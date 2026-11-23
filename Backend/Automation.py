"""Local automation commands for Jarvis.

Handles four kinds of spoken/typed commands:
  * open a website or web app in the default browser
  * open a desktop application on the PC
  * send a WhatsApp message
  * type text into the active window

`HandleCommand` returns a short confirmation when it recognises a command, or
None when the query is normal chat and should go to the language model.
"""

import contextlib  # Import contextlib to hide AppOpener's loading banner.
import io  # Import io to capture the banner as text.
import json  # Import json to read the WhatsApp contacts file.
import os  # Import os to start Windows shell URIs and local files.
import re  # Import re to parse natural-language commands.
import shutil  # Import shutil to find executables on PATH.
import subprocess  # Import subprocess to launch desktop programs.
import time  # Import time for small pauses while typing.
import webbrowser  # Import webbrowser to open sites in the default browser.
from pathlib import Path  # Import Path to build reliable paths to project files.
from urllib.parse import quote, quote_plus  # Import helpers to build safe URLs.

# Base directory of the project (one level above the Backend folder).
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "Data"
CONTACTS_FILE = DATA_DIR / "Contacts.json"

# Optional/heavy dependencies are imported only when a command needs them, so
# normal chat and startup stay fast.
_keyboard = None
_pywhatkit = None
_app_opener = None
_app_not_found = None

# Friendly names for websites and web apps.
WEBSITES = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "google drive": "https://drive.google.com",
    "drive": "https://drive.google.com",
    "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com",
    "google calendar": "https://calendar.google.com",
    "calendar": "https://calendar.google.com",
    "google meet": "https://meet.google.com",
    "meet": "https://meet.google.com",
    "whatsapp": "https://web.whatsapp.com",
    "whatsapp web": "https://web.whatsapp.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "x": "https://x.com",
    "twitter": "https://x.com",
    "github": "https://github.com",
    "gitlab": "https://gitlab.com",
    "chatgpt": "https://chatgpt.com",
    "openai": "https://chatgpt.com",
    "gemini": "https://gemini.google.com",
    "claude": "https://claude.ai",
    "spotify": "https://open.spotify.com",
    "netflix": "https://www.netflix.com",
    "amazon": "https://www.amazon.com",
    "flipkart": "https://www.flipkart.com",
    "linkedin": "https://www.linkedin.com",
    "reddit": "https://www.reddit.com",
    "stack overflow": "https://stackoverflow.com",
    "stackoverflow": "https://stackoverflow.com",
    "wikipedia": "https://www.wikipedia.org",
    "twitch": "https://www.twitch.tv",
    "pinterest": "https://www.pinterest.com",
    "telegram": "https://web.telegram.org",
    "telegram web": "https://web.telegram.org",
    "discord": "https://discord.com/app",
    "discord web": "https://discord.com/app",
    "notion": "https://www.notion.so",
    "canva": "https://www.canva.com",
    "medium": "https://medium.com",
    "quora": "https://www.quora.com",
    "zoom": "https://zoom.us",
}

# Search pages used by "search X on <site>" and "play X on youtube".
SEARCH_URLS = {
    "google": "https://www.google.com/search?q={}",
    "youtube": "https://www.youtube.com/results?search_query={}",
    "spotify": "https://open.spotify.com/search/{}",
    "amazon": "https://www.amazon.com/s?k={}",
    "github": "https://github.com/search?q={}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={}",
}

# Desktop apps whose executable name differs from the spoken name.
DESKTOP_ALIASES = {
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "paint": "mspaint",
    "mspaint": "mspaint",
    "file explorer": "explorer",
    "explorer": "explorer",
    "computer": "explorer",
    "this pc": "explorer",
    "my computer": "explorer",
    "file manager": "explorer",
    "files": "explorer",
    "task manager": "taskmgr",
    "taskmgr": "taskmgr",
    "command prompt": "cmd",
    "cmd": "cmd",
    "powershell": "powershell",
    "terminal": "wt",
    "settings": "ms-settings:",
    "control panel": "control",
    "camera": "microsoft.windows.camera:",
    "photos": "ms-photos:",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "outlook": "outlook",
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "firefox": "firefox",
    "brave": "brave",
    "opera": "opera",
    "code": "code",
    "vs code": "code",
    "visual studio code": "code",
    "spotify": "spotify",
    "vlc": "vlc",
    "whatsapp": "whatsapp",
    "telegram": "telegram",
    "discord": "discord",
    "steam": "steam",
    "zoom": "zoom",
    "skype": "skype",
}

