"""PC system-control tools for J.A.R.V.I.S. — local desktop builds only.

Security model:
- No arbitrary command execution. Launchable apps come from a fixed name map.
- Every file operation is confined to the user's own folders (see allowed_roots).
- Processes start via subprocess with an argument list (never shell=True).
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import urllib.parse
import webbrowser
from pathlib import Path

from langchain_core.tools import tool

IS_WINDOWS = sys.platform == "win32"

# --------------------------------------------------------------------------- #
# Enablement
# --------------------------------------------------------------------------- #


def system_control_enabled() -> bool:
    """True when JARVIS is running as a local desktop app and may touch the PC."""
    flag = os.environ.get("JARVIS_SYSTEM_CONTROL", "")
    if flag == "0":
        return False
    if flag == "1":
        return True
    return bool(getattr(sys, "frozen", False))


# --------------------------------------------------------------------------- #
# Path sandbox
# --------------------------------------------------------------------------- #

_DIR_NAMES = ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos")

# Never let the agent reach into these, even though they sit under the home dir.
DENIED_PARTS = {".ssh", ".aws", ".gnupg", ".config", "appdata", "program files",
                "windows", "winnt", "system32"}


def allowed_roots() -> list:
    home = Path.home()
    roots = [home]
    for name in _DIR_NAMES:
        p = home / name
        if p.exists():
            roots.append(p)
    here = Path(__file__).resolve().parent
    roots.append(here)
    return roots


def _norm(p) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def _within(root, target) -> bool:
    r, t = _norm(root), _norm(target)
    return t == r or t.startswith(r + os.sep)


def _resolve(path_str: str, base_is_dir: bool = True) -> Path:
    """Expand and validate a user-supplied path against the sandbox."""
    raw = (path_str or "").strip().strip('"').strip("'")
    if not raw:
        return Path.home() if base_is_dir else Path.home()
    raw = os.path.expandvars(os.path.expanduser(raw))
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = Path.home() / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate

    parts = {_norm(p).lower() for p in resolved.parts}
    if parts & DENIED_PARTS:
        raise ValueError("that location is protected and cannot be accessed")
    if not any(_within(r, resolved) for r in allowed_roots()):
        raise ValueError(
            "outside the allowed folders — JARVIS can only touch "
            + ", ".join(str(r) for r in allowed_roots() if r != Path.home())
            + " or your home folder"
        )
    return resolved


# --------------------------------------------------------------------------- #
# Launching
# --------------------------------------------------------------------------- #

APPS = {
    "notepad": ("exe", "notepad.exe"),
    "calculator": ("exe", "calc.exe"),
    "paint": ("exe", "mspaint.exe"),
    "snipping tool": ("exe", "snippingtool.exe"),
    "file explorer": ("exe", "explorer.exe"),
    "command prompt": ("exe", "cmd.exe"),
    "powershell": ("exe", "powershell.exe"),
    "task manager": ("exe", "taskmgr.exe"),
    "control panel": ("uri", "ms-settings:"),
    "microsoft edge": ("exe", "msedge.exe"),
    "google chrome": ("exe", "chrome.exe"),
    "firefox": ("exe", "firefox.exe"),
    "whatsapp": ("uri", "whatsapp:"),
    "microsoft word": ("exe", "winword.exe"),
    "microsoft excel": ("exe", "excel.exe"),
    "microsoft powerpoint": ("exe", "powerpnt.exe"),
    "microsoft outlook": ("exe", "outlook.exe"),
    "visual studio code": ("exe", "code.exe"),
    "spotify": ("uri", "spotify:"),
    "vlc media player": ("exe", "vlc.exe"),
}

ALIASES = {
    "calc": "calculator", "notes": "notepad", "text editor": "notepad",
    "terminal": "command prompt", "cmd": "command prompt", "console": "command prompt",
    "files": "file explorer", "explorer": "file explorer", "folder": "file explorer",
    "my computer": "file explorer", "this pc": "file explorer",
    "snip": "snipping tool", "screenshot tool": "snipping tool",
    "chrome": "google chrome", "browser": "microsoft edge",
    "edge": "microsoft edge", "mozilla": "firefox",
    "word": "microsoft word", "excel": "microsoft excel",
    "powerpoint": "microsoft powerpoint", "ppt": "microsoft powerpoint",
    "outlook": "microsoft outlook", "email app": "microsoft outlook",
    "vs code": "visual studio code", "code": "visual studio code", "vscode": "visual studio code",
    "settings": "control panel", "windows settings": "control panel",
    "music": "spotify", "video player": "vlc media player", "vlc": "vlc media player",
}


def _uri_handler_exists(scheme: str) -> bool:
    """True when Windows has a registered handler for a custom URI scheme."""
    if not IS_WINDOWS:
        return True
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f"{scheme}\\shell\\open\\command"):
            return True
    except OSError:
        return False


def _open_uri(target: str) -> None:
    if IS_WINDOWS:
        os.startfile(target)  # noqa: S606 - shell handler for a fixed URI scheme
    else:
        subprocess.Popen(["xdg-open", target] if sys.platform.startswith("linux")
                         else ["open", target], shell=False)


URI_WEB_FALLBACK = {
    "whatsapp": "https://web.whatsapp.com",
    "spotify": "https://open.spotify.com",
    "zoommtg": "https://zoom.us",
}


def _launch_app(name: str) -> str:
    key = (name or "").strip().lower()
    key = ALIASES.get(key, key)
    entry = APPS.get(key)
    if entry is None:
        return (
            f"I don't know how to open '{name}'. Installed apps I can launch: "
            + ", ".join(sorted(APPS))
            + ". Ask me to open a website instead if the app is not in that list."
        )
    kind, target = entry
    try:
        if kind == "uri":
            scheme = target.split(":", 1)[0]
            if not _uri_handler_exists(scheme):
                web = URI_WEB_FALLBACK.get(scheme)
                if web and webbrowser.open(web, new=2):
                    return (f"{key} is not installed on this PC, so I opened "
                            f"{web} in your browser instead.")
                return (f"{key} is not installed on this PC, so I cannot open it. "
                        "Ask me to open its website instead.")
            _open_uri(target)
            return f"Opening {key} …"
        exe = shutil.which(target)
        if exe:
            subprocess.Popen([exe], shell=False)
        else:
            _open_uri(target)  # falls back to the Windows App Paths registry
        return f"Opening {key} …"
    except OSError as exc:
        return f"{key} does not appear to be installed on this PC ({exc.__class__.__name__})."


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #

@tool
def open_website(url: str) -> str:
    """Open a website in the user's default browser. Accepts 'gmail.com',
    'youtube.com', or a full URL; a missing https:// prefix is added for you."""
    raw = (url or "").strip()
    if not raw:
        return "No website was given."
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "That does not look like a valid website address."
    ok = webbrowser.open(raw, new=2)
    return (f"Opening {parsed.netloc} in your browser."
            if ok else f"Your browser refused to open {parsed.netloc}.")


