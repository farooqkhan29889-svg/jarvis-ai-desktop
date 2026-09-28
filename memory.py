"""J.A.R.V.I.S. long-term memory - durable facts about the user, saved on disk.

Memories live in `~/.jarvis/memory.json` so they survive restarts, rebuilds and
being copied to another machine (move the `.jarvis` folder with the app).  The
agent saves facts when asked ("JARVIS, save this") and is also told to save
important durable facts on its own initiative.  A compact digest is injected
into the system prompt so JARVIS remembers across sessions.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool

from followups import data_dir

MAX_TEXT = 500
MAX_CONTEXT_ITEMS = 12
MAX_CONTEXT_CHARS = 1600

_lock = threading.RLock()


def store_path() -> Path:
    return data_dir() / "memory.json"


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


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# --------------------------------------------------------------------------- #
# Plain helpers (UI + agent wiring)
# --------------------------------------------------------------------------- #

def memories() -> list:
    """Raw memory dicts, newest first."""
    with _lock:
        return sorted(_load(), key=lambda i: i.get("updated", ""), reverse=True)


def memory_context() -> str:
    """Compact digest of saved memories, injected into the system prompt."""
    items = memories()[:MAX_CONTEXT_ITEMS]
    if not items:
        return "No memories stored yet."
    lines = []
    total = 0
    for i in items:
        line = f"- {i.get('text', '')} (saved {i.get('updated', '?')})"
        total += len(line)
        if total > MAX_CONTEXT_CHARS:
            break
        lines.append(line)
    return "\n".join(lines)


def fingerprint() -> str:
    """Cheap change-detector so the app knows when to refresh agent and UI."""
    with _lock:
        items = _load()
    return "|".join(f"{i.get('id')}:{i.get('updated')}" for i in items)


def clear_memory() -> int:
    """Wipe every saved memory. Returns how many were dropped."""
    with _lock:
        dropped = len(_load())
        _save([])
    return dropped


# --------------------------------------------------------------------------- #
# Agent tools
# --------------------------------------------------------------------------- #

@tool
def save_memory(text: str) -> str:
    """Save a durable fact about the user to persistent memory. Write `text` as a
    complete, self-contained fact with every detail spelled out (names, numbers,
    dates, places). Use when the user says 'save this'/'remember this', or when
    they share something durable worth keeping for future conversations. Never
    store passwords, API keys, card numbers or any secret."""
    fact = (text or "").strip()
    if not fact:
        return "Tell me what to save, Sir."
    fact = fact[:MAX_TEXT]
    with _lock:
        items = _load()
        hit = next(
            (i for i in items if i.get("text", "").strip().lower() == fact.lower()),
            None,
        )
        if hit is not None:
            hit["text"] = fact
            hit["updated"] = _now()
            _save(items)
            return f"Updated that memory ({len(items)} facts stored)."
        items.append({
            "id": uuid.uuid4().hex[:6],
            "text": fact,
            "created": _now(),
            "updated": _now(),
        })
        _save(items)
    return f"Saved to memory ({len(items)} facts stored): \"{fact}\""


@tool
def list_memories() -> str:
    """Show everything saved in persistent memory, each with its id, so the user
    can review or ask to forget specific items."""
    items = memories()
    if not items:
        return "Nothing is stored in my memory yet."
    lines = [f"[{i['id']}] {i.get('text', '')} (saved {i.get('updated', '?')})"
             for i in items]
    return f"{len(items)} memor{'y' if len(items) == 1 else 'ies'}:\n" + "\n".join(lines)


@tool
def forget_memory(item_id: str) -> str:
    """Delete a saved memory permanently. `item_id` is the short id from
    list_memories. Accept fuzzy references ('the one about the clinic') only if
    the exact id is not given - list first and match the best item."""
    target = (item_id or "").strip().lstrip("#")
    with _lock:
        items = _load()
        hit = next((i for i in items if i.get("id") == target), None)
        if hit is None:
            return f"I can't find a memory with id '{target}'. Use list_memories to see the ids."
        _save([i for i in items if i.get("id") != target])
    return f"Forgotten. ({len(items) - 1} facts still stored.)"


MEMORY_TOOLS = [save_memory, list_memories, forget_memory]

MEMORY_NOTES = (
    "\n\nMEMORY RULES: you have a persistent memory saved on disk - save_memory, "
    "list_memories, forget_memory. When the user says 'save this', 'remember "
    "this' or hands you a fact to keep, call save_memory with the fact written "
    "out in full detail (exact names, numbers, dates, places). ALSO save "
    "important durable facts on your own initiative, without being asked - the "
    "user's name and role, preferences, places, accounts, plans, deadlines, "
    "people they mention - anything likely to matter in later conversations; "
    "skip trivia and one-off requests, and make at most one or two save_memory "
    "calls per turn. NEVER save passwords, API keys, codes or anything secret. "
    "When the user asks what you remember about them, answer from USER MEMORY "
    "above; if unsure what is stored, call list_memories. When they ask you to "
    "forget something, call forget_memory and confirm it is gone."
)