# Browsers that can be targeted explicitly ("open youtube in chrome").
BROWSER_ALIASES = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "firefox": "firefox",
    "brave": "brave",
    "opera": "opera",
}

# Common install locations for apps that are usually not on PATH.
KNOWN_PATHS = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    ],
    "msedge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "firefox": [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
    ],
    "brave": [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
    "code": [
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
    ],
    "spotify": [
        r"%APPDATA%\Spotify\Spotify.exe",
    ],
}


# Trim whitespace and surrounding quotes from a parsed value.
def _Text(Value):
    return re.sub(r"\s+", " ", str(Value or "")).strip().strip("\"'")


# Clean an app/site name (the query modifier adds a trailing full stop).
def _Target(Value):
    return _Text(Value).strip(" .,!?;:")


# Clean a spoken app name: drop articles and a trailing "app".
def _AppName(Value):
    name = _Target(Value)
    name = re.sub(r"^(?:the|my)\s+", "", name, flags=re.I)
    name = re.sub(r"\s+(?:app|application)$", "", name, flags=re.I)
    return name.strip()


# Accept a phone number only when it includes a country code.
def _NormalizePhone(Value):
    raw = _Text(Value)
    if not re.fullmatch(r"\+?[\d\s().-]+", raw):
        return None

    digits = re.sub(r"\D", "", raw)
    if not (8 <= len(digits) <= 15):
        return None

    if raw.startswith("+"):
        return "+" + digits
    # A number long enough to contain a country code can be normalised safely.
    if len(digits) >= 11:
        return "+" + digits
    return None


# Return True when the value looks like a domain or a full URL.
def _LooksLikeUrl(Value):
    return bool(re.match(r"^(?:https?://)?[\w-]+(?:\.[\w-]+)+(?:[/?#].*)?$", Value, re.I))


