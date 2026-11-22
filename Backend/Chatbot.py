import json  # Import the json module to handle JSON data.
from json import load, dump  # Import functions to read and write JSON files.
import datetime  # Import the datetime module for real-time date and time information.
import time  # Import time to add a delay between retries.
import requests  # Import requests to handle request-related exceptions.
from groq import (  # Import the Groq client and its error types.
    Groq,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    BadRequestError,
    UnprocessableEntityError,
)
from dotenv import dotenv_values  # Import dotenv_values to read environment variables from a .env file.
from pathlib import Path  # Import Path to build reliable paths to the project files.

# Base directory of the project (one level above the Backend folder).
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from the .env file at the project root.
env_vars = dotenv_values(BASE_DIR / ".env")

# Retrieve specific environment variables for username, assistant name, and API key.
Username = env_vars.get("Username")
Assistantname = env_vars.get("Assistantname")
GroqAPIKey = env_vars.get("GroqAPIKey")

# Initialize the Groq client using the provided API key.
client = Groq(api_key=GroqAPIKey)

# Initialize an empty list to store chat messages.
messages = []

# Define a system message that provides context to the AI chatbot about its role and behavior.
System = f"""Hello, I am {Username}, You are a very accurate and advanced AI chatbot named {Assistantname} which also has real-time up-to-date information from the internet.
*** Do not tell time until I ask, do not talk too much, just answer the question.***
*** Reply in only English, even if the question is in Hindi, reply in English.***
*** Do not provide notes in the output, just answer the question and never mention your training data. ***
"""

# A list of system instructions for the chatbot.
SystemChatBot = [
    {"role": "system", "content": System}
]

# Path to the chat log file.
CHAT_LOG = BASE_DIR / "Data" / "ChatLog.json"

# Retry configuration for recoverable Groq request failures.
MAX_RETRIES = 2  # Number of retries after the first attempt.
RETRY_DELAY = 1  # Seconds to wait between attempts.

# Errors that indicate a permanent problem; retrying them cannot succeed.
PERMANENT_ERRORS = (
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    BadRequestError,
    UnprocessableEntityError,
)

# Attempt to load the chat log from a JSON file.
try:
    with open(CHAT_LOG, "r") as f:
        messages = load(f)
except FileNotFoundError:
    with open(CHAT_LOG, "w") as f:
        dump([], f)
except json.JSONDecodeError:
    print("ChatLog.json is empty or corrupted. Initializing with an empty list.")
    with open(CHAT_LOG, "w") as f:
        dump([], f)

# Function to get real-time date and time information.
def RealtimeInformation():
    current_date_time = datetime.datetime.now()  # Get the current date and time.
    day = current_date_time.strftime("%A")  # Day of the week.
    date = current_date_time.strftime("%d")  # Day of the month.
    month = current_date_time.strftime("%B")  # Full month name.
    year = current_date_time.strftime("%Y")  # Year.
    hour = current_date_time.strftime("%H")  # Hour in 24-hour format.
    minute = current_date_time.strftime("%M")  # Minute.
    second = current_date_time.strftime("%S")  # Second.

    # Format the information into a string.
    data = f"Please use this real-time information if needed:\n"
    data += f"Day: {day}\nDate: {date}\nMonth: {month}\nYear: {year}\n"
    data += f"Time: {hour} hours, {minute} minutes, {second} seconds.\n"
    return data

# Function to modify the chatbot's response for better formatting.
def AnswerModifier(Answer):
    lines = Answer.split('\n')  # Split the response into lines.
    non_empty_lines = [line for line in lines if line.strip()]  # Remove empty lines.
    modified_answer = '\n'.join(non_empty_lines)  # Join the cleaned lines back together.
    return modified_answer

# Main chatbot function to handle user queries.
def ChatBot(Query):
    """ This function sends the user's query to the chatbot and returns the AI's response. """

    # Retry recoverable failures a bounded number of times instead of recursing.
    for attempt in range(MAX_RETRIES + 1):
        try:
            # Load the existing chat log. Only reset it when it is unreadable.
            try:
                with open(CHAT_LOG, "r") as f:
                    messages = load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                print("ChatLog.json is empty or corrupted. Initializing with an empty list.")
                messages = []
                with open(CHAT_LOG, "w") as f:
                    dump(messages, f, indent=4)

            # Append the user's query to the messages list.
            messages.append({"role": "user", "content": f"{Query}"})

            # Send the query to the Groq API.
            completion = client.chat.completions.create(
                model="llama-3.3-70b-versatile",  # Specify the Groq AI model to use.
                messages=SystemChatBot + [{"role": "system", "content": RealtimeInformation()}] + messages,  # Include system instructions, real-time info, and chat history.
                max_tokens=1024,  # Limit the maximum tokens in the response.
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

            Answer = Answer.replace("</s>", "")  # Clean up any unwanted tokens from the response.

            # Append the chatbot's response to the messages list.
            messages.append({"role": "assistant", "content": Answer})

            # Save the updated chat log only after the full response is ready.
            with open(CHAT_LOG, "w") as f:
                dump(messages, f, indent=4)

            # Return the formatted response.
            return AnswerModifier(Answer=Answer)

        except PERMANENT_ERRORS as e:
            # Retrying cannot fix these, so stop immediately and keep the saved history.
            print(f"Error: {e}")
            return "An error occurred, please try again later."

        except Exception as e:
            # Preserve the saved history and retry recoverable failures.
            print(f"Error: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * (attempt + 1))

    return "An error occurred, please try again later."

# Main program entry point.
if __name__ == "__main__":
    while True:
        user_input = input("Enter Your Question: ")  # Prompt the user for a question.
        print(ChatBot(user_input))  # Call the chatbot function and print its response.
