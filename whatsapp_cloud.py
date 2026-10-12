"""WhatsApp through the official Meta Cloud API (no browser, no QR scan).

This is the second WhatsApp channel next to :mod:`whatsapp_control`. That one
drives WhatsApp Web and can reach every contact in the user's personal account;
this one talks to Meta's Graph API and is what a business number uses:

- OUTBOUND: text, media and approved templates to any international number.
- INBOUND: Meta posts new messages to a webhook, which is served by an extra
  route on this same Streamlit server (same mechanism as :mod:`stop_signal`).
  JARVIS can then answer on its own with the same agent.
- Because a laptop behind a router has no public HTTPS address, a quick tunnel
  can be started from the sidebar to get one for the webhook.

Meta's rules shape the code, so they are enforced here rather than discovered
by the user as send failures:

- Free-form text is only accepted inside the 24-hour window opened by the
  recipient's own last message. Outside it, a pre-approved template is required
  (error 131047 says exactly that, and the message is mapped to plain English).
- A test business can only message a handful of verified recipient numbers.
- Every webhook POST is verified with the app secret (X-Hub-Signature-256) when
  one is configured, and answered 200 immediately - Meta retries otherwise.

Credentials are never written to disk unless the user ticks "remember on this
PC", and they are never echoed back to the UI.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from langchain_core.tools import tool

import followups

GRAPH_HOST = "https://graph.facebook.com"
DEFAULT_API_VERSION = "v25.0"
WEBHOOK_ROUTE = "/_jarvis/whatsapp"
WINDOW_HOURS = 24
MAX_TEXT_LEN = 4096
INBOX_KEEP = 300
OUTBOX_KEEP = 200

TUNNEL_DIR_NAME = "bin"
CLOUDFLARED_URL = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-windows-amd64.exe"
)

_lock = threading.RLock()


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

@dataclass
class CloudConfig:
    """One WhatsApp Business endpoint. `token` and `app_secret` are secrets:
    they are only ever shown masked."""

    token: str = ""
    phone_number_id: str = ""
    waba_id: str = ""
    app_secret: str = ""
    verify_token: str = "jarvis-whatsapp"
    api_version: str = DEFAULT_API_VERSION
    business_name: str = ""
    our_number: str = ""          # the business's own number, filled by test_connection
    remember: bool = False

    @property
    def ready(self) -> bool:
        return bool(self.token.strip() and self.phone_number_id.strip())

    @property
    def webhook_verified(self) -> bool:
        return bool(self.app_secret.strip())

    def masked(self) -> str:
        tok = self.token.strip()
        tail = tok[-4:] if len(tok) > 4 else ""
        num = self.business_name.strip() or self.our_number.strip() or self.phone_number_id.strip()
        return f"{num or 'WhatsApp Cloud API'} · token …{tail}" if tail else (num or "(not set)")


def _config_path() -> Path:
    return followups.data_dir() / "wa_cloud.json"


def _prefs_path() -> Path:
    return followups.data_dir() / "wa_cloud_prefs.json"


def _contacts_path() -> Path:
    return followups.data_dir() / "wa_cloud_contacts.json"


def _inbox_path() -> Path:
    return followups.data_dir() / "wa_cloud_inbox.json"


def _outbox_path() -> Path:
    return followups.data_dir() / "wa_cloud_outbox.json"


DEFAULT_PREFS = {
    "auto_reply": False,
    "reply_style": "assistant",       # assistant | echo | off
    "notify_to": [],                  # numbers that get reminders/briefings
    "notify_reminders": False,
    "notify_briefing": False,
    "allowed_senders": [],            # empty = anyone may talk to the bot
    "last_public_url": "",
}


def from_env() -> CloudConfig:
    """Config from .env / environment - the place secrets belong."""
    return CloudConfig(
        token=os.environ.get("JARVIS_WA_TOKEN", "").strip(),
        phone_number_id=os.environ.get("JARVIS_WA_PHONE_ID", "").strip(),
        waba_id=os.environ.get("JARVIS_WA_WABA_ID", "").strip(),
        app_secret=os.environ.get("JARVIS_WA_APP_SECRET", "").strip(),
        verify_token=(os.environ.get("JARVIS_WA_VERIFY_TOKEN", "").strip()
                      or "jarvis-whatsapp"),
        api_version=(os.environ.get("JARVIS_WA_API_VERSION", "").strip()
                     or DEFAULT_API_VERSION),
        business_name=os.environ.get("JARVIS_WA_BUSINESS_NAME", "").strip(),
    )


def _read_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def saved_config() -> CloudConfig | None:
    """The config the user opted to keep on this PC, or None."""
    data = _read_json(_config_path(), {})
    if not isinstance(data, dict) or not data.get("token"):
        return None
    return CloudConfig(
        token=str(data.get("token", "")),
        phone_number_id=str(data.get("phone_number_id", "")),
        waba_id=str(data.get("waba_id", "")),
        app_secret=str(data.get("app_secret", "")),
        verify_token=str(data.get("verify_token", "") or "jarvis-whatsapp"),
        api_version=str(data.get("api_version", "") or DEFAULT_API_VERSION),
        business_name=str(data.get("business_name", "")),
        our_number=str(data.get("our_number", "")),
        remember=True,
    )


def save_config(cfg: CloudConfig) -> None:
    if cfg.remember:
        _write_json(_config_path(), {
            "token": cfg.token.strip(),
            "phone_number_id": cfg.phone_number_id.strip(),
            "waba_id": cfg.waba_id.strip(),
            "app_secret": cfg.app_secret.strip(),
            "verify_token": cfg.verify_token.strip(),
            "api_version": cfg.api_version.strip() or DEFAULT_API_VERSION,
            "business_name": cfg.business_name.strip(),
            "our_number": cfg.our_number.strip(),
        })
    else:
        try:
            _config_path().unlink()
        except OSError:
            pass


def forget_config() -> None:
    try:
        _config_path().unlink()
    except OSError:
        pass


# The webhook runs outside any Streamlit session, so app.py hands the session's
# config to the module on every rerun. Only the local desktop build does this -
# a hosted deployment answers webhooks from .env/secrets alone, so one viewer
# can never reply using another's token.
_runtime_cfg: CloudConfig | None = None


def set_runtime_config(cfg: CloudConfig | None) -> None:
    global _runtime_cfg
    with _lock:
        _runtime_cfg = cfg if (cfg is not None and cfg.ready) else None


def active_config() -> CloudConfig:
    """Best available config: this session, then .env, then the saved one."""
    with _lock:
        if _runtime_cfg is not None and _runtime_cfg.ready:
            return _runtime_cfg
    env = from_env()
    if env.ready:
        return env
    saved = saved_config()
    return saved or env


def startup_config() -> CloudConfig:
    """What a fresh session starts with: .env, else the config kept on this PC."""
    env = from_env()
    if env.ready:
        return env
    return saved_config() or env


def load_prefs() -> dict:
    merged = dict(DEFAULT_PREFS)
    stored = _read_json(_prefs_path(), {})
    if isinstance(stored, dict):
        merged.update(stored)
    return merged


def save_prefs(changes: dict) -> None:
    with _lock:
        prefs = load_prefs()
        if all(prefs.get(k) == v for k, v in changes.items()):
            return
        prefs.update(changes)
        _write_json(_prefs_path(), prefs)


# --------------------------------------------------------------------------- #
# Numbers, errors
# --------------------------------------------------------------------------- #

_DIGITS = re.compile(r"\D+")


def normalize_number(raw: str) -> str:
    """International format without the '+', as the Graph API expects it."""
    text = _DIGITS.sub("", str(raw or ""))
    if text.startswith("00"):
        text = text[2:]
    return text


def valid_number(raw: str) -> bool:
    return 8 <= len(normalize_number(raw)) <= 15


class CloudError(RuntimeError):
    def __init__(self, message: str, code: int = 0, subcode: int = 0):
        super().__init__(message)
        self.code = code
        self.subcode = subcode


# (code, subcode) -> plain English. Meta's own text is unusable for a user who
# is setting this up for the first time.
_ERROR_HINTS = {
    (190, 0): "Meta rejected the access token - it expired or was pasted wrong. "
              "Make a new System User token in Business Settings and paste it again.",
    (100, 131030): "That number is not allowed to receive messages from this "
                   "business yet. A test business can only message numbers you "
                   "add and verify in WhatsApp Manager (up to 5).",
    (131047, 0): "The 24-hour reply window has closed, so a free-form text is "
                 "refused. Send an approved template instead, or wait for them "
                 "to message you first.",
    (131026, 0): "Meta refused this recipient - the number is not on WhatsApp, "
                 "or the template is not approved for it.",
    (132000, 0): "The template name or its number of parameters does not match "
                 "the approved template.",
    (132001, 0): "Meta does not have a template by that name for this business.",
    (132016, 0): "That template is still waiting for approval - it cannot be "
                 "sent yet.",
    (133000, 0): "Meta rate-limited this business number. Wait a minute and try "
                 "again with fewer recipients.",
    (803, 0): "The Phone Number ID is wrong - copy it from WhatsApp > API Setup "
              "in the Meta developer console.",
    (10, 2635): "This Meta app is not allowed to use WhatsApp yet - finish the "
                "WhatsApp product setup for the app.",
    (4, 0): "Too many API calls just now - wait a few seconds and retry.",
}


def _friendly(err: dict) -> str:
    code = int(err.get("code") or 0)
    sub = int(err.get("error_subcode") or 0)
    hint = _ERROR_HINTS.get((code, sub)) or _ERROR_HINTS.get((code, 0))
    raw = str(err.get("message") or "Meta refused the call.").strip()
    if hint:
        return f"{hint} (Meta: {raw} [{code}/{sub}])"
    return f"Meta refused the call: {raw} (code {code}{f'/{sub}' if sub else ''})."


# --------------------------------------------------------------------------- #
# Graph API plumbing (stdlib only - the exe already ships these)
# --------------------------------------------------------------------------- #

def _url(cfg: CloudConfig, path: str) -> str:
    version = (cfg.api_version or DEFAULT_API_VERSION).strip().lstrip("/")
    if not version.startswith("v"):
        version = "v" + version
    return f"{GRAPH_HOST}/{version}/{path.lstrip('/')}"


def _request(url: str, token: str, payload: dict | None = None, method: str | None = None,
             timeout: float = 40) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method or ("POST" if data is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8", "replace"))
        except (ValueError, OSError):
            detail = {}
        err = (detail or {}).get("error") or {}
        if err:
            raise CloudError(_friendly(err), int(err.get("code") or 0),
                             int(err.get("error_subcode") or 0)) from None
        raise CloudError(f"Meta answered {exc.code} for this request.") from None
    except urllib.error.URLError as exc:
        raise CloudError(f"Could not reach Meta ({exc.reason}). Check the internet "
                         "connection, or a firewall blocking graph.facebook.com.") from None
    except (TimeoutError, OSError) as exc:
        raise CloudError(f"Meta did not answer in time ({exc}).") from None
    if not body.strip():
        return {}
    try:
        return json.loads(body)
    except ValueError:
        return {"raw": body[:300]}


def _post(cfg: CloudConfig, path: str, payload: dict) -> dict:
    if not cfg.token.strip():
        raise CloudError("No WhatsApp access token is set - open the WhatsApp Cloud "
                         "panel in the sidebar and paste it.")
    return _request(_url(cfg, path), cfg.token.strip(), payload)


def _get(cfg: CloudConfig, path: str, params: dict | None = None) -> dict:
    if not cfg.token.strip():
        raise CloudError("No WhatsApp access token is set.")
    url = _url(cfg, path)
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return _request(url, cfg.token.strip())


def _messages_path(cfg: CloudConfig) -> str:
    return f"{normalize_number(cfg.phone_number_id)}/messages"


# --------------------------------------------------------------------------- #
# Sending
# --------------------------------------------------------------------------- #

def send_text(cfg: CloudConfig, to: str, body: str, preview_url: bool = False) -> dict:
    """Send a free-form text. Raises CloudError with a human-readable reason."""
    number = normalize_number(to)
    if not valid_number(number):
        raise CloudError(f"'{to}' does not look like an international number. Use "
                         "the full number with country code, e.g. 919876543210.")
    text = (body or "").strip()
    if not text:
        raise CloudError("There is no message text to send.")
    if len(text) > MAX_TEXT_LEN:
        raise CloudError(f"That message is {len(text)} characters - WhatsApp allows "
                         f"{MAX_TEXT_LEN} per message. Split it.")
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": number,
        "type": "text",
        "text": {"preview_url": bool(preview_url), "body": text},
    }
    return _send(cfg, number, text, payload)


def send_template(cfg: CloudConfig, to: str, name: str, language: str = "en_US",
                  body_params: list | None = None, header_param: dict | None = None) -> dict:
    """Send a pre-approved template (the only way to start a conversation)."""
    number = normalize_number(to)
    if not valid_number(number):
        raise CloudError(f"'{to}' does not look like an international number.")
    components = []
    if header_param:
        components.append({"type": "header", "parameters": [header_param]})
    if body_params:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": str(p)} for p in body_params],
        })
    payload = {
        "messaging_product": "whatsapp",
        "to": number,
        "type": "template",
        "template": {
            "name": (name or "").strip(),
            "language": {"code": (language or "en_US").strip()},
        },
    }
    if components:
        payload["template"]["components"] = components
    preview = f"{(name or '').strip()} ({language}) " + " / ".join(
        str(p) for p in (body_params or []))
    return _send(cfg, number, preview.strip(), payload, kind="template")


def _send(cfg: CloudConfig, number: str, preview: str, payload: dict,
          kind: str = "text") -> dict:
    """POST one message and write the audit trail for it either way."""
    try:
        result = _post(cfg, _messages_path(cfg), payload)
    except CloudError as exc:
        record_outgoing(number, kind, preview, "failed", exc)
        raise
    record_outgoing(number, kind, preview, "sent", _wamid(result))
    return result


# --------------------------------------------------------------------------- #
# Outbound audit
# --------------------------------------------------------------------------- #

def _wamid(result) -> str:
    """The message id Meta assigns, when the reply carries one."""
    if not isinstance(result, dict):
        return ""
    messages = result.get("messages") or []
    first = messages[0] if isinstance(messages, list) and messages else {}
    return str(first.get("id", "")) if isinstance(first, dict) else ""


def record_outgoing(to: str, kind: str, body: str, status: str,
                    detail: str = "") -> dict:
    """Keep a trail of what JARVIS pushed through the business number.

    A channel that can reach any number has to answer "who did it message?"
    after the chat window is gone, so successes and failures both land on disk -
    bodies truncated, in the user's own folder, never in the project.
    """
    row = {
        "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ts": time.time(),
        "to": normalize_number(to),
        "kind": kind,
        "body": re.sub(r"\s+", " ", str(body or ""))[:200].strip(),
        "status": status,
    }
    if detail:
        row["detail"] = str(detail)[:200]
    rows = [r for r in _read_json(_outbox_path(), []) if isinstance(r, dict)]
    rows.append(row)
    _write_json(_outbox_path(), rows[-OUTBOX_KEEP:])
    return row


def outbox(limit: int = 20, number: str = "") -> list:
    """Most recent outbound rows, newest first."""
    rows = [r for r in _read_json(_outbox_path(), [])
            if isinstance(r, dict) and r.get("to")]
    if number:
        wanted = normalize_number(number)
        rows = [r for r in rows if r.get("to") == wanted]
    rows.sort(key=lambda r: r.get("ts") or 0, reverse=True)
    return rows[:limit]


def mark_read(cfg: CloudConfig, message_id: str, typing: bool = False) -> None:
    """Blue ticks + optional typing indicator; never worth failing a reply over."""
    if not message_id:
        return
    payload = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
    if typing:
        payload["typing_indicator"] = {"type": "text"}
    try:
        _post(cfg, _messages_path(cfg), payload)
    except CloudError:
        pass


def notify(text: str, cfg: CloudConfig | None = None) -> str:
    """Push a reminder/briefing to the configured numbers. Returns a short report."""
    cfg = cfg or active_config()
    if not cfg.ready:
        return ""
    numbers = [normalize_number(n) for n in (load_prefs().get("notify_to") or [])]
    numbers = [n for n in numbers if valid_number(n)]
    if not numbers:
        return ""
    sent, failed = 0, []
    for number in numbers:
        try:
            send_text(cfg, number, text)
            sent += 1
        except CloudError as exc:
            failed.append(f"{number}: {exc}")
    if not sent:
        return "WhatsApp push failed - " + "; ".join(failed)[:200]
    return f"Pushed to {sent} WhatsApp number(s)." + (
        " (" + "; ".join(failed)[:160] + ")" if failed else "")


# --------------------------------------------------------------------------- #
# Introspection (used by the setup panel)
# --------------------------------------------------------------------------- #

def test_connection(cfg: CloudConfig) -> str:
    """Read the phone number object - proves token + phone id are right."""
    data = _get(cfg, normalize_number(cfg.phone_number_id),
                {"fields": "display_phone_number,verified_name,quality_rating,"
                           "messaging_limit_tier,platform_type"})
    number = str(data.get("display_phone_number") or "").strip()
    name = str(data.get("verified_name") or "").strip()
    quality = str(data.get("quality_rating") or "").strip()
    tier = str(data.get("messaging_limit_tier") or "").strip()
    cfg.our_number = normalize_number(number)
    cfg.business_name = name or cfg.business_name
    bits = [f"Connected to WhatsApp as {name or 'this business'} ({number or 'number hidden'})"]
    if quality:
        bits.append(f"quality {quality}")
    if tier:
        bits.append(f"limit {tier.replace('_', ' ')}")
    return " - ".join(bits) + "."


def list_templates(cfg: CloudConfig) -> list:
    """Approved/pending templates of the business account."""
    if not cfg.waba_id.strip():
        return []
    try:
        data = _get(cfg, f"{normalize_number(cfg.waba_id)}/message_templates",
                    {"fields": "name,status,language,category", "limit": 100})
    except CloudError:
        return []
    rows = data.get("data") or []
    return [{
        "name": str(r.get("name", "")),
        "status": str(r.get("status", "")),
        "language": str(r.get("language", "")),
        "category": str(r.get("category", "")),
    } for r in rows if isinstance(r, dict) and r.get("name")]


def window_open(number: str) -> bool:
    """True while a free-form reply to this number is still allowed - i.e. they
    messaged the business within the last 24 hours."""
    number = normalize_number(number)
    stamp = 0.0
    for row in _load_inbox():
        if str(row.get("from", "")) != number or row.get("direction") == "out":
            continue
        try:
            stamp = max(stamp, float(row.get("ts") or 0))
        except (TypeError, ValueError):
            continue
    if not stamp:
        return False
    return datetime.fromtimestamp(stamp) + timedelta(hours=WINDOW_HOURS) > datetime.now()


# --------------------------------------------------------------------------- #
# Contact book - lets "message Ali" work without typing a number
# --------------------------------------------------------------------------- #

def contacts() -> list:
    rows = _read_json(_contacts_path(), [])
    return [r for r in rows if isinstance(r, dict) and r.get("name")]


def save_contact(name: str, number: str, note: str = "") -> str:
    name = (name or "").strip()
    number = normalize_number(number)
    if not name:
        return "Give the contact a name."
    if not valid_number(number):
        return f"'{number}' is not a valid international number - use country code " \
               "then the number, e.g. 919876543210."
    with _lock:
        rows = [r for r in contacts() if str(r.get("name", "")).lower() != name.lower()]
        rows.append({"name": name, "number": number, "note": (note or "").strip(),
                     "saved": datetime.now().strftime("%Y-%m-%d %H:%M")})
        rows.sort(key=lambda r: str(r.get("name", "")).lower())
        _write_json(_contacts_path(), rows)
    return f"Saved {name} ({number})."


def remove_contact(name: str) -> str:
    want = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    with _lock:
        rows = contacts()
        kept = [r for r in rows
                if re.sub(r"[^a-z0-9]", "", str(r.get("name", "")).lower()) != want]
        if len(kept) == len(rows):
            return f"No saved contact called '{name}'."
        _write_json(_contacts_path(), kept)
    return f"Removed {name} from the WhatsApp contact book."


def resolve(target: str) -> tuple:
    """Name or number -> (number, display name). Raises CloudError when unknown."""
    raw = (target or "").strip()
    if not raw:
        raise CloudError("Tell me who to send it to.")
    if valid_number(raw) and re.search(r"\d", raw) and not re.search(r"[a-zA-Z]", raw):
        return normalize_number(raw), normalize_number(raw)
    want = re.sub(r"[^a-z0-9]", "", raw.lower())
    rows = contacts()
    exact = partial = None
    for row in rows:
        got = re.sub(r"[^a-z0-9]", "", str(row.get("name", "")).lower())
        if not got:
            continue
        if got == want:
            exact = row
            break
        if want and (want in got or got in want) and partial is None:
            partial = row
    picked = exact or partial
    if not picked:
        names = ", ".join(str(r.get("name")) for r in rows[:12]) or "no one yet"
        raise CloudError(f"'{raw}' is not in the WhatsApp contact book (saved: {names}). "
                         "Give me the full international number, or save the contact first.")
    return normalize_number(picked.get("number", "")), str(picked.get("name", raw))


# --------------------------------------------------------------------------- #
# Inbound: storage + parsing
# --------------------------------------------------------------------------- #

def _load_inbox() -> list:
    rows = _read_json(_inbox_path(), [])
    return [r for r in rows if isinstance(r, dict) and r.get("id")]


def _write_inbox(rows: list) -> None:
    _write_json(_inbox_path(), rows[-INBOX_KEEP:])


def describe_message(msg: dict) -> str:
    """Human text for any inbound message type."""
    kind = str(msg.get("type", "text"))
    if kind == "text":
        return str((msg.get("text") or {}).get("body", "")).strip()
    if kind in ("image", "video", "document", "audio", "sticker"):
        caption = str((msg.get(kind) or {}).get("caption", "")).strip()
        label = {"image": "photo", "video": "video", "document": "document",
                 "audio": "voice note", "sticker": "sticker"}[kind]
        return f"[{label}]" + (f" {caption}" if caption else "")
    if kind == "location":
        loc = msg.get("location") or {}
        return f"[location {loc.get('latitude')},{loc.get('longitude')}]"
    if kind == "contacts":
        return "[a contact card]"
    if kind == "reaction":
        emoji = str((msg.get("reaction") or {}).get("emoji", ""))
        return f"[reacted {emoji}]"
    if kind == "button":
        return str((msg.get("button") or {}).get("text", "[button reply]"))
    if kind in ("interactive", "nfmreply"):
        reply = msg.get("interactive") or msg.get("nfmreply") or {}
        return str(reply.get("list_reply", {}).get("title")
                   or reply.get("button_reply", {}).get("title")
                   or reply.get("response_json") or "[form reply]")
    return f"[{kind} message]"


def parse_payload(payload: dict) -> list:
    """Every inbound message in a webhook payload, flattened and normalised."""
    out = []
    for entry in payload.get("entry") or []:
        for change in (entry.get("changes") or []):
            value = change.get("value") or {}
            if value.get("object") and value["object"] != "whatsapp_business_account":
                continue
            profiles = {}
            for contact in value.get("contacts") or []:
                number = normalize_number(contact.get("wa_id", ""))
                if number:
                    profiles[number] = str((contact.get("profile") or {}).get("name") or "")
            our_id = str((value.get("metadata") or {}).get("phone_number_id", ""))
            for msg in value.get("messages") or []:
                number = normalize_number(msg.get("from", ""))
                if not number or not msg.get("id"):
                    continue
                try:
                    ts = float(msg.get("timestamp") or 0)
                except (TypeError, ValueError):
                    ts = time.time()
                out.append({
                    "id": str(msg.get("id")),
                    "from": number,
                    "name": profiles.get(number, "") or number,
                    "type": str(msg.get("type", "text")),
                    "text": describe_message(msg)[:1500],
                    "ts": ts,
                    "at": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
                          if ts else datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "to_phone_id": our_id,
                    "direction": "in",
                })
    return out


def record_inbound(messages: list) -> list:
    """Store new messages (deduped by id). Returns the ones actually added."""
    if not messages:
        return []
    with _lock:
        rows = _load_inbox()
        known = {str(r.get("id")) for r in rows[-120:]}
        fresh = [m for m in messages if m.get("id") not in known]
        if not fresh:
            return []
        _write_inbox(rows + fresh)
    return fresh


def inbox(limit: int = 20, sender: str = "") -> list:
    rows = _load_inbox()
    if sender:
        needle = re.sub(r"[^a-z0-9]", "", sender.lower())
        rows = [r for r in rows
                if needle in re.sub(r"[^a-z0-9]", "", str(r.get("name", "")).lower())
                or needle in str(r.get("from", ""))]
    if not rows:
        return []
    return rows[-max(1, min(int(limit or 20), 100)):][::-1]


def clear_inbox() -> None:
    with _lock:
        _write_inbox([])


_events: list = []


def pop_events() -> list:
    """Inbound messages the UI has not shown yet (chat feed + spoken aloud)."""
    with _lock:
        out = list(_events)
        _events.clear()
    return out


def has_events() -> bool:
    """True while an inbound message waits to be shown - the heartbeat uses it
    to wake an idle page, otherwise nothing reruns until the user clicks."""
    with _lock:
        return bool(_events)


def _push_events(messages: list) -> None:
    with _lock:
        _events.extend(messages)


# --------------------------------------------------------------------------- #
# Auto-reply worker
# --------------------------------------------------------------------------- #

# app.py installs this: fn(text, sender_name, sender_number) -> reply text.
_reply_handler = None
_reply_error = ""
_queue: list = []
_worker: threading.Thread | None = None
_stop = threading.Event()
_stats = {"replied": 0, "received": 0, "last": ""}


def set_reply_handler(fn) -> None:
    global _reply_handler
    with _lock:
        _reply_handler = fn


def reply_status() -> str:
    with _lock:
        err, stats = _reply_error, dict(_stats)
    if err:
        return f"💬 WhatsApp auto-reply problem: {err}"
    if stats.get("received"):
        return (f"💬 Auto-reply: {stats['received']} message(s) in, "
                f"{stats['replied']} answered"
                + (f", last {stats['last']}" if stats.get("last") else "") + ".")
    return ""


def enqueue(messages: list) -> None:
    """Queue inbound messages for the auto-reply worker."""
    global _worker
    cfg = active_config()
    prefs = load_prefs()
    allowed = [normalize_number(n) for n in (prefs.get("allowed_senders") or [])]
    with _lock:
        for msg in messages:
            _stats["received"] = _stats.get("received", 0) + 1
            if not prefs.get("auto_reply") or _reply_handler is None:
                continue
            if not cfg.ready:
                continue
            if allowed and msg.get("from") not in allowed:
                continue
            if msg.get("from") == normalize_number(cfg.our_number or ""):
                continue          # never answer the business's own messages
            if msg.get("type") == "reaction":
                continue
            _queue.append(msg)
        if _queue and not (_worker and _worker.is_alive()):
            _stop.clear()
            _worker = threading.Thread(target=_reply_loop, name="jarvis-wa-reply",
                                       daemon=True)
            _worker.start()


def _reply_loop() -> None:
    global _reply_error
    while not _stop.is_set():
        with _lock:
            msg = _queue.pop(0) if _queue else None
            handler, cfg = _reply_handler, active_config()
        if msg is None:
            return
        try:
            mark_read(cfg, msg.get("id", ""), typing=True)
            answer = handler(msg.get("text", ""), msg.get("name", ""), msg.get("from", ""))
            answer = str(answer or "").strip()
            if not answer:
                continue
            for chunk in _split(answer):
                send_text(cfg, msg.get("from", ""), chunk)
            _write_inbox(_load_inbox() + [{
                "id": f"out-{msg.get('id', '')}-{int(time.time())}",
                "from": normalize_number(cfg.our_number or ""),
                "name": cfg.business_name or "JARVIS",
                "type": "text",
                "text": answer[:1500],
                "ts": time.time(),
                "at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "direction": "out",
            }])
            with _lock:
                _stats["replied"] = _stats.get("replied", 0) + 1
                _stats["last"] = datetime.now().strftime("%H:%M")
                _reply_error = ""
        except CloudError as exc:
            with _lock:
                _reply_error = str(exc)[:160]
        except Exception as exc:  # noqa: BLE001 - one bad message must not kill it
            with _lock:
                _reply_error = f"{type(exc).__name__}: {exc}"[:160]


def _split(text: str) -> list:
    """WhatsApp rejects >4096 chars. Break on line/sentence ends, and hard-cut
    any run that is still too long so nothing is silently dropped."""
    text = (text or "").strip()
    if len(text) <= MAX_TEXT_LEN:
        return [text] if text else []
    chunks: list = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for piece in re.split(r"(?<=[\n.!?])", text):
        while len(piece) > MAX_TEXT_LEN:
            flush()
            chunks.append(piece[:MAX_TEXT_LEN])
            piece = piece[MAX_TEXT_LEN:]
        if len(current) + len(piece) > MAX_TEXT_LEN:
            flush()
        current += piece
    flush()
    return chunks


def stop_reply_worker() -> None:
    _stop.set()


# --------------------------------------------------------------------------- #
# Webhook routes on this Streamlit server
# --------------------------------------------------------------------------- #

_installed = False
_last_webhook = {"at": "", "result": ""}


def _signature_ok(body: bytes, header: str, app_secret: str) -> bool:
    if not app_secret:
        return True                     # nothing to check against
    if not header.startswith("sha256="):
        return False
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, header.split("=", 1)[1].strip())


def webhook_path() -> str:
    return WEBHOOK_ROUTE


def local_port() -> int:
    """The port this Streamlit server listens on (for building a webhook URL)."""
    import gc

    try:
        from streamlit.web.server.starlette.starlette_server import UvicornServer

        for obj in gc.get_objects():
            if type(obj) is not UvicornServer:
                continue
            port = getattr(getattr(obj, "_server", None), "config", None)
            port = getattr(port, "port", 0)
            if port:
                return int(port)
    except Exception:  # noqa: BLE001
        pass
    try:
        from streamlit import config as st_config

        return int(st_config.get_option("server.port") or 8501)
    except Exception:  # noqa: BLE001
        return 8501


def local_webhook_url() -> str:
    return f"http://127.0.0.1:{local_port()}{WEBHOOK_ROUTE}"


def public_webhook_url() -> str:
    """Tunnel URL when one is running, else a URL the user configured."""
    base = tunnel_url() or load_prefs().get("last_public_url") \
        or os.environ.get("JARVIS_PUBLIC_URL", "").rstrip("/")
    return f"{base.rstrip('/')}{WEBHOOK_ROUTE}" if base else ""


def install_webhook() -> bool:
    """Register GET (verify) + POST (receive) on the live Starlette app."""
    global _installed
    if _installed:
        return True
    try:
        from starlette.responses import JSONResponse, PlainTextResponse
        from starlette.routing import Route

        import stop_signal

        app = stop_signal._live_starlette_app()
        if app is None:
            return False

        async def _verify(request):
            cfg = active_config()
            params = request.query_params
            mode = params.get("hub.mode", "")
            token = params.get("hub.verify_token", "")
            challenge = params.get("hub.challenge", "")
            if mode == "subscribe" and token and hmac.compare_digest(
                    token, cfg.verify_token or "jarvis-whatsapp"):
                _last_webhook.update({"at": datetime.now().strftime("%H:%M"),
                                      "result": "verified by Meta"})
                return PlainTextResponse(challenge)
            _last_webhook.update({"at": datetime.now().strftime("%H:%M"),
                                  "result": "verification refused (wrong verify token)"})
            return PlainTextResponse("verify token mismatch", status_code=403)

        async def _receive(request):
            cfg = active_config()
            body = await request.body()
            secret = cfg.app_secret.strip()
            if not _signature_ok(body, request.headers.get("x-hub-signature-256", ""),
                                 secret):
                _last_webhook.update({"at": datetime.now().strftime("%H:%M"),
                                      "result": "rejected: bad signature"})
                return PlainTextResponse("bad signature", status_code=401)
            if not secret:
                # No app secret means nothing can be signature-checked, and this
                # port also serves the LAN (the phone page). Only the loopback
                # test harness is trusted until Meta's deliveries can be proved.
                client = getattr(request.client, "host", "") or ""
                if client not in ("127.0.0.1", "::1", "localhost"):
                    _last_webhook.update({
                        "at": datetime.now().strftime("%H:%M"),
                        "result": "refused: unauthenticated delivery from "
                                  f"{client} - set the App secret",
                    })
                    return PlainTextResponse(
                        "app secret required before accepting external deliveries",
                        status_code=403)
            try:
                payload = json.loads(body.decode("utf-8", "replace") or "{}")
            except ValueError:
                return PlainTextResponse("bad json", status_code=400)
            fresh = record_inbound(parse_payload(payload))
            _last_webhook.update({
                "at": datetime.now().strftime("%H:%M"),
                "result": f"{len(fresh)} new message(s)" if fresh else "status/echo only",
            })
            if fresh:
                _push_events(fresh)
                enqueue(fresh)
            # 200 immediately: Meta retries anything else and would duplicate.
            return JSONResponse({"ok": True})

        existing = {getattr(r, "path", None) for r in app.routes}
        if WEBHOOK_ROUTE not in existing:
            app.routes.insert(0, Route(WEBHOOK_ROUTE, _verify, methods=["GET"]))
            app.routes.insert(1, Route(WEBHOOK_ROUTE, _receive, methods=["POST"]))
        _installed = True
        return True
    except Exception:  # noqa: BLE001
        return False


def webhook_status() -> str:
    if not _last_webhook["at"]:
        return ""
    return f"Webhook last hit {_last_webhook['at']} - {_last_webhook['result']}."


# --------------------------------------------------------------------------- #
# Public URL: a quick tunnel so Meta can reach this laptop
# --------------------------------------------------------------------------- #

_tunnel = {"proc": None, "url": "", "error": "", "binary": ""}


def find_tunnel_binary() -> str:
    home = followups.data_dir() / TUNNEL_DIR_NAME
    for cand in (os.path.join(str(home), "cloudflared.exe"),
                 os.path.join(str(home), "ngrok.exe"),
                 shutil.which("cloudflared") or "",
                 shutil.which("ngrok") or ""):
        if cand and os.path.exists(cand):
            return cand
    return ""


def download_cloudflared() -> str:
    """Fetch the official cloudflared binary into ~/.jarvis/bin (explicit action)."""
    target = followups.data_dir() / TUNNEL_DIR_NAME / "cloudflared.exe"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    try:
        req = urllib.request.Request(CLOUDFLARED_URL, headers={"User-Agent": "JARVIS/1.0"})
        with urllib.request.urlopen(req, timeout=180) as resp, open(tmp, "wb") as fh:
            shutil.copyfileobj(resp, fh, 1024 * 256)
        os.replace(tmp, target)
    except (urllib.error.URLError, OSError) as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise CloudError(f"Could not download cloudflared ({exc}).") from None
    return str(target)


_URL_RE = re.compile(r"https://[a-z0-9\-]+\.(?:trycloudflare\.com|ngrok(?:-free)?\.app|ngrok\.io)")


def start_tunnel() -> str:
    """Expose the local server; returns the public HTTPS base URL."""
    with _lock:
        if _tunnel["proc"] and _tunnel["proc"].poll() is None and _tunnel["url"]:
            return _tunnel["url"]
        binary = find_tunnel_binary()
        if not binary:
            raise CloudError("No tunnel tool found. Install Cloudflare's `cloudflared` "
                             "(or `ngrok`), or host JARVIS somewhere with a public URL.")
        name = os.path.basename(binary).lower()
        port = local_port()
        if "cloudflared" in name:
            args = [binary, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"]
        else:
            args = [binary, "http", str(port), "--log", "stdout", "--log-format", "logfmt"]
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, text=True,
                                encoding="utf-8", errors="replace", bufsize=1)
        _tunnel.update({"proc": proc, "url": "", "error": "", "binary": binary})

        def _watch(process, is_ngrok: bool) -> None:
            deadline = time.monotonic() + 60
            try:
                for line in process.stdout:            # blocks until the tunnel dies
                    if time.monotonic() > deadline and not _tunnel["url"]:
                        _tunnel["error"] = "The tunnel did not print a URL in 60 seconds."
                        deadline = time.monotonic() + 3600
                    found = _URL_RE.search(line or "")
                    if found and not _tunnel["url"]:
                        _tunnel["url"] = found.group(0).rstrip("/")
                        save_prefs({"last_public_url": _tunnel["url"]})
                    if is_ngrok and "authentication failed" in (line or "").lower():
                        _tunnel["error"] = "ngrok needs an authtoken: run `ngrok config add-authtoken <token>`."
                    if "ERR" in (line or "") and "cloudflared" in (line or ""):
                        _tunnel["error"] = (line or "").strip()[:160]
            except (OSError, ValueError):
                pass
            finally:
                if not _tunnel["url"]:
                    _tunnel["error"] = _tunnel["error"] or "The tunnel closed before giving a URL."

        threading.Thread(target=_watch, args=(proc, "ngrok" in name),
                         name="jarvis-wa-tunnel", daemon=True).start()

        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if _tunnel["url"]:
                return _tunnel["url"]
            if proc.poll() is not None and not _tunnel["url"]:
                break
            time.sleep(0.5)
        if _tunnel["url"]:
            return _tunnel["url"]
        raise CloudError(_tunnel["error"] or "The tunnel did not start - check that "
                         "cloudflared/ngrok is allowed through the firewall.")


def stop_tunnel() -> None:
    with _lock:
        proc = _tunnel.get("proc")
        _tunnel.update({"url": "", "error": ""})
    if proc and proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass


def tunnel_url() -> str:
    with _lock:
        proc = _tunnel.get("proc")
        if proc is not None and proc.poll() is not None:
            _tunnel.update({"url": "", "proc": None})
        return _tunnel.get("url", "")


def tunnel_error() -> str:
    with _lock:
        return _tunnel.get("error", "")


# --------------------------------------------------------------------------- #
# Agent tools
# --------------------------------------------------------------------------- #

def make_cloud_tools(cfg: CloudConfig) -> list:
    """Tools bound to one config, exactly like the email tools."""

    @tool
    def whatsapp_business_send(contact: str, message: str) -> str:
        """Send a WhatsApp message through the official Meta Cloud API to a saved
        contact NAME or an international NUMBER (country code, digits only, e.g.
        919876543210). Use for 'send a whatsapp to Ali', 'message 9198... saying
        the report is ready'. Only works inside the 24-hour window the recipient
        opened by messaging the business first."""
        number = ""
        try:
            number, name = resolve(contact)
            result = send_text(cfg, number, (message or "").strip())
        except CloudError as exc:
            note = ""
            if number and not window_open(number):
                note = (" They have not messaged the business in the last 24 hours, so "
                        "free-form text is refused - use whatsapp_business_template.")
            return f"I could not send that WhatsApp: {exc}{note}"
        wamid = _wamid(result)
        return f"Sent on WhatsApp to {name} (+{number})." + (f" [id {wamid}]" if wamid else "")

    @tool
    def whatsapp_business_template(contact: str, template: str, params: str = "",
                                   language: str = "en_US") -> str:
        """Send a pre-approved WhatsApp TEMPLATE to a contact name or number.
        This is the only way to start a conversation with someone who has not
        messaged the business in the last 24 hours. `params` is a comma-separated
        list of the template's {{1}}, {{2}}... values in order. Use for 'send the
        appointment reminder template to Ali'."""
        try:
            number, name = resolve(contact)
            values = [p.strip() for p in re.split(r"\s*,\s*", params or "") if p.strip()]
            result = send_template(cfg, number, template.strip(), language, values or None)
        except CloudError as exc:
            return f"The template did not go out: {exc}"
        wamid = _wamid(result)
        return (f"Template '{template}' sent to {name} (+{number}) on WhatsApp."
                + (f" [id {wamid}]" if wamid else ""))

    @tool
    def whatsapp_business_broadcast(message: str, recipients: str = "all",
                                    template: str = "") -> str:
        """Broadcast one WhatsApp message to several people at once. `recipients`
        is 'all' for the whole contact book, or comma-separated names/numbers.
        With `template` it sends that approved template instead of free text (use
        a template for people who have not messaged the business in 24 hours).
        Use for 'tell everyone on whatsapp the clinic is closed tomorrow'."""
        rows = contacts()
        if not rows:
            return "The WhatsApp contact book is empty - save contacts first."
        wanted = [r.strip() for r in re.split(r"\s*,\s*", recipients or "") if r.strip()]
        if not wanted or wanted[0].lower() == "all":
            targets = [(str(r.get("number", "")), str(r.get("name", ""))) for r in rows]
        else:
            targets = []
            for item in wanted:
                try:
                    number, name = resolve(item)
                    targets.append((number, name))
                except CloudError as exc:
                    targets.append(("", str(exc)))
        body = (message or "").strip()
        if not body and not template:
            return "Tell me what to send."
        sent, failed = [], []
        for number, name in targets:
            if not number:
                failed.append(name)
                continue
            try:
                if template:
                    send_template(cfg, number, template, "en_US")
                else:
                    send_text(cfg, number, body)
                sent.append(name or number)
            except CloudError as exc:
                failed.append(f"{name or number} ({str(exc)[:70]})")
            time.sleep(0.4)          # stay well inside Meta's rate limit
        report = f"Broadcast to {len(sent)} of {len(targets)}: " + ", ".join(sent[:12])
        if failed:
            report += "\nFailed: " + "; ".join(failed[:8])
        return report

    @tool
    def whatsapp_business_inbox(limit: int = 10, contact: str = "") -> str:
        """Read the WhatsApp messages people have sent TO the business number
        (captured by the webhook). `contact` narrows it to one sender. Use for
        'who messaged us on whatsapp', 'read the last whatsapp replies'."""
        rows = inbox(limit=limit, sender=contact)
        if not rows:
            return ("No WhatsApp messages have arrived at the business number yet"
                    + (" from that contact" if contact else "") + ".")
        lines = []
        for row in rows:
            who = str(row.get("name") or row.get("from"))
            arrow = "You" if row.get("direction") == "out" else who
            lines.append(f"- {row.get('at', '?')} {arrow}: {str(row.get('text', ''))[:300]}")
        return f"Latest WhatsApp messages ({len(rows)}):\n" + "\n".join(lines)

    @tool
    def whatsapp_business_save_contact(name: str, number: str, note: str = "") -> str:
        """Save a name + international number in the WhatsApp contact book so
        messages can be sent by name later. Use for 'save Ali's whatsapp number
        as 919876543210'."""
        return save_contact(name, number, note)

    @tool
    def whatsapp_business_contacts() -> str:
        """List the WhatsApp contact book, and the approved message templates of
        the business account. Use for 'who can I whatsapp', 'what templates do I
        have'."""
        rows = contacts()
        out = ["Contact book:"]
        if rows:
            out += [f"- {r.get('name')} (+{r.get('number')})"
                    + (f" — {r.get('note')}" if r.get("note") else "") for r in rows]
        else:
            out.append("(empty - save someone with whatsapp_business_save_contact)")
        templates = list_templates(cfg)
        if templates:
            out.append("\nApproved templates:")
            out += [f"- {t['name']} [{t.get('language')}] {t.get('status')}"
                    f" ({t.get('category')})" for t in templates[:20]]
        return "\n".join(out)

    return [whatsapp_business_send, whatsapp_business_template,
            whatsapp_business_broadcast, whatsapp_business_inbox,
            whatsapp_business_save_contact, whatsapp_business_contacts]


CLOUD_NOTES = (
    "\n\nWHATSAPP CLOUD API (business number): whatsapp_business_send(contact, "
    "message) sends to a saved contact NAME or an international number; "
    "whatsapp_business_template(contact, template, params) sends an approved "
    "template - the ONLY way to reach someone who has not messaged the business "
    "in the last 24 hours; whatsapp_business_broadcast(message, recipients, "
    "template) sends to several people ('all' or a comma-separated list); "
    "whatsapp_business_inbox() reads what people sent to the business; "
    "whatsapp_business_save_contact(name, number) and "
    "whatsapp_business_contacts() manage the contact book. Numbers must include "
    "the country code with no '+' and no spaces. If Meta refuses a send, relay "
    "the reason plainly - never claim a message was sent when the tool reports a "
    "failure, and always confirm before broadcasting to more than two people."
)