@tool
def search_in_browser(query: str, engine: str = "google") -> str:
    """Type a search into the browser and show the results page on screen (this
    opens the actual site, unlike web_search which only reads results).
    engine: google, images, youtube, maps, news."""
    q = (query or "").strip()
    if not q:
        return "Nothing to search for."
    engines = {
        "google": "https://www.google.com/search?q=",
        "images": "https://www.google.com/search?tbm=isch&q=",
        "youtube": "https://www.youtube.com/results?search_query=",
        "maps": "https://www.google.com/maps/search/",
        "news": "https://news.google.com/search?q=",
    }
    base = engines.get((engine or "google").strip().lower())
    if base is None:
        return f"Unknown search engine '{engine}'. Choose from: " + ", ".join(engines)
    url = base + urllib.parse.quote_plus(q)
    return f"Searching {engine} for '{q}' — opening your browser." if webbrowser.open(url, new=2) \
        else "Your browser refused to open the search page."


@tool
def open_application(name: str) -> str:
    """Launch a desktop application on this PC by name, e.g. 'notepad',
    'calculator', 'chrome', 'whatsapp', 'microsoft word', 'spotify'."""
    return _launch_app(name)


@tool
def send_whatsapp_message(number: str, message: str = "") -> str:
    """Open WhatsApp to a specific contact number, pre-filled with a message.
    Include the country code, e.g. '+919876543210'. The user still presses send."""
    digits = "".join(c for c in (number or "") if c.isdigit() or c == "+")
    if len(digits.lstrip("+")) < 6:
        return "That phone number looks too short — please confirm it with the country code."
    text = urllib.parse.quote(message or "")
    if IS_WINDOWS and _uri_handler_exists("whatsapp"):
        try:
            os.startfile(f"whatsapp://send?phone={digits}&text={text}")  # noqa: S606
            return f"Opening WhatsApp to {digits} with your message ready to send."
        except OSError:
            pass
    fallback = f"https://wa.me/{digits.lstrip('+')}?text={text}"
    webbrowser.open(fallback, new=2)
    return (
        f"WhatsApp Desktop is not installed here, so I opened wa.me for {digits} in "
        "your browser instead — the chat will open with the message pre-filled once "
        "you are logged into WhatsApp Web."
    )


@tool
def open_item(path: str) -> str:
    """Open a file or folder on this PC with its default application
    (a document in Word, a folder in Explorer, an image in the viewer, ...)."""
    try:
        target = _resolve(path)
    except ValueError as exc:
        return str(exc)
    if not target.exists():
        return f"I could not find {target}."
    try:
        _open_uri(str(target))
        return f"Opening {target.name} …"
    except OSError as exc:
        return f"Could not open {target}: {exc}"