# Load the name -> phone number map, creating an empty file on first use.
def _LoadContacts():
    if not CONTACTS_FILE.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONTACTS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4)
        return {}

    try:
        with open(CONTACTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    return {
        str(name).strip().lower(): phone
        for name, number in data.items()
        if (phone := _NormalizePhone(number))
    }


# Accept either a phone number or a name from Data/Contacts.json.
def ResolveContact(Contact):
    raw = _Text(Contact)
    phone = _NormalizePhone(raw)
    if phone:
        return phone, raw

    contacts = _LoadContacts()
    key = raw.lower()
    if key in contacts:
        return contacts[key], raw

    matches = [name for name in contacts if key and (key in name or name in key)]
    if len(matches) == 1:
        return contacts[matches[0]], matches[0]

    return None, raw


# Import keyboard only when typing is requested.
def _Keyboard():
    global _keyboard
    if _keyboard is None:
        import keyboard
        _keyboard = keyboard
    return _keyboard


# Import pywhatkit only when WhatsApp is requested.
def _PyWhatkit():
    global _pywhatkit
    if _pywhatkit is None:
        import pywhatkit
        _pywhatkit = pywhatkit
    return _pywhatkit


# Import AppOpener without printing its "LOADING APPS..." banner into the chat.
def _AppOpenerModule():
    global _app_opener, _app_not_found
    if _app_opener is None:
        with contextlib.redirect_stdout(io.StringIO()):
            import AppOpener as app_opener
            from AppOpener.features import AppNotFound
        _app_opener = app_opener
        _app_not_found = AppNotFound
    return _app_opener, _app_not_found


# Ask AppOpener to launch an app. Return True only if it actually opened one.
def _TryAppOpener(Name, Closest):
    app_opener, app_not_found = _AppOpenerModule()
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            app_opener.open(Name, match_closest=Closest, output=True, throw_error=True)
    except app_not_found:
        return False
    except Exception:
        return False
    return "OPENING" in output.getvalue().upper()


# Find an executable on PATH or in one of the common install folders.
def _FindExecutable(Command):
    found = shutil.which(Command)
    if found:
        return found

    for raw_path in KNOWN_PATHS.get(Command.lower(), []):
        path = os.path.expandvars(raw_path)
        if os.path.exists(path):
            return path
    return None


# Open a website or web app, optionally in a specific browser.
def OpenBrowser(Target, Browser=None):
    name = _Target(Target)
    key = name.lower()

    if key in WEBSITES:
        url = WEBSITES[key]
    elif re.match(r"^https?://", name, re.I):
        url = name
    elif _LooksLikeUrl(name):
        url = "https://" + name
    else:
        # Unknown name: search for it instead of guessing a domain.
        url = SEARCH_URLS["google"].format(quote_plus(name))

    # "open X in chrome" launches that browser directly when it is installed.
    if Browser:
        command = BROWSER_ALIASES.get(Browser.lower(), Browser.lower())
        executable = _FindExecutable(command)
        if executable:
            try:
                subprocess.Popen([executable, url])
                return f"Opening {name} in {Browser.title()}."
            except Exception:
                pass

    if not webbrowser.open(url, new=2):
        return f"I couldn't open {name} in your browser."
    return f"Opening {name} in your browser."


# Open a desktop application on the PC.
def OpenDesktop(Target, Quiet=False):
    name = _AppName(Target)
    if not name:
        return None if Quiet else "Which app should I open?"

    # Fast path: known executables and Windows shell URIs.
    command = DESKTOP_ALIASES.get(name.lower(), name)
    try:
        if command.endswith(":"):
            os.startfile(command)
            return f"Opening {name}."

        executable = _FindExecutable(command)
        if executable:
            subprocess.Popen([executable])
            return f"Opening {name}."

        if os.path.exists(command):
            os.startfile(command)
            return f"Opening {name}."
    except Exception:
        pass

    # Exact Start Menu match next; this also handles Store/UWP apps.
    if _TryAppOpener(name, Closest=False):
        return f"Opening {name}."

    # Explicit "open X" commands may use a fuzzy Start Menu match. Generic chat
    # falls through to the model instead of opening the wrong app.
    if not Quiet and _TryAppOpener(name, Closest=True):
        return f"Opening {name}."

    if Quiet:
        return None
    return f"I couldn't find an app called '{name}' on this PC."


# Open a search results page for the given site.
def SearchWeb(Query, Site="google"):
    query = _Target(Query)
    site = _Target(Site).lower() or "google"
    template = SEARCH_URLS.get(site, SEARCH_URLS["google"])
    encoded = quote(query) if site == "spotify" else quote_plus(query)
    if not webbrowser.open(template.format(encoded), new=2):
        return f"I couldn't open {site.title()} in your browser."
    label = "YouTube" if site == "youtube" else site.title()
    return f"Searching {label} for '{query}'."


# Send a WhatsApp message through WhatsApp Web.
def SendWhatsApp(Contact, Message):
    phone, display = ResolveContact(Contact)
    if not phone:
        return (
            f"I don't have a phone number for '{_Target(Contact)}'. "
            "Add it to Data/Contacts.json, or say the number with the country "
            "code (for example +91 98765 43210)."
        )

    message = _Text(Message)
    if not message:
        return f"What should I say to {display}?"

    try:
        pywhatkit = _PyWhatkit()
        # Opens WhatsApp Web, focuses the chat, types the message and presses Enter.
        pywhatkit.sendwhatmsg_instantly(
            phone,
            message,
            wait_time=12,
            tab_close=True,
            close_time=3,
        )
    except Exception as e:
        return f"I couldn't send the WhatsApp message: {e}"

    return f"Sent your WhatsApp message to {display}."


# Type text into whichever window is currently focused.
def TypeText(Text, PressEnter=False):
    text = _Text(Text)
    if not text:
        return "What should I type?"

    keyboard = _Keyboard()
    try:
        if text.isascii():
            keyboard.write(text, delay=0.01)
        else:
            # Clipboard paste handles Hindi/Urdu and other non-ASCII text.
            try:
                import pyperclip
                previous = None
                try:
                    previous = pyperclip.paste()
                except Exception:
                    pass
                pyperclip.copy(text)
                keyboard.press_and_release("ctrl+v")
                time.sleep(0.3)
                # Put the user's own clipboard text back.
                if previous is not None:
                    pyperclip.copy(previous)
            except Exception:
                keyboard.write(text, delay=0.01)

        if PressEnter:
            time.sleep(0.2)
            keyboard.press_and_release("enter")
    except Exception as e:
        return f"I couldn't type that: {e}"

    return "Typed it and pressed Enter." if PressEnter else "Typed it."


# Match "send message to X saying Y" style WhatsApp commands.
def _MatchWhatsApp(Text):
    patterns = [
        r"^(?:send|write)\s+(?:a\s+)?(?:whatsapp\s+)?message\s+to\s+(?P<contact>.+?)\s+(?:on\s+whatsapp\s+)?(?:saying|that|with\s+(?:the\s+)?text)\s+(?P<message>.+)$",
        r"^(?:send|write)\s+(?:a\s+)?whatsapp\s+message\s+to\s+(?P<contact>.+?)\s+(?:saying|that)\s+(?P<message>.+)$",
        r"^(?:send|write)\s+(?:a\s+)?whatsapp\s+to\s+(?P<contact>.+?)\s+(?:saying|that)\s+(?P<message>.+)$",
        r"^(?:send|write)\s+(?P<message>.+?)\s+to\s+(?P<contact>.+?)\s+(?:on\s+)?whatsapp$",
        r"^(?:message|text)\s+(?P<contact>.+?)\s+(?:on\s+whatsapp\s+)?(?:saying|that)\s+(?P<message>.+)$",
        r"^whatsapp\s+(?P<contact>.+?)\s+(?:saying|that)\s+(?P<message>.+)$",
    ]

    for pattern in patterns:
        match = re.match(pattern, Text, re.I)
        if match:
            return match
    return None


# Parse a query and run it locally. Return None for normal chat.
def HandleCommand(Query):
    text = _Text(Query)
    if not text:
        return None

    # WhatsApp first, so "write a message to X" is not treated as typing.
    match = _MatchWhatsApp(text)
    if match:
        return SendWhatsApp(match.group("contact"), match.group("message"))

    match = re.match(r"^(?:send|write)\s+(?:a\s+)?(?:whatsapp\s+)?message\s+to\s+(?P<contact>.+)$", text, re.I)
    if match:
        return f"What should I say to {_Target(match.group('contact'))}?"

    # Type / write text. "press enter" is optional.
    match = re.match(r"^(?:type(?:\s+out)?|write)\s+(?P<body>.+)$", text, re.I)
    if match:
        body = match.group("body").strip()
        press_enter = False
        enter = re.search(r"\s+(?:and|then)\s+(?:press|hit)\s+enter$", body, re.I)
        if enter:
            body = body[:enter.start()].strip()
            press_enter = True
        return TypeText(body, press_enter)

    # Search on a specific site, or on Google by default.
    match = re.match(
        r"^(?:search(?:\s+for)?|google|look\s+up)\s+(?P<query>.+?)"
        r"(?:\s+on\s+(?P<site>google|youtube|spotify|amazon|github|wikipedia))?$",
        text,
        re.I,
    )
    if match:
        return SearchWeb(match.group("query"), match.group("site") or "google")

    # Play something: open its YouTube results.
    match = re.match(r"^(?:play|youtube)\s+(?P<query>.+?)(?:\s+on\s+youtube)?$", text, re.I)
    if match:
        return SearchWeb(match.group("query"), "youtube")

    # Explicit browser commands.
    match = re.match(
        r"^(?:open|launch|visit|go\s+to|goto)\s+(?P<target>.+?)\s+"
        r"(?:in|on)\s+(?:the\s+)?"
        r"(?P<browser>browser|chrome|google\s+chrome|edge|microsoft\s+edge|firefox|brave|opera|internet)$",
        text,
        re.I,
    )
    if match:
        browser = re.sub(r"\s+", " ", match.group("browser")).strip()
        if browser.lower() in ("browser", "internet"):
            browser = None
        return OpenBrowser(match.group("target"), browser)

    match = re.match(r"^(?:open|launch|visit|go\s+to|goto)\s+(?P<target>.+?)\s+(?:web|website|site)$", text, re.I)
    if match:
        return OpenBrowser(match.group("target"))

    # Explicit desktop commands.
    match = re.match(
        r"^(?:open|launch|start|run)\s+(?P<target>.+?)\s+"
        r"(?:on|in)\s+(?:my\s+)?(?:pc|computer|laptop|desktop)$",
        text,
        re.I,
    )
    if match:
        return OpenDesktop(match.group("target"))

    # Generic "open X": prefer known sites, then known/short app names.
    match = re.match(r"^(?:open|launch|start|run)\s+(?P<target>.+)$", text, re.I)
    if match:
        target = _AppName(match.group("target"))
        key = target.lower()

        if key in WEBSITES or _LooksLikeUrl(key):
            return OpenBrowser(target)

        if key in ("browser", "web browser", "internet"):
            if webbrowser.open("https://www.google.com", new=2):
                return "Opening your browser."
            return "I couldn't open your browser."

        if key in DESKTOP_ALIASES:
            return OpenDesktop(target)

        # Try an exact Start Menu match for any name. Only single words may use
        # a fuzzy match, so "open source meaning" goes to the model instead of
        # opening a random app.
        exact = OpenDesktop(target, Quiet=True)
        if exact is not None:
            return exact
        if len(key.split()) == 1:
            return OpenDesktop(target)

    return None


# Manual test: python Automation.py
if __name__ == "__main__":
    while True:
        Query = input("Command: ")
        Result = HandleCommand(Query)
        print(Result if Result is not None else "(not an automation command)")
