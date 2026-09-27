"""Follow-up reminders for J.A.R.V.I.S. — persisted task list with a scheduler.

Reminders live in `~/.jarvis/followups.json` so they survive restarts and work for
any Windows user without admin rights.  A daemon thread watches for due items and
raises a native Windows popup; the UI picks them up via :func:`pop_due`.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import sys
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from langchain_core.tools import tool

TIME_FMT = "%Y-%m-%d %H:%M"
POLL_SECONDS = 15

_lock = threading.RLock()
_thread_started = False
_announced: list = []


def data_dir() -> Path:
    root = os.environ.get("JARVIS_HOME")
    return Path(root).expanduser() if root else Path.home() / ".jarvis"


def store_path() -> Path:
    return data_dir() / "followups.json"


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #

def _load() -> list:
    try:
        with open(store_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(items: list) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(items, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# When-parser
# --------------------------------------------------------------------------- #

_UNIT = {
    "s": "seconds", "sec": "seconds", "secs": "seconds", "second": "seconds",
    "m": "minutes", "min": "minutes", "mins": "minutes", "minute": "minutes",
    "h": "hours", "hr": "hours", "hrs": "hours", "hour": "hours",
    "d": "days", "day": "days", "days": "days",
    "w": "weeks", "week": "weeks", "weeks": "weeks",
}


def parse_when(text: str, now: datetime | None = None) -> datetime | None:
    """Turn a human time ('in 2 hours', 'tomorrow 9am', '+45m', '2026-09-28 14:00',
    '18:30') into a datetime.  Returns None when nothing sensible matches."""
    now = now or datetime.now()
    raw = (text or "").strip().lower()
    if not raw:
        return None

    # Absolute ISO-ish: 2026-09-28 14:00 / 28-09-2026 2pm style dates
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})[ t,]+(\d{1,2}):(\d{2})", raw)
    if m:
        y, mo, d, h, mi = (int(g) for g in m.groups())
        return _safe_datetime(y, mo, d, h, mi)

    # Relative: "in 2 hours", "+45m", "30 mins"
    m = re.search(r"(?:in\s+)?([+-]?\d+(?:\.\d+)?)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|m|h|d|w|s)\b", raw)
    if m:
        amount = float(m.group(1))
        unit_key = m.group(2)
        if unit_key not in _UNIT and unit_key.endswith("s"):
            unit_key = unit_key[:-1]
        unit = _UNIT.get(unit_key)
        if unit and amount:
            return now + timedelta(**{unit: -abs(amount) if m.group(1).startswith("-") else abs(amount)})

    # Named windows with no clock time.
    if raw in ("tomorrow", "day after"):
        return (now + timedelta(days=2 if raw == "day after" else 1)).replace(hour=9, minute=0, second=0)
    if raw == "tonight":
        return now.replace(hour=20, minute=0, second=0)
    if raw in ("next week", "in a week", "in one week"):
        return (now + timedelta(days=7)).replace(hour=9, minute=0, second=0)

    # Clock time, optionally with a day word
    clock = None
    m = re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\b", raw)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        ap = m.group(3)
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        if h <= 23 and mi <= 59:
            clock = (h, mi)
    else:
        m = re.search(r"\b(\d{1,2})\s*(am|pm)\b", raw)
        if m:
            h, ap = int(m.group(1)), m.group(2)
            if ap == "pm" and h < 12:
                h += 12
            if ap == "am" and h == 12:
                h = 0
            clock = (h, 0)
    if clock is None:
        # "call Ali at 6" / "by 5" — treat small hours as the afternoon/evening.
        m = re.search(r"\b(?:at|by|around|near|@)\s*(\d{1,2})\b", raw)
        if m:
            h = int(m.group(1))
            if 1 <= h <= 7:
                h += 12
            if h <= 23:
                clock = (h, 0)
    if clock is None:
        return None

    day = now.date()
    if "tomorrow" in raw or "day after" in raw:
        day = day + timedelta(days=2 if "day after" in raw else 1)
    elif "monday" in raw or "tuesday" in raw or "wednesday" in raw or "thursday" in raw \
            or "friday" in raw or "saturday" in raw or "sunday" in raw:
        names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        target = next(i for i, n in enumerate(names) if n in raw)
        ahead = (target - now.weekday()) % 7 or 7
        day = day + timedelta(days=ahead)

    when = datetime.combine(day, datetime.min.time()).replace(hour=clock[0], minute=clock[1])
    if when <= now and "tomorrow" not in raw and ahead_not_mentioned(raw):
        when += timedelta(days=1)
    return when


def ahead_not_mentioned(raw: str) -> bool:
    """A bare clock time that already passed rolls to tomorrow."""
    return not any(w in raw for w in ("tomorrow", "monday", "tuesday", "wednesday",
                                      "thursday", "friday", "saturday", "sunday"))


def _safe_datetime(y, mo, d, h, mi):
    try:
        return datetime(y, mo, d, h, mi)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Native popup
# --------------------------------------------------------------------------- #


def _popup(title: str, message: str) -> None:
    def show():
        if sys.platform == "win32":
            try:
                # 0x40 icon | 0x10000 foreground | 0x40000 topmost
                ctypes.windll.user32.MessageBoxW(None, message, title, 0x40 | 0x10000 | 0x40000)
            except Exception:  # noqa: BLE001
                pass
    threading.Thread(target=show, daemon=True).start()


# --------------------------------------------------------------------------- #
# Scheduler
# --------------------------------------------------------------------------- #


def _tick() -> None:
    now = datetime.now()
    with _lock:
        items = _load()
        changed = False
        for it in items:
            if not it.get("fired") and not it.get("done"):
                try:
                    due = datetime.strptime(it["due"], TIME_FMT)
                except (KeyError, ValueError):
                    continue
                if due <= now:
                    it["fired"] = True
                    _announced.append(dict(it))
                    changed = True
                    _popup("J.A.R.V.I.S. — reminder", f"{it['text']}\n\n(scheduled {it['due']})")
        if changed:
            _save(items)


def start_scheduler() -> None:
    """Start the background watcher once per process."""
    global _thread_started
    with _lock:
        if _thread_started:
            return
        _thread_started = True
    threading.Thread(target=_loop, name="jarvis-reminders", daemon=True).start()


def _loop() -> None:
    while True:
        try:
            _tick()
        except Exception:  # noqa: BLE001 - a bad entry must never kill the watcher
            pass
        threading.Event().wait(POLL_SECONDS)


def pop_due() -> list:
    """Reminder items that fired since the UI last looked (clears the buffer)."""
    global _announced
    with _lock:
        due, _announced = _announced, []
    return due


def list_upcoming(include_done: bool = False) -> list:
    """Raw reminder dicts sorted by due time, for the interface."""
    with _lock:
        items = sorted(_load(), key=lambda i: i.get("due", ""))
    return [i for i in items if include_done or not i.get("done")]


def upcoming_text() -> str:
    """Human-readable digest used by the sidebar and the agent."""
    rows = list_upcoming()
    if not rows:
        return ""
    now = datetime.now()
    lines = []
    for i in rows:
        try:
            overdue = datetime.strptime(i["due"], TIME_FMT) < now and not i.get("done")
        except ValueError:
            overdue = False
        mark = "!! " if overdue else ""
        lines.append(f"{mark}{i['due']}  {i['text']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Agent tools
# --------------------------------------------------------------------------- #


@tool
def add_followup(text: str, when: str) -> str:
    """Schedule a follow-up reminder. `text` is what to remember, `when` is a
    time such as 'in 2 hours', 'tomorrow 9am', '+45m', 'Friday 14:00' or
    '2026-09-28 18:30'. Call current_datetime first if the user gave a relative
    time and you need an anchor."""
    due = parse_when(when)
    if due is None:
        return (f"I could not understand the time '{when}'. Try 'in 2 hours', "
                "'tomorrow 9am', '+45m' or '2026-09-28 18:30'.")
    item = {
        "id": uuid.uuid4().hex[:6],
        "text": (text or "").strip()[:300],
        "due": due.strftime(TIME_FMT),
        "created": datetime.now().strftime(TIME_FMT),
        "done": False,
        "fired": False,
    }
    if not item["text"]:
        return "Tell me what to remind you about, Sir."
    with _lock:
        items = _load()
        items.append(item)
        _save(items)
    start_scheduler()
    return f"Noted — I will remind you about '{item['text']}' at {item['due']}."


@tool
def list_followups(include_done: bool = False) -> str:
    """Show scheduled follow-ups with their ids, so the user can see or cancel them."""
    with _lock:
        items = sorted(_load(), key=lambda i: i.get("due", ""))
    rows = [i for i in items if include_done or not i.get("done")]
    if not rows:
        return "There are no follow-ups on the list right now."
    now = datetime.now()
    lines = []
    for i in rows:
        try:
            late = "  << OVERDUE" if datetime.strptime(i["due"], TIME_FMT) < now and not i.get("done") else ""
        except ValueError:
            late = ""
        state = "done" if i.get("done") else ("fired" if i.get("fired") else "pending")
        lines.append(f"[{i['id']}] {i['due']} ({state}) {i['text']}{late}")
    return f"{len(rows)} follow-up(s):\n" + "\n".join(lines)


@tool
def complete_followup(item_id: str) -> str:
    """Mark a follow-up as finished. `item_id` is the short id from list_followups."""
    target = (item_id or "").strip().lstrip("#")
    with _lock:
        items = _load()
        hit = next((i for i in items if i.get("id") == target), None)
        if hit is None:
            return f"I can't find a follow-up with id '{target}'. Use list_followups to see the ids."
        hit["done"] = True
        _save(items)
    return f"Closed out '{hit['text']}'."


@tool
def remove_followup(item_id: str) -> str:
    """Delete a scheduled follow-up permanently. `item_id` comes from list_followups."""
    target = (item_id or "").strip().lstrip("#")
    with _lock:
        items = _load()
        keep = [i for i in items if i.get("id") != target]
        if len(keep) == len(items):
            return f"I can't find a follow-up with id '{target}'."
        _save(keep)
    return f"Removed follow-up '{target}'."


REMINDER_TOOLS = [add_followup, list_followups, complete_followup, remove_followup]

REMINDER_NOTES = (
    "\n\nFOLLOW-UPS: you can schedule real reminders that pop up on the user's "
    "screen — add_followup, list_followups, complete_followup, remove_followup. "
    "When the user says 'remind me to call Ali at 6' or 'follow up with the lab "
    "tomorrow morning', call add_followup. Work out an absolute time first with "
    "current_datetime, then pass `when` as something like '18:00', 'tomorrow 9am' "
    "or 'in 2 hours'. Confirm the resulting time back to the user. Never claim a "
    "reminder exists without calling the tool."
)
