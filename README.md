# StarkJarvis

A Python-based desktop AI assistant (Jarvis) with a PyQt5 GUI, voice interaction,
chat, automation, real-time web search and image generation.

> Status: early scaffold. Source files are in place and the implementation is being built.

## Tech Stack

- **Python 3.12**
- **PyQt5** – desktop GUI
- **Groq / Cohere** – LLM inference
- **edge-tts** – text to speech
- **SpeechRecognition / pygame** – speech input and audio playback
- **Selenium + googlesearch-python + bs4** – real-time search
- **pywhatkit, AppOpener, pyautogui** – desktop automation

## Project Structure

```
StarkJarvis/
├── main.py                  # Application entry point
├── requirements.txt         # Python dependencies
├── .env                     # API keys (not tracked)
├── Backend/                 # Core logic
│   ├── Model.py             # LLM / model configuration
│   ├── Chatbot.py           # Chat handling
│   ├── SpeechToText.py      # Voice input
│   ├── TextToSpeech.py      # Voice output
│   ├── RealtimeSearchEngine.py  # Live web search
│   ├── ImageGeneration.py   # Image generation
│   └── Automation.py        # OS / app automation
├── Frontend/                # GUI and UI state
│   ├── GUI.py               # PyQt5 interface
│   ├── Graphics/            # UI assets
│   └── Files/               # Runtime state (.data files)
│       ├── Responses.data
│       ├── Database.data
│       ├── ImageGeneration.data
│       ├── Mic.data
│       └── Status.data
└── Data/                    # Local data / generated files
```

## Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/ARGura786/StarkJarvis.git
   cd StarkJarvis
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv arjarvis
   arjarvis\Scripts\activate      # Windows
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file in the project root and add your API keys:
   ```env
   GroqAPIKey=your_key_here
   CohereAPIKey=your_key_here
   ```

5. Run the assistant:
   ```bash
   python main.py
   ```

## Notes

- `.env` and virtual environments are ignored by Git.
- The `.data` files under `Frontend/Files` store runtime state and UI data.
- Requires a working microphone for voice features.
