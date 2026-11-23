import asyncio  # Import asyncio so search and speech can share one event loop.
from exa_py import Exa  # Import Exa to perform real-time web searches.
from json import load, dump  # Import functions to read and write JSON files.
import datetime  # Import the datetime module for real-time date and time information.
from dotenv import dotenv_values  # Import dotenv_values to read environment variables from a .env file.
from pathlib import Path  # Import Path to build reliable paths to the project files.

# Base directory of the project (one level above the Backend folder).
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from the .env file at the project root.
env_vars = dotenv_values(BASE_DIR / ".env")

# Retrieve environment variables for the chatbot configuration.
Username = env_vars.get("Username")
Assistantname = env_vars.get("Assistantname")
ExaAPIKey = env_vars.get("ExaAPIKey")

# Initialize the Exa client with the provided API key.
exa = Exa(api_key=ExaAPIKey)

# Define the system instructions for the chatbot.
System = f"""Hello, I am {Username}, You are a very accurate and advanced AI chatbot named {Assistantname} which also has real-time up-to-date information from the internet.
*** Reply in the same language as the user. If the user writes in English, reply in English; otherwise reply in Hindi. ***
*** Provide Answers In a Professional Way, make sure to add full stops, commas, question marks and use proper grammar.***
*** Just answer the question from the provided data in a professional way. ***
*** Put the direct answer in the first short sentence, then add at most one more sentence. ***"""

# Path to the chat log file.
CHAT_LOG = BASE_DIR / "Data" / "ChatLog.json"

# Try to load the chat log from a JSON file, or create an empty one if it doesn't exist.
try:
    with open(CHAT_LOG, "r") as f:
        messages = load(f)
except Exception:
    with open(CHAT_LOG, "w") as f:
        dump([], f)

# Function to perform a web search with Exa and format the results.
def ExaSearch(query):
    results = exa.search(
        query,
        num_results=3,
        contents={"text": {"max_characters": 400}}  # Keep the prompt small so the model starts sooner.
    )
    Answer = f"The search results for '{query}' are:\n[start]\n"

    for i in results.results:
        Answer += f"Title: {i.title}\nDescription: {(i.text or '').strip()}\n\n"

    Answer += "[end]"
    return Answer

# Function to clean up the answer by removing empty lines.
def AnswerModifier(Answer):
    lines = Answer.split('\n')
    non_empty_lines = [line for line in lines if line.strip()]
    modified_answer = '\n'.join(non_empty_lines)
    return modified_answer

# Predefined chatbot conversation system message and an initial user message.
SystemChatBot = [
    {"role": "system", "content": System},
    {"role": "user", "content": "Hi"},
    {"role": "assistant", "content": "Hello, how can I help you?"}
]

# Function to get real-time date and time information.
def Information():
    data = ""
    current_date_time = datetime.datetime.now()  # Get the current date and time.
    day = current_date_time.strftime("%A")  # Day of the week.
    date = current_date_time.strftime("%d")  # Day of the month.
    month = current_date_time.strftime("%B")  # Full month name.
    year = current_date_time.strftime("%Y")  # Year.
    hour = current_date_time.strftime("%H")  # Hour in 24-hour format.
    minute = current_date_time.strftime("%M")  # Minute.
    second = current_date_time.strftime("%S")  # Second.

    data += "Use This Real-time Information if needed:\n"
    data += f"Day: {day}\n"
    data += f"Date: {date}\n"
    data += f"Month: {month}\n"
    data += f"Year: {year}\n"
    data += f"Time: {hour} hours, {minute} minutes, {second} seconds.\n"
    return data

# Search, then stream the answer. The search runs in a thread so the event loop stays free.
async def RealtimeSearchStream(prompt):
    global messages

    from Chatbot import stream_groq_sentences

    def load_history():
        with open(CHAT_LOG, "r", encoding="utf-8") as f:
            return load(f)

    messages = await asyncio.to_thread(load_history)
    messages.append({"role": "user", "content": f"{prompt}"})

    # Exa is synchronous; keep it off the event loop.
    search = await asyncio.to_thread(ExaSearch, prompt)
    request = (
        SystemChatBot
        + [{"role": "system", "content": search}, {"role": "system", "content": Information()}]
        + messages[-12:]
    )
    sink = {}

    try:
        async for piece in stream_groq_sentences(request, sink):
            yield piece
    finally:
        answer = (sink.get("text") or "").strip()
        if answer:
            messages.append({"role": "assistant", "content": answer})

            def save():
                with open(CHAT_LOG, "w", encoding="utf-8") as f:
                    dump(messages, f, indent=4, ensure_ascii=False)

            await asyncio.to_thread(save)

# Function to handle real-time search queries and generate a response.
def RealtimeSearchEngine(prompt):
    async def _collect():
        parts = []
        async for piece in RealtimeSearchStream(prompt):
            parts.append(piece)
        return AnswerModifier(Answer=" ".join(parts))

    return asyncio.run(_collect())

# Main program entry point.
if __name__ == "__main__":
    while True:
        prompt = input("Enter your query: ")  # Prompt the user for a query.
        print(RealtimeSearchEngine(prompt))  # Print the search-based response.
