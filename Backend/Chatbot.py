import asyncio  # Import asyncio so generation can overlap with speech.
import json  # Import the json module to handle JSON data.
import re  # Import re to split a streaming reply into speakable chunks.
from json import load, dump  # Import functions to read and write JSON files.
import datetime  # Import the datetime module for real-time date and time information.
from groq import (  # Import the Groq clients and their error types.
    AsyncGroq,
    Groq,
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    BadRequestError,
    UnprocessableEntityError,
    RateLimitError,
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

# Fast default. qwen3.8-27b with reasoning disabled answers much sooner than gpt-oss-120b.
GroqModel = env_vars.get("GroqModel") or "qwen/qwen3.8-27b"

# How many recent messages are sent to the model. A shorter prompt returns sooner.
MAX_HISTORY = 12

# Initialize the synchronous Groq client. The sync one stays for compatibility.
client = Groq(api_key=GroqAPIKey, timeout=20.0, max_retries=0)

# The async client and lock must belong to the event loop that uses them. The CLI
# calls asyncio.run() per query, which closes the loop each time; reusing a client
# from a closed loop fails with "Connection error" (the pool holds connections
# bound to the dead loop). Keep one entry per running loop instead.
_loop_state = {}


def _loop_entry():
    loop = asyncio.get_running_loop()
    entry = _loop_state.get(loop)
    if entry is None:
        entry = {
            "lock": asyncio.Lock(),
            "client": AsyncGroq(api_key=GroqAPIKey, timeout=20.0, max_retries=0),
        }
        _loop_state[loop] = entry
    return entry


async def _close_loop_entry():
    entry = _loop_state.pop(asyncio.get_running_loop(), None)
    if entry is not None:
        await entry["client"].close()

# Initialize an empty list to store chat messages.
messages = []

# Define a system message that provides context to the AI chatbot about its role and behavior.
System = f"""Hello, I am {Username}, You are a very accurate and advanced AI chatbot named {Assistantname} which also has real-time up-to-date information from the internet.
*** Do not tell time until I ask. ***
*** Match the length to the question: keep greetings and simple facts short, but when the user asks for an explanation, steps, comparison, code, or details, give a complete, well-structured answer with as much length as the topic needs. Never cut an explanation short just to be brief. ***
*** Reply in the same language as the user. If the user writes in English, reply in English; otherwise reply in Hindi. ***
*** अगर उपयोगकर्ता अंग्रेज़ी में लिखे तो अंग्रेज़ी में उत्तर दें, अन्यथा हिंदी में उत्तर दें। ***
*** Do not provide notes in the output, just answer the question and never mention your training data. ***
"""

# A list of system instructions for the chatbot.
SystemChatBot = [
    {"role": "system", "content": System}
]

# Path to the chat log file.
CHAT_LOG = BASE_DIR / "Data" / "ChatLog.json"

# Retry configuration for recoverable Groq request failures.
MAX_RETRIES = 2  # Two extra attempts; rate limits wait as long as Groq asks.
RETRY_DELAY = 0.35  # Seconds to wait between attempts.
STALL_TIMEOUT = 30.0  # Give up if the stream sends no new text for this many seconds.
MAX_OUTPUT_TOKENS = 2048  # Room for a detailed answer when the question needs one.

# Errors that indicate a permanent problem; retrying them cannot succeed.
PERMANENT_ERRORS = (
    AuthenticationError,
    PermissionDeniedError,
    NotFoundError,
    BadRequestError,
    UnprocessableEntityError,
)


def _retry_after_seconds(error, default=5.0, cap=65.0):
    """ Read how long Groq asked us to wait before retrying a rate limit. """
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or {}
    value = headers.get("retry-after")
    if value:
        try:
            return min(max(float(value), 0.5), cap)
        except (TypeError, ValueError):
            pass

    match = re.search(r"try again in\s+([\d.]+)\s*(ms|s)", str(error), re.IGNORECASE)
    if match:
        seconds = float(match.group(1))
        if match.group(2).lower() == "ms":
            seconds /= 1000.0
        return min(max(seconds, 0.5), cap)
    return default

# Attempt to load the chat log from a JSON file.
try:
    with open(CHAT_LOG, "r", encoding="utf-8") as f:
        messages = load(f)
except FileNotFoundError:
    with open(CHAT_LOG, "w", encoding="utf-8") as f:
        dump([], f)
except json.JSONDecodeError:
    print("ChatLog.json is empty or corrupted. Initializing with an empty list.")
    with open(CHAT_LOG, "w", encoding="utf-8") as f:
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

def _get_lock():
    return _loop_entry()["lock"]

# Reasoning tokens delay the first spoken word, so keep them off when the model allows it.
def _speed_kwargs():
    if str(GroqModel).startswith("qwen/"):
        return {"reasoning_effort": "none", "reasoning_format": "hidden"}
    return {"reasoning_effort": "low", "reasoning_format": "hidden"}

# Pull finished sentences, or a long enough clause, so speech can start early.
def _take_chunks(buffer, flush=False):
    chunks = []
    while buffer:
        sentence = re.match(r"^(.{8,}?[.!?।])(?:\s+|$)", buffer, re.S)
        if sentence:
            chunks.append(sentence.group(1).strip())
            buffer = buffer[sentence.end():]
            continue
        clause = re.match(r"^(.{36,}?[,;:—])\s+", buffer, re.S)
        if clause:
            chunks.append(clause.group(1).strip())
            buffer = buffer[clause.end():]
            continue
        if len(buffer) >= 80:
            cut = buffer[:80].rfind(" ")
            if cut >= 24:
                chunks.append(buffer[:cut].strip())
                buffer = buffer[cut + 1:]
                continue
        break
    if flush and buffer.strip():
        chunks.append(buffer.strip())
        buffer = ""
    return chunks, buffer

# Write the chat log without blocking the event loop.
async def _persist(snapshot):
    def write():
        with open(CHAT_LOG, "w", encoding="utf-8") as f:
            dump(snapshot, f, indent=4, ensure_ascii=False)
    await asyncio.to_thread(write)

# Stream speakable chunks as soon as the model produces them.
async def stream_groq_sentences(request_messages, sink):
    sink["text"] = ""
    sink["finish"] = None
    buffer = ""
    raw = ""

    stream = await _loop_entry()["client"].chat.completions.create(
        model=GroqModel,
        messages=request_messages,
        max_tokens=MAX_OUTPUT_TOKENS,
        temperature=0.6,
        top_p=1,
        stream=True,
        stop=None,
        **_speed_kwargs(),
    )

    # Keep-alive chunks can arrive forever without any answer text, so track the
    # last time real content arrived instead of trusting the socket timeout alone.
    loop = asyncio.get_running_loop()
    deadline = loop.time() + STALL_TIMEOUT

    async for chunk in stream:
        if chunk.choices:
            choice = chunk.choices[0]
            delta = choice.delta.content or ""
            if delta:
                deadline = loop.time() + STALL_TIMEOUT
                raw += delta
                buffer += delta
                ready, buffer = _take_chunks(buffer)
                sink["text"] = raw
                for piece in ready:
                    yield piece
            if choice.finish_reason:
                sink["finish"] = choice.finish_reason
        if loop.time() > deadline:
            raise TimeoutError("Groq stopped sending the reply.")

    raw = raw.replace("</s>", "")
    sink["text"] = raw
    ready, _ = _take_chunks(buffer.replace("</s>", ""), flush=True)
    for piece in ready:
        yield piece

# Function to modify the chatbot's response for better formatting.
def AnswerModifier(Answer):
    lines = Answer.split('\n')  # Split the response into lines.
    non_empty_lines = [line for line in lines if line.strip()]  # Remove empty lines.
    modified_answer = '\n'.join(non_empty_lines)  # Join the cleaned lines back together.
    return modified_answer

# Latest background save, so the synchronous helper can wait for it before exiting.
_last_save = None

def _save_soon(snapshot):
    global _last_save
    _last_save = asyncio.create_task(_persist(snapshot))

# Speak the reply as it is generated. Call this from a running event loop.
async def ChatBotStream(Query):
    """ Yield speakable pieces of the reply as soon as each one is ready. """
    global messages

    # Local commands (open apps, WhatsApp, typing) run before the model.
    try:
        from Automation import HandleCommand
        action = await asyncio.to_thread(HandleCommand, Query)
    except Exception as e:
        print(f"Automation error: {e}")
        action = None

    if action is not None:
        async with _get_lock():
            messages.append({"role": "user", "content": f"{Query}"})
            messages.append({"role": "assistant", "content": action})
            _save_soon(list(messages))
        yield action
        return

    async with _get_lock():
        messages.append({"role": "user", "content": f"{Query}"})
        history = messages[-MAX_HISTORY:]
        sink = {}
        emitted = False
        saved = False

        try:
            for attempt in range(MAX_RETRIES + 1):
                try:
                    request = SystemChatBot + [{"role": "system", "content": RealtimeInformation()}] + history
                    async for piece in stream_groq_sentences(request, sink):
                        emitted = True
                        yield piece

                    if not (sink.get("text") or "").strip():
                        raise RuntimeError("Groq returned an empty reply.")

                    messages.append({"role": "assistant", "content": sink.get("text", "")})
                    _save_soon(list(messages))
                    saved = True
                    return

                except PERMANENT_ERRORS as e:
                    print(f"Error: {e or type(e).__name__}")
                    break

                except RateLimitError as e:
                    wait = _retry_after_seconds(e)
                    if emitted or attempt >= MAX_RETRIES:
                        print("Error: Groq rate limit reached.")
                        break
                    print(f"Rate limit reached. Waiting {wait:.1f}s before retrying...")
                    await asyncio.sleep(wait)

                except Exception as e:
                    print(f"Error: {e or type(e).__name__}")
                    if emitted or attempt >= MAX_RETRIES:
                        break
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))

            if not emitted:
                yield "An error occurred, please try again later."
        finally:
            # Keep a partial reply if speech already started; otherwise drop the unanswered turn.
            if not saved and messages and messages[-1].get("role") == "user":
                if emitted and sink.get("text"):
                    messages.append({"role": "assistant", "content": sink["text"]})
                    _save_soon(list(messages))
                else:
                    messages.pop()