@tool
def list_folder(path: str = "") -> str:
    """List the files and folders inside a directory. An empty path means your
    home folder. Only folders JARVIS is allowed to see are listed."""
    try:
        target = _resolve(path)
    except ValueError as exc:
        return str(exc)
    if not target.is_dir():
        return f"{target} is not a folder."
    try:
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError as exc:
        return f"Could not read {target}: {exc}"
    lines = []
    for e in entries[:60]:
        kind = "DIR " if e.is_dir() else "file"
        size = f"{e.stat().st_size // 1024} KB" if e.is_file() else ""
        lines.append(f"{kind}  {e.name}  {size}".rstrip())
    head = f"{len(entries)} item(s) in {target}:\n"
    body = "\n".join(lines)
    if len(entries) > 60:
        body += f"\n… and {len(entries) - 60} more."
    return head + body


@tool
def read_text_file(path: str) -> str:
    """Read the contents of a text file (txt, md, csv, json, log) so you can
    summarise, check or rewrite it."""
    try:
        target = _resolve(path)
    except ValueError as exc:
        return str(exc)
    if not target.is_file():
        return f"I could not find the file {target}."
    if target.suffix.lower() not in (".txt", ".md", ".csv", ".json", ".log",
                                     ".py", ".html", ".xml", ".yml", ".yaml", ".ini"):
        return f"{target.name} is not a plain-text file, so I will not read it."
    try:
        data = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Could not read {target.name}: {exc}"
    if len(data) > 20000:
        data = data[:20000] + "\n… (truncated)"
    return data or f"{target.name} is empty."


@tool
def create_text_file(path: str, content: str) -> str:
    """Create a NEW text file (notes, lists, drafts, reports) inside one of your
    folders. Refuses to overwrite anything that already exists."""
    try:
        target = _resolve(path)
    except ValueError as exc:
        return str(exc)
    if target.exists():
        return (f"{target} already exists — I will not overwrite it. Give me a new "
                "name, or ask me to append to it instead.")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content or "", encoding="utf-8")
    except OSError as exc:
        return f"Could not create {target.name}: {exc}"
    return f"Wrote {len(content or '')} characters to {target}."


@tool
def append_to_file(path: str, text: str) -> str:
    """Add a line of text to the end of an existing text file (or create it if
    it does not exist yet). Nothing already in the file is changed."""
    try:
        target = _resolve(path)
    except ValueError as exc:
        return str(exc)
    if target.exists() and not target.is_file():
        return f"{target} is a folder, not a file."
    try:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(("" if target.stat().st_size == 0 else "\n") + (text or ""))
    except OSError as exc:
        return f"Could not write to {target.name}: {exc}"
    return f"Appended to {target}."


@tool
def create_folder(path: str) -> str:
    """Create a new folder inside one of your own directories."""
    try:
        target = _resolve(path)
    except ValueError as exc:
        return str(exc)
    if target.exists():
        return f"{target} already exists."
    try:
        target.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        return f"Could not create {target}: {exc}"
    return f"Created folder {target}."


@tool
def system_status() -> str:
    """Report this PC's basics: OS, machine name, CPU count, free disk space and
    which user folders JARVIS can reach."""
    info = []
    try:
        info.append(f"OS: {platform.system()} {platform.release()} ({platform.machine()})")
    except Exception:  # noqa: BLE001
        pass
    info.append(f"User: {os.environ.get('USERNAME') or Path.home().name}")
    info.append(f"CPU cores: {os.cpu_count()}")
    try:
        usage = shutil.disk_usage(str(Path.home()))
        info.append(f"Disk free: {usage.free / 1024 ** 3:.1f} GB of {usage.total / 1024 ** 3:.0f} GB")
    except OSError:
        pass
    info.append("Reachable folders: " + ", ".join(str(r) for r in allowed_roots() if r != Path.home()))
    if not IS_WINDOWS:
        info.append("Note: app launching is tuned for Windows; some apps may not resolve.")
    return "\n".join(info)


PC_TOOLS = [
    open_website,
    search_in_browser,
    open_application,
    send_whatsapp_message,
    open_item,
    list_folder,
    read_text_file,
    create_text_file,
    append_to_file,
    create_folder,
    system_status,
]

PC_CONTROL_NOTES = (
    "\n\nPC CONTROL: you are running on the user's own Windows machine and you have "
    "real system tools — open_website, search_in_browser, open_application, "
    "send_whatsapp_message, open_item, list_folder, read_text_file, create_text_file, "
    "append_to_file, create_folder, system_status.\n"
    "When the user asks you to OPEN, LAUNCH, SHOW or WRITE something on their PC, "
    "actually call the tool instead of describing the steps. Examples: 'open whatsapp' "
    "-> open_application('whatsapp'); 'open my patients file' -> open_item; "
    "'make a note of this' -> create_text_file in Documents. "
    "Prefer web_search when they want an answer, search_in_browser when they want to "
    "see the page. Never invent a file path — if unsure, list_folder first. "
    "You cannot delete or overwrite files; if a task needs that, tell the user to do "
    "it themselves."
)


def get_pc_tools() -> list:
    return list(PC_TOOLS)
