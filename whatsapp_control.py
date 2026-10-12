"""WhatsApp read & send through WhatsApp Web, driven over Chrome DevTools Protocol.

The user asked for full handling of their own WhatsApp: SEE messages and SEND to
any contact by name. There is no official local API, so this drives the real
WhatsApp Web page in a small dedicated browser window:

- Launches the PC's own Edge (or Chrome) with --remote-debugging-port and a
  private profile in ~/.jarvis/wa-edge, so the user's normal browsing is untouched.
- First time, WhatsApp Web shows a QR code — scan it once with the phone
  (WhatsApp → Settings → Linked devices → Link a device). The session persists
  in that profile afterwards.
- Reads the chat list / a conversation and searches a contact by name, then
  delivers the message for real (no phone number needed, no manual send).

Only the `websockets` package is used for the CDP socket — already bundled with
the app, so nothing new ships. Everything runs locally on the user's machine.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from langchain_core.tools import tool

import followups

CDP_PORT_RANGE = range(9222, 9232)
BROWSER_WAIT_SECONDS = 25
PAGE_WAIT_SECONDS = 30

_lock = threading.RLock()

EDGE_PATHS = [
    os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 "Microsoft", "Edge", "Application", "msedge.exe"),
    os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                 "Microsoft", "Edge", "Application", "msedge.exe"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge",
                 "Application", "msedge.exe"),
]
CHROME_PATHS = [
    os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                 "Google", "Chrome", "Application", "chrome.exe"),
    os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 "Google", "Chrome", "Application", "chrome.exe"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome",
                 "Application", "chrome.exe"),
]


# --------------------------------------------------------------------------- #
# Paths & state
# --------------------------------------------------------------------------- #

def profile_dir() -> str:
    path = os.path.join(followups.data_dir(), "wa-edge")
    os.makedirs(path, exist_ok=True)
    return path


def state_path() -> str:
    return os.path.join(followups.data_dir(), "wa_cdp.json")


def _read_state() -> dict:
    try:
        with open(state_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(port: int) -> None:
    try:
        with open(state_path(), "w", encoding="utf-8") as fh:
            json.dump({"port": port}, fh)
    except OSError:
        pass


def _find_browser() -> str:
    for cand in EDGE_PATHS + CHROME_PATHS:
        if cand and os.path.exists(cand):
            return cand
    for name in ("msedge.exe", "chrome.exe"):
        found = shutil.which(name)
        if found:
            return found
    return ""


# --------------------------------------------------------------------------- #
# CDP plumbing
# --------------------------------------------------------------------------- #

def _http_json(port: int, path: str, method: str = "GET", timeout: float = 4):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _version_ok(port: int) -> bool:
    try:
        info = _http_json(port, "/json/version")
        return bool(info.get("webSocketDebuggerUrl"))
    except Exception:  # noqa: BLE001
        return False


def _free_port() -> int:
    for p in CDP_PORT_RANGE:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return CDP_PORT_RANGE[0]


async def _cdp_call(ws_url: str, method: str, params: dict, timeout: float = 25) -> dict:
    import websockets

    async with websockets.connect(ws_url, max_size=8_000_000, close_timeout=2) as ws:
        await ws.send(json.dumps({"id": 1, "method": method, "params": params}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(0.5, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                break
            data = json.loads(raw)
            if data.get("id") == 1:
                if "error" in data:
                    raise RuntimeError(str(data["error"])[:200])
                return data.get("result", {})
    raise RuntimeError("The WhatsApp browser did not answer in time.")


def _cdp(port: int, method: str, params: dict, timeout: float = 25) -> dict:
    tab = _wa_tab(port)
    return asyncio.run(_cdp_call(tab["webSocketDebuggerUrl"], method, params, timeout))


def _evaluate(port: int, expression: str, timeout: float = 25):
    result = _cdp(port, "Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
        "awaitPromise": True,
        "timeout": int(timeout * 1000),
    }, timeout + 5)
    if result.get("exceptionDetails"):
        raise RuntimeError("WhatsApp page script failed.")
    value = result.get("result", {}).get("value")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


# --------------------------------------------------------------------------- #
# Browser session
# --------------------------------------------------------------------------- #

def _launch_browser(port: int) -> None:
    browser = _find_browser()
    if not browser:
        raise RuntimeError("Neither Microsoft Edge nor Google Chrome was found on this PC.")
    args = [
        browser,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        "--start-maximized",
        "https://web.whatsapp.com/",
    ]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL)


def _wa_tab(port: int) -> dict:
    """Return the WhatsApp Web debug target, opening a tab if needed."""
    deadline = time.monotonic() + 15
    while True:
        try:
            targets = _http_json(port, "/json/list")
            for t in targets:
                if "web.whatsapp.com" in (t.get("url") or ""):
                    return t
            # no tab yet - open one
            try:
                t = _http_json(port, f"/json/new?{urllib.parse.quote('https://web.whatsapp.com/', safe='')}",
                               method="PUT")
            except Exception:  # noqa: BLE001 - older builds accept GET
                t = _http_json(port, "/json/new?https://web.whatsapp.com/")
            if t and t.get("webSocketDebuggerUrl"):
                return t
        except Exception:  # noqa: BLE001
            pass
        if time.monotonic() > deadline:
            raise RuntimeError("Could not reach the WhatsApp browser tab.")
        time.sleep(0.6)


def ensure_session() -> int:
    """Return a live CDP port with WhatsApp Web open, launching if needed."""
    with _lock:
        port = int(_read_state().get("port") or 0)
        if port and _version_ok(port):
            return port
        # the window may still be open from an earlier run on another port
        for p in CDP_PORT_RANGE:
            if _version_ok(p):
                try:
                    targets = _http_json(p, "/json/list")
                    if any("web.whatsapp.com" in (t.get("url") or "") for t in targets):
                        _write_state(p)
                        return p
                except Exception:  # noqa: BLE001
                    continue
        port = _free_port()
        _launch_browser(port)
        deadline = time.monotonic() + BROWSER_WAIT_SECONDS
        while time.monotonic() < deadline:
            if _version_ok(port):
                _write_state(port)
                return port
            time.sleep(0.8)
        raise RuntimeError(
            "The WhatsApp browser window did not start in time — check that "
            "Edge/Chrome is allowed to open on this PC."
        )


JS_READY = """(function(){
  if (document.querySelector('#pane-side')) return 'ready';
  var qr = document.querySelector('canvas') ||
    /Use WhatsApp on your computer|Log into WhatsApp Web|Linked devices/i.test(document.body.innerText||'');
  return qr ? 'qr' : 'loading';
})()"""


def _wait_ready(port: int, timeout: float = PAGE_WAIT_SECONDS) -> str:
    deadline = time.monotonic() + timeout
    state = "loading"
    while time.monotonic() < deadline:
        try:
            state = _evaluate(port, JS_READY, timeout=8)
        except Exception:  # noqa: BLE001
            state = "loading"
        if state in ("ready", "qr"):
            return state
        time.sleep(1.0)
    return state


def quick_status() -> str:
    """Sidebar hint: 'linked', 'qr' or 'off' — never launches a browser."""
    try:
        port = int(_read_state().get("port") or 0)
        if not port or not _version_ok(port):
            return "off"
        state = _wait_ready(port, timeout=6)
        return "linked" if state == "ready" else state
    except Exception:  # noqa: BLE001
        return "off"


def open_login_window() -> str:
    """Open the WhatsApp Web window so the user can scan the QR code once."""
    port = ensure_session()
    state = _wait_ready(port)
    if state == "ready":
        return "WhatsApp is already linked — JARVIS can read and send messages."
    return (
        "The WhatsApp window is open on your screen. Scan the QR code with your "
        "phone: WhatsApp → Settings → Linked devices → Link a device. "
        "Linking lasts for weeks; you scan only this once."
    )


def _require_ready() -> tuple:
    """Return (port, None) or raise a friendly RuntimeError."""
    port = ensure_session()
    state = _wait_ready(port)
    if state == "ready":
        return port, None
    if state == "qr":
        raise RuntimeError(
            "WhatsApp is not linked yet. I made sure the WhatsApp login window is "
            "open on your screen — scan the QR with your phone (WhatsApp → "
            "Settings → Linked devices → Link a device), then ask me again."
        )
    raise RuntimeError("WhatsApp Web is still loading — give it a few seconds and ask again.")


# --------------------------------------------------------------------------- #
# In-page actions (JS snippets — every value leaves the page as JSON text)
# --------------------------------------------------------------------------- #

_JS_ARG = "__ARG__"


def _js(template: str, arg) -> str:
    return template.replace(_JS_ARG, json.dumps(arg))


JS_CHAT_LIST = """(function(){
  var rows = document.querySelectorAll('#pane-side [role="listitem"], #pane-side [data-testid="cell-frame-container"]');
  var out = [];
  for (var i = 0; i < rows.length && out.length < __ARG__; i++) {
    var r = rows[i];
    var t = r.querySelector('span[title]');
    if (!t) continue;
    var title = (t.getAttribute('title') || '').trim();
    if (!title) continue;
    var unread = '';
    var b = r.querySelector('[data-testid="icon-unread-count"]');
    if (b) unread = (b.textContent || '').trim();
    if (!unread) {
      var m = ((r.getAttribute('aria-label') || '').match(/(\\d+)\\s*unread/i));
      if (m) unread = m[1];
    }
    var p = r.querySelector('.copyable-text span');
    out.push({title: title, unread: unread, preview: (p ? p.textContent : '').trim().slice(0, 120)});
  }
  return JSON.stringify(out);
})()"""

JS_TYPE_INTO = """(function(){
  var q = __ARG__.text, sel = __ARG__.selector;
  var el = document.querySelector(sel);
  if (!el) return JSON.stringify({ok: false, err: 'missing'});
  var isInput = el.tagName === 'INPUT' || el.tagName === 'TEXTAREA';
  el.focus();
  if (isInput) {
    var proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    var setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    setter.call(el, q);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    return new Promise(function(res){
      setTimeout(function(){ res(JSON.stringify({ok: true, has: el.value.includes(q.slice(0, Math.min(8, q.length)))})); }, 150);
    });
  }
  if (el.select) { try { el.select(); } catch (e) {} }
  document.execCommand('delete', false);
  var dt = new DataTransfer();
  dt.setData('text/plain', q);
  el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
  return new Promise(function(res){
    setTimeout(function(){
      if (!el.textContent.includes(q.slice(0, Math.min(8, q.length)))) {
        document.execCommand('insertText', false, q);
      }
      setTimeout(function(){
        res(JSON.stringify({ok: true, has: el.textContent.includes(q.slice(0, Math.min(8, q.length)))}));
      }, 150);
    }, 150);
  });
})()"""

JS_SEARCH_RESULTS = """(function(){
  var rows = document.querySelectorAll('#pane-side [data-testid="chat-list"] [data-testid^="list-item-"], #pane-side [data-testid="cell-frame-container"]');
  var out = [];
  for (var i = 0; i < rows.length && out.length < 10; i++) {
    var t = rows[i].querySelector('span[title]');
    var title = t ? (t.getAttribute('title') || '').trim() : '';
    if (!title) continue;
    var b = rows[i].getBoundingClientRect();
    out.push({title: title,
      x: Math.round(b.left + b.width / 2),
      y: Math.round(b.top + Math.min(b.height / 2, 40))});
  }
  return JSON.stringify(out);
})()"""

JS_OPEN_TITLE = """(function(){
  var msg = document.querySelector('[data-testid="msg-container"], footer div[contenteditable="true"]');
  if (!msg) return JSON.stringify({title: ''});
  var el = msg, header = null;
  for (var i = 0; i < 15 && el; i++) {
    var h = el.querySelector ? el.querySelector('header, [data-testid="conversation-info-header"]') : null;
    if (h) { header = h; break; }
    el = el.parentElement;
  }
  if (!header) return JSON.stringify({title: ''});
  var named = header.querySelector('[data-testid="conversation-info-header-chat-title-name"]');
  var title = named ? named.textContent.trim() : header.innerText.trim().split('\\n')[0];
  return JSON.stringify({title: title});
})()"""

JS_READ_MESSAGES = """(function(){
  var n = __ARG__;
  var items = document.querySelectorAll('[data-testid="msg-container"]');
  var out = [];
  for (var i = Math.max(0, items.length - n); i < items.length; i++) {
    var it = items[i];
    var spans = it.querySelectorAll('span.selectable-text.copyable-text');
    var text = '';
    for (var j = 0; j < spans.length; j++) text += spans[j].textContent;
    text = text.trim();
    if (!text) continue;
    var meta = it.querySelector('[data-testid="msg-meta"]');
    var tspan = meta ? meta.querySelector('span') : null;
    var time = tspan ? tspan.textContent.trim() : (meta ? meta.textContent.trim() : '');
    var st = it.querySelector('[data-testid="msg-meta"] svg title');
    var stTxt = st ? (st.textContent || '') : '';
    var me = !!it.closest('.message-out')
      || /wds-ic-(read|msg-check|clock|round-check|msg-dblcheck)/.test(stTxt)
      || !!it.querySelector('[data-testid="msg-dblcheck"], [data-testid="msg-check"]');
    var who = '';
    if (!me) {
      var we = it.querySelector('[data-testid="msg-contact-name"]');
      if (we) who = we.textContent.trim();
    }
    out.push({who: who, time: time, me: me, text: text.slice(0, 400)});
  }
  return JSON.stringify(out.slice(-n));
})()"""

JS_COMPOSER = "footer div[contenteditable='true']"
JS_FOCUS_COMPOSER = """(function(){
  var el = document.querySelector(__ARG__);
  if (!el) return JSON.stringify({ok: false});
  el.focus();
  return JSON.stringify({ok: true});
})()"""
JS_COMPOSER_TEXT = """(function(){
  var el = document.querySelector(__ARG__);
  return JSON.stringify({text: el ? el.textContent : ''});
})()"""
JS_SEARCH_BOX = ('#side input[type="text"], #pane-side input[type="text"], #side input, #pane-side input, '
                 '[data-testid="chat-list-search"], header div[contenteditable="true"][role="textbox"], '
                 'header div[contenteditable="true"], header input[type="text"]')

ENTER_PARAMS = {"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"}

JS_LAST_OUTGOING = """(function(){
  var items = document.querySelectorAll('[data-testid="msg-container"]');
  for (var i = items.length - 1; i >= 0; i--) {
    var it = items[i];
    var st = it.querySelector('[data-testid="msg-meta"] svg title');
    var stTxt = st ? (st.textContent || '') : '';
    var outgoing = !!it.closest('.message-out')
      || /wds-ic-(read|msg-check|clock|round-check|msg-dblcheck)/.test(stTxt)
      || !!it.querySelector('[data-testid="msg-dblcheck"], [data-testid="msg-check"]');
    if (!outgoing) continue;
    var spans = it.querySelectorAll('span.selectable-text.copyable-text');
    var text = '';
    for (var j = 0; j < spans.length; j++) text += spans[j].textContent;
    return JSON.stringify({text: text.trim(), idx: i});
  }
  return JSON.stringify({text: '', idx: -1});
})()"""

JS_SYNTH_ENTER = """(function(){
  var c = document.querySelector("footer div[contenteditable='true']");
  if (!c) return JSON.stringify({ok: false});
  c.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true}));
  return JSON.stringify({ok: true});
})()"""

JS_FOCUS_SEARCH = """(function(){
  var el = document.querySelector(__ARG__);
  if (!el) return JSON.stringify({ok: false});
  el.focus();
  if (el.select) { try { el.select(); } catch (e) {} }
  return JSON.stringify({ok: true, tag: el.tagName});
})()"""

_BACKSPACE_DOWN = {"type": "keyDown", "key": "Backspace", "code": "Backspace",
                   "windowsVirtualKeyCode": 8, "nativeVirtualKeyCode": 8}
_BACKSPACE_UP = {"type": "keyUp", "key": "Backspace", "code": "Backspace",
                 "windowsVirtualKeyCode": 8, "nativeVirtualKeyCode": 8}
_SELECT_ALL_DOWN = {"type": "keyDown", "key": "a", "code": "KeyA", "modifiers": 2,
                    "windowsVirtualKeyCode": 65, "nativeVirtualKeyCode": 65}
_SELECT_ALL_UP = {"type": "keyUp", "key": "a", "code": "KeyA", "modifiers": 2,
                  "windowsVirtualKeyCode": 65, "nativeVirtualKeyCode": 65}


def _ensure_foreground() -> None:
    """Un-minimize the WhatsApp Edge window — the page pauses rendering while hidden."""
    try:
        import ctypes

        u32 = ctypes.windll.user32
        matches = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def cb(hwnd, _):
            n = u32.GetWindowTextLengthW(hwnd)
            if not n:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value
            if "WhatsApp" in title and "Edge" in title and "Chrome" not in title:
                matches.append(hwnd)
            return True

        u32.EnumWindows(cb, 0)
        for hwnd in matches:
            u32.ShowWindow(hwnd, 9)  # SW_RESTORE
            u32.SetForegroundWindow(hwnd)
    except Exception:  # noqa: BLE001
        pass


def _type_search_query(port: int, text: str) -> None:
    """Type into the WA search box with CDP trusted input (React sees it)."""
    focused = _evaluate(port, _js(JS_FOCUS_SEARCH, JS_SEARCH_BOX), timeout=10)
    if not isinstance(focused, dict) or not focused.get("ok"):
        raise RuntimeError("I could not reach the WhatsApp search box.")
    time.sleep(0.2)
    # select all + backspace clears whatever the previous search left behind
    _cdp(port, "Input.dispatchKeyEvent", _SELECT_ALL_DOWN)
    _cdp(port, "Input.dispatchKeyEvent", _SELECT_ALL_UP)
    _cdp(port, "Input.dispatchKeyEvent", _BACKSPACE_DOWN)
    _cdp(port, "Input.dispatchKeyEvent", _BACKSPACE_UP)
    time.sleep(0.3)
    _cdp(port, "Input.insertText", {"text": text})
    time.sleep(0.8)


def _click_at(port: int, x: float, y: float) -> None:
    """Trusted CDP mouse click — the new WhatsApp UI ignores synthetic DOM clicks."""
    _cdp(port, "Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    time.sleep(0.12)
    _cdp(port, "Input.dispatchMouseEvent",
         {"type": "mousePressed", "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1})
    time.sleep(0.12)
    _cdp(port, "Input.dispatchMouseEvent",
         {"type": "mouseReleased", "x": x, "y": y, "button": "left", "buttons": 0, "clickCount": 1})


def _open_chat_by_name(port: int, name: str, timeout: float = 25) -> str:
    """Search WhatsApp for `name`, click the best-matching result, return the title."""
    _ensure_foreground()
    deadline = time.monotonic() + timeout
    _type_search_query(port, name)
    # Right after typing, the list is still the unfiltered chat list — keep
    # polling until a row whose TITLE genuinely matches the typed name shows up.
    picked = None
    last_results: list = []
    while time.monotonic() < deadline:
        time.sleep(0.7)
        results = _evaluate(port, JS_SEARCH_RESULTS)
        if isinstance(results, list) and results:
            last_results = results
            picked = _pick_result(name, results)
            if picked:
                break
    if not picked and last_results:
        # No title matched the request — the fully-filtered list's first row
        # is still WhatsApp's own best guess.
        picked = last_results[0]
    if not picked:
        raise RuntimeError(f"I searched WhatsApp for '{name}' but found no matching chat.")
    _click_at(port, picked["x"], picked["y"])
    # wait for the conversation pane to mount and report its title
    opened = None
    while time.monotonic() < deadline:
        time.sleep(0.8)
        opened = _evaluate(port, JS_OPEN_TITLE)
        if isinstance(opened, dict) and opened.get("title"):
            break
        opened = None
    title = opened.get("title", "") if isinstance(opened, dict) else ""
    if not title:
        raise RuntimeError("The chat did not open in WhatsApp — try again in a moment.")
    return title


def _names_match(requested: str, opened: str) -> bool:
    a = re.sub(r"[^a-z0-9]", "", requested.lower())
    b = re.sub(r"[^a-z0-9]", "", opened.lower())
    if not a or not b:
        return False
    return a in b or b in a


def _pick_result(name: str, results: list):
    """Pick the search result whose TITLE genuinely matches — search also
    matches message content, so the first row is often the wrong chat."""
    want = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    contains = None
    for r in results:
        title = str(r.get("title", ""))
        got = re.sub(r"[^a-z0-9]", "", title.lower())
        if not got:
            continue
        if got == want:
            return r
        if want and (want in got or got in want) and contains is None:
            contains = r
    return contains


# --------------------------------------------------------------------------- #
# Agent tools
# --------------------------------------------------------------------------- #

@tool
def whatsapp_unread(limit: int = 12) -> str:
    """Check the user's WhatsApp for unread chats: who messaged and a short
    preview of the latest message. Use for 'check my whatsapp', 'any new
    whatsapp messages'. Requires WhatsApp linked (one-time QR scan)."""
    try:
        port, _ = _require_ready()
    except RuntimeError as exc:
        return str(exc)
    try:
        rows = _evaluate(port, _js(JS_CHAT_LIST, max(1, min(int(limit or 12), 25))))
    except RuntimeError as exc:
        return f"I could not read the WhatsApp chat list: {exc}"
    if not isinstance(rows, list):
        return "WhatsApp did not answer in a readable way — try again in a moment."
    unread = [r for r in rows if str(r.get("unread", "")).strip()]
    if not unread:
        return "No unread WhatsApp messages right now."
    lines = []
    for r in unread[:12]:
        n = str(r.get("unread", "")).strip()
        prev = (r.get("preview") or "").strip()
        lines.append(f"- {r.get('title', '?')} ({n} unread)" + (f" — {prev}" if prev else ""))
    return f"{len(unread)} unread WhatsApp chat(s):\n" + "\n".join(lines)


