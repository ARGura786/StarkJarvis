from exa_py import Exa  # Import Exa to perform real-time web searches.
from groq import Groq  # Importing the Groq library to use its API.
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
GroqAPIKey = env_vars.get("GroqAPIKey")
ExaAPIKey = env_vars.get("ExaAPIKey")

# Initialize the Groq client with the provided API key.
client = Groq(api_key=GroqAPIKey)

# Initialize the Exa client with the provided API key.
exa = Exa(api_key=ExaAPIKey)

# Define the system instructions for the chatbot.
System = f"""Hello, I am {Username}, You are a very accurate and advanced AI chatbot named {Assistantname} which also has real-time up-to-date information from the internet.
*** Provide Answers In a Professional Way, make sure to add full stops, commas, question marks and use proper grammar.***
*** Just answer the question from the provided data in a professional way. ***"""

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
        num_results=5,
        contents={"text": {"max_characters": 1000}}  # Include a trimmed page text for context.
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

# Function to handle real-time search queries and generate a response.
def RealtimeSearchEngine(prompt):
    global messages

    # Load the existing chat log.
    with open(CHAT_LOG, "r") as f:
        messages = load(f)

    # Append the user's query to the messages list.
    messages.append({"role": "user", "content": f"{prompt}"})

    # Add the search results to the system instructions for this request.
    SystemChatBot.append({"role": "system", "content": ExaSearch(prompt)})

    try:
        # Send the query to the Groq API.
        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",  # Specify the Groq AI model to use.
            messages=SystemChatBot + [{"role": "system", "content": Information()}] + messages,  # Include instructions, real-time info, and chat history.
            max_tokens=2048,  # Limit the maximum tokens in the response.
            temperature=0.7,  # Adjust the randomness of the response.
            top_p=1,  # Use nucleus sampling to control diversity.
            stream=True,  # Enable streaming responses.
            stop=None  # Allow the model to determine when to stop.
        )

        Answer = ""  # Initialize an empty string to store the AI's response.

        # Process the streamed response chunks.
        for chunk in completion:
            if chunk.choices[0].delta.content:  # Check if there's content in the current chunk.
                Answer += chunk.choices[0].delta.content  # Append the content to the answer.

        Answer = Answer.strip().replace("</s>", "")  # Clean up the response.

        # Append the chatbot's response to the messages list.
        messages.append({"role": "assistant", "content": Answer})

        # Save the updated chat log only after the full response is ready.
        with open(CHAT_LOG, "w") as f:
            dump(messages, f, indent=4)

        # Return the formatted response.
        return AnswerModifier(Answer=Answer)
    finally:
        # Always remove the temporary search context from the system instructions.
        SystemChatBot.pop()

# Main program entry point.
if __name__ == "__main__":
    while True:
        prompt = input("Enter your query: ")  # Prompt the user for a query.
        print(RealtimeSearchEngine(prompt))  # Print the search-based response.