# Main chatbot function to handle user queries.
def ChatBot(Query):
    """ This function sends the user's query to the chatbot and returns the AI's response. """

    async def _collect():
        try:
            parts = []
            async for piece in ChatBotStream(Query):
                parts.append(piece)
            if _last_save is not None:
                await _last_save
            return AnswerModifier(Answer=" ".join(parts))
        finally:
            # Release the connection pool before asyncio.run() closes the loop.
            await _close_loop_entry()

    return asyncio.run(_collect())

# Print the reply to the terminal while it is still being generated, so a slow
# answer never looks like a frozen program.
def ChatBotConsole(Query):
    async def _run():
        try:
            started = False
            async for piece in ChatBotStream(Query):
                if not started:
                    print(f"{Assistantname}: ", end="", flush=True)
                    started = True
                print(piece, end=" ", flush=True)
            if started:
                print()
            if _last_save is not None:
                await _last_save
        finally:
            await _close_loop_entry()

    asyncio.run(_run())

# Main program entry point.
if __name__ == "__main__":
    while True:
        try:
            user_input = input("Enter Your Question: ")  # Prompt the user for a question.
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input.strip():
            continue

        try:
            ChatBotConsole(user_input)  # Stream the reply as it is generated.
        except KeyboardInterrupt:
            print()
            break