@tool
def whatsapp_read_chat(contact: str, count: int = 15) -> str:
    """Open a WhatsApp chat by contact or group NAME and read the most recent
    messages. Use for 'what did Ali say on whatsapp', 'read my chat with Ali'.
    Requires WhatsApp linked (one-time QR scan)."""
    name = (contact or "").strip()
    if not name:
        return "Tell me whose WhatsApp chat to read, Sir."
    try:
        port, _ = _require_ready()
        opened = _open_chat_by_name(port, name)
    except RuntimeError as exc:
        return str(exc)
    if not _names_match(name, opened):
        return (f"I searched WhatsApp for '{name}' and the closest match was "
                f"'{opened}' — not close enough to read. Check the exact name.")
    try:
        msgs = _evaluate(port, _js(JS_READ_MESSAGES, max(1, min(int(count or 15), 40))))
    except RuntimeError as exc:
        return f"I opened '{opened}' but could not read the messages: {exc}"
    if not isinstance(msgs, list) or not msgs:
        return f"'{opened}' has no text messages to show yet."
    lines = []
    for m in msgs:
        who = "You" if m.get("me") else (m.get("who") or opened)
        tm = f"[{m['time']}] " if m.get("time") else ""
        lines.append(f"{tm}{who}: {m['text']}")
    return f"Recent messages with {opened}:\n" + "\n".join(lines)


