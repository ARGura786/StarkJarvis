import asyncio  # Import asyncio to run speech synthesis and playback concurrently.
import re  # Import re to split responses into sentences.
import shutil  # Import shutil to clean up temporary audio files.
import tempfile  # Import tempfile to create a working directory for audio parts.
import requests  # Import requests to call the Fish Audio text-to-speech API (sync helper).
import aiohttp  # Import aiohttp for non-blocking Fish Audio requests.
import pygame  # Import pygame to play the generated audio.
from dotenv import dotenv_values  # Import dotenv_values to read environment variables from a .env file.
from pathlib import Path  # Import Path to build reliable paths to the project files.

# Base directory of the project (one level above the Backend folder).
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from the .env file at the project root.
env_vars = dotenv_values(BASE_DIR / ".env")

# Retrieve the Fish Audio configuration.
FishAPIKey = env_vars.get("FishAPIKey")
FishVoiceId = env_vars.get("FishVoiceId")  # Optional voice model ID.
FishModel = env_vars.get("FishModel") or "s2.1-pro-free"  # Free development TTS model.
Assistantname = env_vars.get("Assistantname") or "Jarvis"  # Name shown in the chat loop.

# Fish Audio text-to-speech endpoint.
TTS_URL = "https://api.fish.audio/v1/tts"

# Path where the generated audio is stored.
OutputFile = BASE_DIR / "Data" / "speech.mp3"

# Build the headers required by the Fish Audio API.
def _BuildHeaders():
    return {
        "Authorization": f"Bearer {FishAPIKey}",
        "Content-Type": "application/json",
        "model": FishModel,
    }

# Build the request body required by the Fish Audio API.
def _BuildPayload(Text):
    payload = {
        "text": str(Text),
        "format": "mp3",
    }

    # Use a specific voice when one is configured.
    if FishVoiceId:
        payload["reference_id"] = FishVoiceId

    return payload

# Function to convert text into an audio file using Fish Audio (synchronous).
def TextToAudioFile(Text):
    if not FishAPIKey:
        raise ValueError("FishAPIKey is missing from the .env file.")

    # Remove the previous audio file, if any.
    if OutputFile.exists():
        OutputFile.unlink()

    response = requests.post(
        TTS_URL,
        headers=_BuildHeaders(),
        json=_BuildPayload(Text),
        timeout=120,
    )

    # Surface the API's error message instead of a bare status code.
    if response.status_code != 200:
        raise RuntimeError(f"Fish Audio TTS failed ({response.status_code}): {response.text[:500]}")

    # Save the generated audio to disk.
    with open(OutputFile, "wb") as f:
        f.write(response.content)

    return OutputFile

# Asynchronously fetch the audio for a single piece of text.
async def _FetchAudio(Session, Text, FilePath):
    if not FishAPIKey:
        raise ValueError("FishAPIKey is missing from the .env file.")

    async with Session.post(
        TTS_URL,
        headers=_BuildHeaders(),
        json=_BuildPayload(Text),
        timeout=aiohttp.ClientTimeout(total=120),
    ) as response:
        if response.status != 200:
            body = await response.text()
            raise RuntimeError(f"Fish Audio TTS failed ({response.status}): {body[:500]}")
        data = await response.read()

    FilePath.write_bytes(data)
    return FilePath

# Split a response into sentences so speech can start as early as possible.
def _SplitSentences(Text):
    parts = re.split(r'(?<=[.!?])\s+', str(Text).strip())
    return [part for part in parts if part.strip()]

# Play an audio file without blocking the event loop.
def _PlayFile(FilePath, func=lambda: True):
    if not pygame.mixer.get_init():
        pygame.mixer.init()

    pygame.mixer.music.load(str(FilePath))
    pygame.mixer.music.play()

    # Keep playing until the audio ends or the caller asks to stop.
    while pygame.mixer.music.get_busy():
        if func() is False:
            pygame.mixer.music.stop()
            break
        pygame.time.Clock().tick(10)

    # Release the file handle so the audio file can be deleted on Windows.
    try:
        pygame.mixer.music.unload()
    except Exception:
        pass

# Stop playback and release the mixer.
def _StopPlayback():
    try:
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
            pygame.mixer.quit()
    except Exception:
        pass

# Function to play the generated audio file (synchronous).
def PlayAudio(FilePath, func=lambda: True):
    pygame.mixer.init()
    try:
        _PlayFile(FilePath, func)
    finally:
        _StopPlayback()

# Speak a response sentence by sentence, synthesizing the next part while the
# current part is playing so the reply starts almost immediately.
async def SpeakAsync(Text, func=lambda: True):
    if not Text or not str(Text).strip():
        return False

    sentences = _SplitSentences(Text)
    if not sentences:
        return False

    work_dir = Path(tempfile.mkdtemp(prefix="jarvis_tts_"))
    next_audio = None

    try:
        async with aiohttp.ClientSession() as session:
            def synthesize(index, sentence):
                return _FetchAudio(session, sentence, work_dir / f"part_{index}.mp3")

            # Start generating the first sentence right away.
            next_audio = asyncio.create_task(synthesize(0, sentences[0]))

            for index in range(len(sentences)):
                audio_path = await next_audio

                # Start generating the next sentence while this one plays.
                if index + 1 < len(sentences):
                    next_audio = asyncio.create_task(synthesize(index + 1, sentences[index + 1]))

                await asyncio.to_thread(_PlayFile, audio_path, func)
                try:
                    audio_path.unlink(missing_ok=True)
                except OSError:
                    pass  # Windows may still hold the handle briefly; temp dir is cleaned later.

                if func() is False:
                    break

        return True
    finally:
        # Cancel any in-flight synthesis so it does not outlive the session.
        if next_audio is not None and not next_audio.done():
            next_audio.cancel()
            try:
                await next_audio
            except BaseException:
                pass

        await asyncio.to_thread(_StopPlayback)
        shutil.rmtree(work_dir, ignore_errors=True)

# Main text-to-speech function (kept synchronous for existing callers).
def TextToSpeech(Text, func=lambda: True):
    if not Text or not str(Text).strip():
        return False

    try:
        return asyncio.run(SpeakAsync(Text, func))
    except Exception as e:
        print(f"Error in TTS: {e}")
        return False

# Function to run a continuous voice chat session.
async def ContinuousChat():
    # Imported here so the microphone and chat setup only runs when a session starts.
    from SpeechToText import SpeechRecognition
    from Chatbot import ChatBot

    print("Voice chat started. Say 'exit' or 'bye' to stop.")

    try:
        while True:
            try:
                # Listen for the user's voice input without blocking the event loop.
                user_input = await asyncio.to_thread(SpeechRecognition)
            except Exception as e:
                print(f"Speech recognition error: {e}")
                continue

            if not user_input:
                continue

            print(f"You: {user_input}")

            # Stop the session when the user says goodbye.
            if user_input.lower().strip(" .?!") in {"exit", "quit", "bye", "goodbye"}:
                break

            # Generate the reply, then speak it.
            response = await asyncio.to_thread(ChatBot, user_input)
            print(f"{Assistantname}: {response}")
            await SpeakAsync(response)

    except KeyboardInterrupt:
        print("\nVoice chat stopped.")
    finally:
        print("Goodbye.")

# Main program entry point.
if __name__ == "__main__":
    asyncio.run(ContinuousChat())
