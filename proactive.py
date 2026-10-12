"""Proactive J.A.R.V.I.S. - the daily briefing and new-mail alerts.

Three features that let JARVIS speak first:
- a once-a-day briefing (date, follow-ups, mailbox) delivered after a set hour;
- a background watcher that announces new INBOX mail (read-only IMAP);
- a background watcher that announces new WhatsApp messages (read-only peek
  at the linked WhatsApp Web sidebar - nothing is ever marked as read).

State lives in ``~/.jarvis/proactive.json`` so all survive restarts. The UI
polls :func:`pop_proactive` on every rerun, exactly like the reminder engine,
so whatever fires shows up in the chat and is spoken aloud.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

import email_control
import followups
import whatsapp_cloud
import whatsapp_control

DEFAULT_PREFS = {
    "briefing_on": True,
    "briefing_hour": 8,
    "briefing_last": "",      # YYYY-MM-DD of the last delivered briefing
    "mail_watch_on": False,
    "mail_user": "",          # mailbox the UID watermark belongs to
    "mail_last_uid": 0,
    "wa_watch_on": False,
    "wa_marked": False,       # watermark established by a first completed check
    "wa_last": {},            # {chat title: unread count} watermark
}

MAIL_POLL_SECONDS = 120

_lock = threading.RLock()
_pending: list = []
_watch_thread: threading.Thread | None = None
_stop = threading.Event()
_watch_info = {"last_check": "", "last_error": ""}


# --------------------------------------------------------------------------- #
# Preferences (persisted)
# --------------------------------------------------------------------------- #


def _prefs_path() -> Path:
    return followups.data_dir() / "proactive.json"


def load_prefs() -> dict:
    try:
        with open(_prefs_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    merged = dict(DEFAULT_PREFS)
    if isinstance(data, dict):
        merged.update(data)
    return merged


def _save_prefs(prefs: dict) -> None:
    path = _prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(prefs, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def save_prefs(changes: dict) -> None:
    """Merge `changes` into the stored preferences (skips no-op writes)."""
    with _lock:
        prefs = load_prefs()
        if all(prefs.get(k) == v for k, v in changes.items()):
            return
        prefs.update(changes)
        _save_prefs(prefs)


# --------------------------------------------------------------------------- #
# Native popup (same style as the reminder popups)
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
# Morning briefing
# --------------------------------------------------------------------------- #


def _short_who(from_header: str) -> str:
    name = (from_header or "").split("<")[0].strip().strip('"')
    return name or (from_header or "someone").strip() or "someone"


def compose_briefing() -> tuple:
    """Build (chat_text, spoken_text) for the daily briefing."""
    now = datetime.now()
    greet = ("Good morning" if now.hour < 12
             else "Good afternoon" if now.hour < 17 else "Good evening")
    day = now.strftime("%A, %d %B %Y")
    chat = [f"{greet}, Sir. Today is {day} — the time is {now.strftime('%H:%M')}."]
    spoken = [f"{greet}, Sir. Today is {day}."]

    rows = followups.list_upcoming()
    if rows:
        chat.append(f"\n**Follow-ups:** {len(rows)} open.")
        for r in rows[:4]:
            chat.append(f"- {r.get('due', '?')} — {r.get('text', '')}")
        if len(rows) > 4:
            chat.append(f"- …and {len(rows) - 4} more.")
        first = "; ".join(str(r.get("text", "")) for r in rows[:2])
        spoken.append(f"You have {len(rows)} open follow-up(s): {first}.")
    else:
        chat.append("\n**Follow-ups:** none on the list.")
        spoken.append("No follow-ups on the list.")

    cfg = email_control.from_env()
    if cfg.ready:
        try:
            n = email_control.unread_count(cfg)
            if n:
                top = email_control.fetch_messages(cfg, count=3, unread_only=True)
                subjects = "; ".join(m["subject"][:70] for m in top)
                chat.append(f"**Mailbox:** {n} unread — newest: {subjects}.")
                spoken.append(f"Mailbox: {n} unread. Newest: "
                              + ". ".join(m['subject'][:60] for m in top[:2]) + ".")
            else:
                chat.append("**Mailbox:** no unread mail.")
                spoken.append("Mailbox: no unread mail.")
        except Exception as exc:  # noqa: BLE001
            chat.append(f"**Mailbox:** could not check ({str(exc)[:120]}).")
            spoken.append("Mailbox: I could not check it just now.")

    try:
        wa_unread = [r for r in _wa_rows() if _wa_count(r) > 0]
        if wa_unread:
            names = "; ".join(
                f"{r.get('title', '?')} ({_wa_count(r)})" for r in wa_unread[:4])
            chat.append(f"**WhatsApp:** {len(wa_unread)} chat(s) with unread — {names}.")
            spoken.append(f"WhatsApp: {len(wa_unread)} chats with unread messages: {names}.")
        else:
            chat.append("**WhatsApp:** no unread messages.")
            spoken.append("WhatsApp: no unread messages.")
    except Exception:  # noqa: BLE001 - not linked, or WhatsApp not answering
        pass

    chat.append("All systems ready, Sir.")
    return "\n".join(chat), " ".join(spoken)


def _push_briefing(chat: str) -> None:
    """The same briefing on the phone, when that is switched on."""
    try:
        if not load_prefs().get("notify_briefing"):
            return
        text = re.sub(r"[*_`#>]+", "", chat).strip()
        threading.Thread(target=whatsapp_cloud.notify, args=(text,),
                         name="jarvis-wa-briefing", daemon=True).start()
    except Exception:  # noqa: BLE001
        pass


def _due_briefing() -> dict | None:
    """One briefing per day, after the set hour. None when not due."""
    with _lock:
        prefs = load_prefs()
        if not prefs.get("briefing_on"):
            return None
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        if prefs.get("briefing_last") == today:
            return None
        try:
            hour = int(prefs.get("briefing_hour", 8))
        except (TypeError, ValueError):
            hour = 8
        if now.hour < hour:
            return None
        prefs["briefing_last"] = today
        _save_prefs(prefs)
    chat, spoken = compose_briefing()
    _popup("J.A.R.V.I.S. — briefing", spoken[:900])
    _push_briefing(chat)
    return {"kind": "briefing", "text": chat, "speak": spoken}


# --------------------------------------------------------------------------- #
# New-mail watcher
# --------------------------------------------------------------------------- #


def _compose_mail(messages: list) -> dict:
    if len(messages) == 1:
        subject = messages[0]["subject"][:80]
        who = _short_who(messages[0]["from"])
        return {
            "kind": "mail",
            "text": f"📬 **New mail** from {who} — {subject}",
            "speak": f"New mail from {who}: {subject}.",
        }
    head = f"{len(messages)} new emails"
    detail = "; ".join(
        f"{_short_who(m['from'])}: {m['subject'][:60]}" for m in messages[:3]
    )
    return {
        "kind": "mail",
        "text": f"📬 **{head}** — {detail}",
        "speak": f"You have {head}. {detail}.",
    }


def _announce(messages: list) -> None:
    item = _compose_mail(messages)
    with _lock:
        _pending.append(item)
    _popup("J.A.R.V.I.S. — new mail", item["speak"][:900])


def _watch_loop(cfg) -> None:
    # First establish the watermark (never announce existing mail), then poll.
    while not _stop.is_set():
        try:
            prefs = load_prefs()
            ready = (bool(prefs.get("mail_last_uid"))
                     and prefs.get("mail_user") == cfg.address)
            if not ready:
                uid = email_control.highest_uid(cfg)
                with _lock:
                    cur = load_prefs()
                    cur["mail_user"] = cfg.address
                    cur["mail_last_uid"] = uid
                    _save_prefs(cur)
                _watch_info["last_check"] = datetime.now().strftime("%H:%M")
                _watch_info["last_error"] = ""
            else:
                last = int(prefs.get("mail_last_uid") or 0)
                messages, new_last = email_control.fetch_since_uid(cfg, last)
                if new_last > last:
                    with _lock:
                        cur = load_prefs()
                        cur["mail_last_uid"] = new_last
                        _save_prefs(cur)
                _watch_info["last_check"] = datetime.now().strftime("%H:%M")
                _watch_info["last_error"] = ""
                if messages:
                    _announce(messages)
        except Exception as exc:  # noqa: BLE001 - keep watching next cycle
            _watch_info["last_error"] = str(exc)[:120]
            _watch_info["last_check"] = datetime.now().strftime("%H:%M")
        _stop.wait(MAIL_POLL_SECONDS)


def start_mail_watch(cfg) -> None:
    """Start the watcher once per process; idempotent."""
    global _watch_thread
    with _lock:
        # Clear first: toggling off->on can land here while the old thread is
        # still waking from _stop.wait(); clearing after the early-return would
        # let it die and leave nothing running.
        _stop.clear()
        if _watch_thread and _watch_thread.is_alive():
            return
        _watch_thread = threading.Thread(
            target=_watch_loop, args=(cfg,), name="jarvis-mail-watch", daemon=True
        )
        thread = _watch_thread
    thread.start()


def stop_mail_watch() -> None:
    _stop.set()


def mail_watch_status() -> str:
    with _lock:
        alive = bool(_watch_thread and _watch_thread.is_alive())
    if not alive:
        return ""
    if _watch_info["last_error"]:
        return f"📬 Mail watch problem: {_watch_info['last_error']}"
    if _watch_info["last_check"]:
        return f"📬 Last mail check {_watch_info['last_check']}."
    return "📬 Mail watch starting…"


def reset_mail_watermark() -> None:
    """Forget the watermark so the next check starts from the newest message."""
    with _lock:
        prefs = load_prefs()
        prefs["mail_last_uid"] = 0
        prefs["mail_user"] = ""
        _save_prefs(prefs)


# --------------------------------------------------------------------------- #
# New-WhatsApp-message watcher
# --------------------------------------------------------------------------- #

WA_POLL_SECONDS = 90

_wa_stop = threading.Event()
_wa_thread: threading.Thread | None = None
_wa_info = {"last_check": "", "last_error": ""}


def _wa_rows() -> list:
    """Chats from the linked WhatsApp Web sidebar, unread badge included.

    Pure sidebar peek - nothing is clicked, so nothing is marked as read.
    """
    port, _ = whatsapp_control._require_ready()
    rows = whatsapp_control._evaluate(
        port, whatsapp_control._js(whatsapp_control.JS_CHAT_LIST, 25))
    if not isinstance(rows, list):
        return []
    return [r for r in rows
            if isinstance(r, dict) and str(r.get("title", "")).strip()]


def _wa_count(row: dict) -> int:
    try:
        return int(str(row.get("unread", "")).strip() or 0)
    except (TypeError, ValueError):
        return 0


def _compose_wa(rows: list) -> dict:
    if len(rows) == 1:
        who = str(rows[0].get("title", "someone"))
        prev = str(rows[0].get("preview") or "").strip()
        text = f"💬 **New WhatsApp** from {who}" + (f" — {prev[:80]}" if prev else "")
        speak = f"New WhatsApp message from {who}." + (f" It says: {prev[:140]}." if prev else "")
        return {"kind": "whatsapp", "text": text, "speak": speak}
    head = f"{len(rows)} chats with new WhatsApp messages"
    detail = "; ".join(
        f"{r.get('title', '?')}: {str(r.get('preview') or '').strip()[:50]}"
        for r in rows[:3]
    )
    return {"kind": "whatsapp", "text": f"💬 **{head}** — {detail}",
            "speak": f"You have {head}. {detail}."}


def _announce_wa(rows: list) -> None:
    item = _compose_wa(rows)
    with _lock:
        _pending.append(item)
    _popup("J.A.R.V.I.S. — new WhatsApp", item["speak"][:900])


def _wa_watch_loop() -> None:
    # The first completed check only establishes the watermark - existing
    # unread never alerts. After that, a chat's unread count GROWING (or a
    # fresh title with unread) is announced.
    while not _wa_stop.is_set():
        try:
            rows = _wa_rows()
            snap = {str(r["title"]): _wa_count(r) for r in rows if _wa_count(r) > 0}
            with _lock:
                prefs = load_prefs()
            baseline = prefs.get("wa_last")
            if not isinstance(baseline, dict):
                baseline = {}
            if not prefs.get("wa_marked"):
                with _lock:
                    save_prefs({"wa_last": snap, "wa_marked": True})
            else:
                fresh = [r for r in rows
                         if _wa_count(r) > int(baseline.get(str(r.get("title", "")), 0))]
                if fresh:
                    _announce_wa(fresh)
                if snap != baseline:
                    with _lock:
                        save_prefs({"wa_last": snap})
            _wa_info["last_check"] = datetime.now().strftime("%H:%M")
            _wa_info["last_error"] = ""
        except Exception as exc:  # noqa: BLE001 - keep watching next cycle
            _wa_info["last_error"] = str(exc)[:120]
            _wa_info["last_check"] = datetime.now().strftime("%H:%M")
        _wa_stop.wait(WA_POLL_SECONDS)


def start_wa_watch() -> None:
    """Start the WhatsApp watcher once per process; idempotent.

    The watermark lives in the prefs, so messages that arrived while the
    watcher was off (or the app was closed) are announced once it runs again.
    """
    global _wa_thread
    with _lock:
        # Clear first: toggling off->on can land here while the old thread is
        # still waking from _wa_stop.wait(); clearing after the early-return
        # would let it die and leave nothing running.
        _wa_stop.clear()
        if _wa_thread and _wa_thread.is_alive():
            return
        _wa_thread = threading.Thread(target=_wa_watch_loop, name="jarvis-wa-watch", daemon=True)
        thread = _wa_thread
    thread.start()


def stop_wa_watch() -> None:
    _wa_stop.set()


def wa_watch_status() -> str:
    with _lock:
        alive = bool(_wa_thread and _wa_thread.is_alive())
    if not alive:
        return ""
    if _wa_info["last_error"]:
        return f"💬 WhatsApp watch problem: {_wa_info['last_error']}"
    if _wa_info["last_check"]:
        return f"💬 Last WhatsApp check {_wa_info['last_check']}."
    return "💬 WhatsApp watch starting…"


# --------------------------------------------------------------------------- #
# UI hook
# --------------------------------------------------------------------------- #


def pop_proactive() -> list:
    """Briefing (if due) plus queued mail alerts; clears the buffer."""
    out = []
    try:
        briefing = _due_briefing()
    except Exception:  # noqa: BLE001 - never break the page for a briefing
        briefing = None
    if briefing:
        out.append(briefing)
    with _lock:
        out.extend(_pending)
        _pending.clear()
    return out