@tool
def send_whatsapp_message(contact: str, message: str) -> str:
    """Send a WhatsApp message to a contact or group by NAME — WhatsApp is
    searched for the name and the message is DELIVERED automatically (no
    number needed, nothing left waiting for a manual send). Use for 'send
    whatsapp to Ali saying the meeting moved to 6'. Requires WhatsApp linked
    (one-time QR scan)."""
    name = (contact or "").strip()
    text = (message or "").strip()
    if not name:
        return "Tell me who to send it to, Sir."
    if not text:
        return "Tell me what message to send, Sir."
    if len(text) > 2000:
        return "That message is too long for one WhatsApp text — split it, Sir."
    try:
        port, _ = _require_ready()
        opened = _open_chat_by_name(port, name)
    except RuntimeError as exc:
        return str(exc)
    if not _names_match(name, opened):
        return (f"I searched WhatsApp for '{name}' and the closest match was "
                f"'{opened}' — I did not send anything. Tell me the exact name to use.")
    try:
        focused = _evaluate(port, _js(JS_FOCUS_COMPOSER, JS_COMPOSER), timeout=10)
    except RuntimeError as exc:
        return f"I opened '{opened}' but could not type the message: {exc}"
    if not isinstance(focused, dict) or not focused.get("ok"):
        return f"I opened '{opened}' but the message box was not reachable — try again."
    typed_ok = False
    try:
        time.sleep(0.2)
        _cdp(port, "Input.insertText", {"text": text})
        for _ in range(6):
            time.sleep(0.4)
            comp = _evaluate(port, _js(JS_COMPOSER_TEXT, JS_COMPOSER), timeout=10)
            if isinstance(comp, dict) and text[:80] in (comp.get("text") or ""):
                typed_ok = True
                break
    except RuntimeError:
        typed_ok = False
    if not typed_ok:
        try:
            typed = _evaluate(port, _js(JS_TYPE_INTO, {"selector": JS_COMPOSER, "text": text}), timeout=15)
            typed_ok = isinstance(typed, dict) and typed.get("ok")
        except RuntimeError:
            typed_ok = False
    if not typed_ok:
        return f"I opened '{opened}' but could not type the message — try again."
    sent = False
    try:
        _cdp(port, "Input.dispatchKeyEvent", dict(type="keyDown", **ENTER_PARAMS), timeout=10)
        _cdp(port, "Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter",
                                              "code": "Enter", "windowsVirtualKeyCode": 13}, timeout=10)
        for _ in range(8):
            time.sleep(0.6)
            last = _evaluate(port, JS_LAST_OUTGOING)
            if isinstance(last, dict) and last.get("text", "").strip() == text:
                sent = True
                break
        if not sent:
            _evaluate(port, JS_SYNTH_ENTER, timeout=10)
            for _ in range(8):
                time.sleep(0.6)
                last = _evaluate(port, JS_LAST_OUTGOING)
                if isinstance(last, dict) and last.get("text", "").strip() == text:
                    sent = True
                    break
    except RuntimeError:
        sent = False
    if sent:
        return f"Sent to {opened} on WhatsApp: {text}"
    return (f"I typed the message to {opened} but could not confirm it was "
            "delivered — please glance at the WhatsApp window on your screen.")


WHATSAPP_TOOLS = [whatsapp_unread, whatsapp_read_chat, send_whatsapp_message]

WHATSAPP_NOTES = (
    "\n\nWHATSAPP: you can READ and SEND the user's own real WhatsApp messages "
    "— whatsapp_unread (check for new messages), whatsapp_read_chat(contact=...) "
    "(read a conversation by NAME) and send_whatsapp_message(contact=..., "
    "message=...), which searches the contact by name in WhatsApp and DELIVERS "
    "the message automatically — no phone number, no manual send. "
    "'send whatsapp to Ali saying the meeting moved to 6' -> "
    "send_whatsapp_message(contact='Ali', message='the meeting moved to 6'); "
    "'check my whatsapp' -> whatsapp_unread(); 'what did Ali say' -> "
    "whatsapp_read_chat(contact='Ali'). It only works once the user has linked "
    "WhatsApp (sidebar → 💬 Link WhatsApp, one QR scan) — if a tool says it is "
    "not linked, tell the user to do that. Only ever act on the user's own "
    "WhatsApp exactly as asked; never message anyone unprompted, and report the "
    "resolved contact name when you send."
)
