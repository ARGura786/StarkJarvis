import re  # Import re to detect Hindi (Devanagari) text.
import speech_recognition as sr  # Import speech_recognition for direct microphone capture.
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait  # Import a pool to try languages in parallel.
from dotenv import dotenv_values  # Import dotenv_values to read environment variables from a .env file.
from pathlib import Path  # Import Path to build reliable paths to the project files.

# Base directory of the project (one level above the Backend folder).
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from the .env file at the project root.
env_vars = dotenv_values(BASE_DIR / ".env")

# Get the input language setting from the environment variables.
InputLanguage = env_vars.get("InputLanguage") or "en"

# Define the path for temporary files.
TempDirPath = BASE_DIR / "Frontend" / "Files"

# Map short language names to the codes used by the recognizer.
LANGUAGE_MAP = {
    "en": "en-US",
    "english": "en-US",
    "hi": "hi-IN",
    "hindi": "hi-IN",
}

# Languages tried for every recording (English and Hindi).
RECOGNITION_LANGUAGES = ["en-US", "hi-IN"]

# Create a reusable recognizer instance.
recognizer = sr.Recognizer()
recognizer.dynamic_energy_threshold = True
# Wait through natural pauses instead of ending the prompt at the first short gap.
# The old 0.45s/0.3s values cut users off mid-sentence.
recognizer.pause_threshold = 1.0
recognizer.non_speaking_duration = 0.7
# Bound each recognition request so a stalled call cannot hang the pool.
recognizer.operation_timeout = 10

# One pool for every recognition, so threads are not created on each utterance.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="stt")
_ambient_ready = False

# Function to set the assistant's status by writing it to a file.
def SetAssistantStatus(Status):
    with open(TempDirPath / "Status.data", "w", encoding="utf-8") as file:
        file.write(Status)

# Function to modify a query to ensure proper punctuation and formatting.
def QueryModifier(Query):
    new_query = Query.lower().strip()
    query_words = new_query.split()
    question_words = ["how", "what", "who", "where", "when", "why", "which", "whose", "whom", "can you", "what's", "where's", "how's"]

    # Check if the query is a question and add a question mark if necessary.
    if any(word + " " in new_query for word in question_words):
        if query_words[-1][-1] in ['.', '?', '!']:
            new_query = new_query[:-1] + "?"
        else:
            new_query += "?"
    else:
        # Add a period if the query is not a question.
        if query_words[-1][-1] in ['.', '?', '!']:
            new_query = new_query[:-1] + "."
        else:
            new_query += "."

    return new_query.capitalize()

# Common words used to guess which language the user actually spoke.
ENGLISH_HINTS = {
    "a", "am", "an", "and", "are", "can", "close", "could", "date", "did",
    "do", "does", "evening", "give", "good", "hello", "help", "hey", "hi",
    "how", "i", "is", "it", "make", "me", "morning", "music", "my", "name",
    "night", "no", "ok", "okay", "open", "play", "please", "search", "should",
    "stop", "tell", "thank", "thanks", "the", "time", "to", "today", "tomorrow",
    "weather", "what", "what's", "when", "where", "which", "who", "why",
    "would", "yes", "you", "your",
}

HINDI_HINTS = {
    "अच्छा", "आज", "आप", "कल", "कहाँ", "कहां", "काम", "कितना", "कितनी",
    "कैसे", "कौन", "क्या", "क्यों", "कब", "खोलो", "गाना", "चलाओ", "जी",
    "ठीक", "तुम", "दोस्त", "धन्यवाद", "नमस्ते", "नमस्कार", "नहीं", "बताओ",
    "बताइए", "बंद", "भाई", "मदद", "मैं", "मौसम", "समय", "हाँ", "हां", "है",
    "हैं", "हूँ", "हूं", "शुक्रिया",
}

# Count how many words in the text are known words of a language.
def _HintScore(Text, Hints):
    words = re.findall(r"[a-z']+|[\u0900-\u097F]+", str(Text).lower())
    return sum(1 for word in words if word in Hints)

# Pick the transcript that looks like the language the user actually spoke.
def _ChooseResult(Results):
    english = Results.get("en-US", "")
    hindi = Results.get("hi-IN", "")

    if not english:
        return hindi
    if not hindi:
        return english

    english_score = _HintScore(english, ENGLISH_HINTS)
    hindi_score = _HintScore(hindi, HINDI_HINTS)

    if hindi_score > english_score:
        return hindi
    if english_score > hindi_score:
        return english

    # Neither transcript contains known words: use the configured language.
    if str(InputLanguage).lower().startswith("hi"):
        return hindi
    return english

# Recognize speech in English and Hindi, then choose the best transcript.
def _Recognize(Audio):
    results = {}
    futures = {
        _executor.submit(recognizer.recognize_google, Audio, language=language): language
        for language in RECOGNITION_LANGUAGES
    }

    pending = set(futures)
    # Take results as they arrive, but do not let the slower language add a long wait
    # once one language already produced text.
    while pending:
        grace = 0.3 if any(results.values()) else 15
        done, pending = wait(pending, timeout=grace, return_when=FIRST_COMPLETED)
        if not done:
            break
        for future in done:
            language = futures[future]
            try:
                results[language] = future.result().strip()
            except sr.UnknownValueError:
                results[language] = ""
            except sr.RequestError as e:
                print(f"Speech recognition service error: {e}")
                results[language] = ""

    return _ChooseResult(results)

# Calibrate the microphone once, before the first prompt, so the user's first
# words are not treated as background noise.
def PrepareMicrophone():
    global _ambient_ready
    if _ambient_ready:
        return True
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
        _ambient_ready = True
        return True
    except Exception as e:
        print(f"Microphone error: {e}")
        return False

# Function to perform speech recognition using the microphone.
def SpeechRecognition():
    if not _ambient_ready:
        PrepareMicrophone()

    try:
        with sr.Microphone() as source:
            SetAssistantStatus("Listening...")
            # Allow a long prompt: wait 15s for speech to start and record up to 45s.
            Audio = recognizer.listen(source, timeout=15, phrase_time_limit=45)
    except sr.WaitTimeoutError:
        # No speech was detected within the timeout.
        SetAssistantStatus("")
        return ""
    except OSError as e:
        print(f"Microphone error: {e}")
        SetAssistantStatus("")
        return ""

    SetAssistantStatus("Recognizing...")
    Text = _Recognize(Audio)

    if not Text:
        SetAssistantStatus("")
        return ""

    return QueryModifier(Text)

# Main execution block.
if __name__ == "__main__":
    while True:
        # Continuously perform speech recognition and print the recognized text.
        Text = SpeechRecognition()
        if Text:
            print(Text)
