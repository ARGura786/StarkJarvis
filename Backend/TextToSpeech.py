import requests  # Import requests to call the Fish Audio text-to-speech API.
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

# Fish Audio text-to-speech endpoint.
TTS_URL = "https://api.fish.audio/v1/tts"

# Path where the generated audio is stored.
OutputFile = BASE_DIR / "Data" / "speech.mp3"

# Function to convert text into an audio file using Fish Audio.
def TextToAudioFile(Text):
    if not FishAPIKey:
        raise ValueError("FishAPIKey is missing from the .env file.")

    # Remove the previous audio file, if any.
    if OutputFile.exists():
        OutputFile.unlink()

    headers = {
        "Authorization": f"Bearer {FishAPIKey}",
        "Content-Type": "application/json",
        "model": FishModel,
    }

    payload = {
        "text": str(Text),
        "format": "mp3",
    }

    # Use a specific voice when one is configured.
    if FishVoiceId:
        payload["reference_id"] = FishVoiceId

    response = requests.post(TTS_URL, headers=headers, json=payload, timeout=120)

    # Surface the API's error message instead of a bare status code.
    if response.status_code != 200:
        raise RuntimeError(f"Fish Audio TTS failed ({response.status_code}): {response.text[:500]}")

    # Save the generated audio to disk.
    with open(OutputFile, "wb") as f:
        f.write(response.content)

    return OutputFile

# Function to play the generated audio file.
def PlayAudio(FilePath, func=lambda: True):
    pygame.mixer.init()
    try:
        pygame.mixer.music.load(str(FilePath))
        pygame.mixer.music.play()

        # Keep playing until the audio ends or the caller asks to stop.
        while pygame.mixer.music.get_busy():
            if func() is False:
                break
            pygame.time.Clock().tick(10)
    finally:
        pygame.mixer.music.stop()
        pygame.mixer.quit()

# Main text-to-speech function.
def TextToSpeech(Text, func=lambda: True):
    if not Text or not str(Text).strip():
        return False

    try:
        audio_file = TextToAudioFile(Text)
        PlayAudio(audio_file, func)
        return True
    except Exception as e:
        print(f"Error in TTS: {e}")
        return False

# Main program entry point.
if __name__ == "__main__":
    print(TextToSpeech(input("Enter the text to speak: ")))
