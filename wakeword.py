"""Always-on "Hello JARVIS" listener for the Windows desktop build.

The browser's Speech Recognition API cannot reach a speech service from inside
the packaged window (it dies with `error:network`), so wake word detection runs
natively instead: a hidden PowerShell process driving Windows' *offline* desktop
recognizer (System.Speech).  It answers out loud, raises the JARVIS window (or
starts it), and drops the dictated command into `~/.jarvis/wake_command.json`
for the UI to pick up and run - no internet, and no API cost for the wake word.

Public surface used by app.py:
    is_supported(), status(), is_on(), enable(), disable(), pop_pending_command(),
    prefers_on(), set_prefers_on(), startup_installed(), install_startup(),
    remove_startup()
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from followups import data_dir

SCRIPT_NAME = "wake_listener.ps1"
STATUS_FILE = "wake_status.json"
COMMAND_FILE = "wake_command.json"
CONFIG_FILE = "wake_config.json"
STARTUP_NAME = "JARVIS.lnk"

# The listener rewrites its status every ~10s; older than this means it is gone.
STALE_SECONDS = 30

PS_ARGS = [
    "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
    "-WindowStyle", "Hidden",
]


def _base_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and os.path.exists(os.path.join(meipass, SCRIPT_NAME)):
        return Path(meipass)
    return Path(os.path.dirname(os.path.abspath(__file__)))


def script_path() -> Path:
    return _base_dir() / SCRIPT_NAME


def _status_path() -> Path:
    return data_dir() / STATUS_FILE


def _command_path() -> Path:
    return data_dir() / COMMAND_FILE


def _config_path() -> Path:
    return data_dir() / CONFIG_FILE


def _read_json(path: Path) -> dict:
    try:
        # PowerShell 5.1 writes UTF-8 with a BOM.
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, path)


def config() -> dict:
    """What the user asked for, and where this copy of JARVIS lives."""
    return _read_json(_config_path())


def _save_config(**updates) -> dict:
    merged = config()
    merged.update(updates)
    _write_json(_config_path(), merged)
    return merged


def is_supported() -> bool:
    """Windows only, and only if we can find the listener script."""
    return sys.platform == "win32" and script_path().exists()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _age_of(stamp: str):
    if not stamp:
        return None
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if moment.tzinfo is not None:      # PowerShell's 'o' format carries the offset
        moment = moment.astimezone().replace(tzinfo=None)
    return (datetime.now() - moment).total_seconds()


def _alive(info: dict) -> bool:
    age = _age_of(info.get("updated", ""))
    return bool(info) and age is not None and age < STALE_SECONDS and _pid_alive(
        int(info.get("pid") or 0)
    )


def status() -> dict:
    """Where the listener stands: {state, alive, mode, engine, error, age, pid}."""
    info = _read_json(_status_path())
    alive = _alive(info)
    return {
        "state": info.get("state", "off") if alive else "off",
        "alive": alive,
        "mode": info.get("mode", ""),
        "engine": info.get("engine", ""),
        "error": info.get("error", ""),
        "age": _age_of(info.get("updated", "")),
        "pid": int(info.get("pid") or 0),
    }


def is_on() -> bool:
    return status()["alive"]


def prefers_on() -> bool:
    """Did the user ask for hands-free? JARVIS honours this on every start."""
    return bool(config().get("enabled"))


def set_prefers_on(on: bool) -> None:
    _save_config(enabled=bool(on))


# --------------------------------------------------------------------------- #
# Starting / stopping the listener process
# --------------------------------------------------------------------------- #

def _launch_target() -> tuple:
    """What gets started when you wake JARVIS while it is closed."""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = str(pythonw) if pythonw.exists() else sys.executable
    desktop = _base_dir() / "desktop.py"
    return (interpreter, f'"{desktop}"') if desktop.exists() else ("", "")


def _remember_self() -> tuple:
    target, args = _launch_target()
    if target:
        _save_config(launch_target=target, launch_args=args)
    return target, args


def _ps_args() -> list:
    """Command for the listener - no path arguments; it reads wake_config.json."""
    return ["powershell.exe", *PS_ARGS, "-File", str(script_path())]


def _spawn_hidden(cmd: list) -> subprocess.Popen:
    flags = 0
    if sys.platform == "win32":
        # NB: DETACHED_PROCESS makes powershell.exe exit straight away; a
        # windowless child is what actually survives here.
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_NO_WINDOW = 0x08000000
        flags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
    return subprocess.Popen(
        cmd, creationflags=flags, close_fds=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def enable() -> tuple:
    """Start the listener now. Returns (ok, message)."""
    if not is_supported():
        return False, "The always-on listener needs Windows."
    _remember_self()
    if is_on():
        return True, "Already listening."
    proc = _spawn_hidden(_ps_args())
    deadline = time.time() + 14
    while time.time() < deadline:
        raw = _read_json(_status_path())
        if raw.get("state") == "unavailable":
            return False, raw.get("error") or "No offline speech recognizer found."
        if _alive(raw):
            return True, f"Listening on the Windows offline engine ({raw.get('mode','')})."
        if proc.poll() is not None and raw.get("updated"):
            break
        time.sleep(0.3)
    raw = _read_json(_status_path())
    if raw.get("state") == "unavailable":
        return False, raw.get("error") or "No offline speech recognizer found."
    return False, "The listener stopped before it could start. See ~/.jarvis/wake_listener.log"


def disable() -> tuple:
    """Stop the listener process."""
    pid = status()["pid"]
    if not pid:
        return True, "Not running."
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F", "/T"],
            capture_output=True, timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"Could not stop the listener: {exc}"
    for _ in range(12):
        time.sleep(0.25)
        if not is_on():
            return True, "Stopped."
    return False, "The listener is still running."


def pop_pending_command() -> str:
    """Return the newest dictated command, or ''. Consumed on read."""
    path = _command_path()
    text = str(_read_json(path).get("text", "")).strip()
    if not text:
        return ""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return ""
    return text


# --------------------------------------------------------------------------- #
# Sign-in entry: a plain JARVIS shortcut in the user's Startup folder
# --------------------------------------------------------------------------- #

def startup_path() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return (
        Path(appdata)
        / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        / STARTUP_NAME
    )


def startup_installed() -> bool:
    return startup_path().exists()


def _ps_str(value) -> str:
    """A PowerShell single-quoted string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def install_startup() -> tuple:
    """Put a JARVIS shortcut in the per-user Startup folder. No admin needed.

    A shortcut to the app itself, not a hidden script - security software reads
    it as what it is, and the user can undo it from Settings > Startup.
    """
    target, args = _remember_self()
    if not target:
        return False, "Could not work out how to start JARVIS at sign-in."
    path = startup_path()
    script = (
        f"$sc = (New-Object -ComObject WScript.Shell).CreateShortcut({_ps_str(path)}); "
        f"$sc.TargetPath = {_ps_str(target)}; "
        f"$sc.Arguments = {_ps_str(args)}; "
        f"$sc.WorkingDirectory = {_ps_str(_base_dir())}; "
        "$sc.Description = 'Start JARVIS at sign-in'; "
        "$sc.Save()"
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        res = subprocess.run(
            ["powershell.exe", *PS_ARGS, "-Command", script],
            capture_output=True, text=True, timeout=90,
        )
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    if res.returncode != 0 or not path.exists():
        return False, (res.stderr or res.stdout or "Shortcut creation failed.").strip()
    return True, str(path)


def remove_startup() -> tuple:
    path = startup_path()
    try:
        if path.exists():
            path.unlink()
        return True, "Removed."
    except OSError as exc:
        return False, str(exc)
