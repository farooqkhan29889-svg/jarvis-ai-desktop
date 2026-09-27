"""Read-only email access for J.A.R.V.I.S. over IMAP (stdlib only).

Deliberate limits:
- Strictly READ-ONLY. The mailbox is selected with readonly=True and messages are
  fetched with BODY.PEEK, so nothing is ever marked seen, moved or deleted.
- JARVIS cannot send mail from here by design.
- A credential dict is passed into every call and closed over by the tools, so
  nothing is stored in process-global state where another viewer of a hosted
  deployment could read it.
- Search terms are applied to results in Python, never interpolated into an
  IMAP command.
"""

from __future__ import annotations

import email as email_lib
import email.header
import html
import imaplib
import os
import re
import socket
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

from langchain_core.tools import tool

PROVIDERS = {
    "gmail.com": ("imap.gmail.com", 993),
    "googlemail.com": ("imap.gmail.com", 993),
    "outlook.com": ("outlook.office365.com", 993),
    "hotmail.com": ("outlook.office365.com", 993),
    "live.com": ("outlook.office365.com", 993),
    "msn.com": ("outlook.office365.com", 993),
    "yahoo.com": ("imap.mail.yahoo.com", 993),
    "icloud.com": ("imap.mail.me.com", 993),
    "me.com": ("imap.mail.me.com", 993),
    "zoho.com": ("imap.zoho.com", 993),
}

MAX_BODY = 900


@dataclass(frozen=True)
class EmailConfig:
    address: str
    password: str
    host: str = ""
    port: int = 0

    @property
    def ready(self) -> bool:
        return bool(self.address.strip() and self.password.strip())

    def server(self) -> tuple:
        if self.host.strip():
            return self.host.strip(), self.port or 993
        domain = self.address.strip().split("@")[-1].lower()
        if domain in PROVIDERS:
            host, port = PROVIDERS[domain]
            return host, self.port or port
        if domain:
            return f"imap.{domain}", self.port or 993
        return "", 993

    def masked(self) -> str:
        """Safe to display: never reveals the password."""
        return self.address.strip() or "(not set)"


def from_env() -> EmailConfig:
    """Config from .env / environment, for people who prefer not to type it."""
    return EmailConfig(
        address=os.environ.get("JARVIS_EMAIL_USER", ""),
        password=os.environ.get("JARVIS_EMAIL_PASSWORD", ""),
        host=os.environ.get("JARVIS_EMAIL_HOST", ""),
        port=int(os.environ.get("JARVIS_EMAIL_PORT") or 0),
    )


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #


def _decode(value) -> str:
    if not value:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    try:
        parts = email.header.decode_header(value)
        out = "".join(
            txt.decode(enc or "utf-8", "replace") if isinstance(txt, bytes) else txt
            for txt, enc in parts
        )
    except Exception:  # noqa: BLE001
        out = value
    return re.sub(r"\s+", " ", out).strip()


def _snippet(msg) -> str:
    """Plain-text preview; HTML is stripped and the richest part wins."""
    try:
        parts = list(msg.walk()) if msg.is_multipart() else [msg]
        text = ""
        for part in parts:
            if part.get_content_maintype() != "text":
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                body = part.get_payload(decode=True).decode(charset, "replace")
            except (LookupError, AttributeError, TypeError):
                continue
            if part.get_content_subtype() == "html":
                body = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", body)
                body = re.sub(r"(?s)<[^>]+>", " ", body)
                body = html.unescape(body)
            body = re.sub(r"[ \t]+", " ", body)
            body = "\n".join(ln.strip() for ln in body.splitlines() if ln.strip())
            if len(body) > len(text):
                text = body
        return text[:MAX_BODY].strip()
    except Exception:  # noqa: BLE001
        return ""


# --------------------------------------------------------------------------- #
# IMAP access
# --------------------------------------------------------------------------- #


def _connect(cfg: EmailConfig):
    host, port = cfg.server()
    if not host:
        raise ValueError("No email server is configured.")
    try:
        conn = imaplib.IMAP4_SSL(host, port, timeout=25)
    except OSError as exc:
        raise ConnectionError(
            f"Cannot reach the mail server {host} ({exc}). "
            "Check the email address, or set the IMAP host manually."
        ) from exc
    try:
        conn.login(cfg.address.strip(), cfg.password)
    except imaplib.IMAP4.error as exc:
        raise ConnectionError(
            f"{host} refused the sign-in ({exc}). Gmail, Outlook and Yahoo need an "
            "*app password*, not the ordinary login password."
        ) from exc
    return conn


def fetch_messages(cfg: EmailConfig, count: int = 10, unread_only: bool = False,
                   contains: str = "") -> list:
    """Read the newest INBOX messages without altering them."""
    count = max(1, min(int(count or 10), 25))
    conn = _connect(cfg)
    try:
        conn.select("INBOX", readonly=True)
        criterion = "UNSEEN" if unread_only else "ALL"
        status, data = conn.search(None, criterion)
        if status != "OK":
            raise RuntimeError(f"The mail server rejected the search ({status}).")
        ids = data[0].split()
        if not ids:
            return []
        status, unseen_data = conn.search(None, "UNSEEN")
        unseen = set(unseen_data[0].split()) if status == "OK" else set()
        out = []
        for num in ids[-count:][::-1]:  # newest first
            status, fetched = conn.fetch(num, "(BODY.PEEK[])")
            if status != "OK" or not fetched:
                continue
            raw = next((p[1] for p in fetched if isinstance(p, tuple) and len(p) > 1), None)
            if raw is None:
                continue
            msg = email_lib.message_from_bytes(raw)
            try:
                when = parsedate_to_datetime(msg.get("Date"))
            except (TypeError, ValueError):
                when = None
            out.append({
                "date": when.strftime("%Y-%m-%d %H:%M") if when else _decode(msg.get("Date")),
                "from": _decode(msg.get("From")),
                "subject": _decode(msg.get("Subject")) or "(no subject)",
                "unread": num in unseen,
                "snippet": _snippet(msg),
            })
        if contains:
            needle = contains.lower()
            out = [m for m in out
                   if needle in m["subject"].lower() or needle in m["from"].lower()
                   or needle in m["snippet"].lower()]
        return out
    finally:
        _logout(conn)


def unread_count(cfg: EmailConfig) -> int:
    conn = _connect(cfg)
    try:
        conn.select("INBOX", readonly=True)
        status, data = conn.search(None, "UNSEEN")
        if status != "OK":
            raise RuntimeError("Could not read the mailbox.")
        return len(data[0].split())
    finally:
        _logout(conn)


def test_connection(cfg: EmailConfig) -> str:
    """Log in and report the mailbox size - used by the UI to confirm credentials."""
    host, _port = cfg.server()
    conn = _connect(cfg)
    try:
        conn.select("INBOX", readonly=True)
        status, data = conn.search(None, "ALL")
        total = len(data[0].split()) if status == "OK" else 0
        return f"Connected to {host} as {cfg.masked()} - {total} message(s) in INBOX."
    finally:
        _logout(conn)


def _logout(conn) -> None:
    try:
        conn.logout()
    except Exception:  # noqa: BLE001
        pass


def _format(messages: list) -> str:
    lines = []
    for m in messages:
        flag = "NEW  " if m["unread"] else "read "
        lines.append(f"- {flag}{m['date']} | {m['from']} | {m['subject']}")
        if m["snippet"]:
            lines.append(f"      {m['snippet'][:280]}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Agent tools (bound to one session's credentials)
# --------------------------------------------------------------------------- #


def make_email_tools(cfg: EmailConfig) -> list:
    """Build the read-only email tools for a specific account."""

    @tool
    def check_email(count: int = 8, unread_only: bool = True, contains: str = "") -> str:
        """Read the user's newest INBOX emails (view only - nothing is marked read).
        unread_only=True limits to unseen mail; `contains` filters subject, sender
        and body text. Use for 'check my email', 'any new mail from Ali?'."""
        try:
            messages = fetch_messages(cfg, count=count, unread_only=unread_only, contains=contains)
        except imaplib.IMAP4.error as exc:
            return ("Your mail server refused the login. Gmail, Outlook and Yahoo need an "
                    f"APP PASSWORD (not your normal password), with 2-step verification on. ({exc})")
        except (socket.timeout, TimeoutError):
            return "The mail server took too long to answer - check the internet connection."
        except (OSError, ValueError) as exc:
            return f"Could not reach the mail server: {exc}"
        if not messages:
            if unread_only and not contains:
                return "You have no unread email right now."
            return "No messages matched that search."
        head = f"{len(messages)} message(s)"
        if contains:
            head += f" matching '{contains}'"
        return head + ":\n" + _format(messages)

    @tool
    def count_unread_email() -> str:
        """Report how many unread emails are waiting in the user's INBOX."""
        try:
            n = unread_count(cfg)
        except imaplib.IMAP4.error as exc:
            return f"Could not read the mailbox: {exc}"
        except (OSError, socket.timeout) as exc:
            return f"Could not reach the mail server: {exc}"
        return f"You have {n} unread email(s)." if n else "No unread email. Your inbox is clear."

    return [check_email, count_unread_email]


EMAIL_NOTES = (
    "\n\nEMAIL: check_email and count_unread_email read the user's INBOX in view-only "
    "mode. Use them for 'check my email' or 'any new mail from the supplier?'. They "
    "can only read - never send, delete or mark messages - so say so plainly if asked. "
    "Summarise what matters instead of dumping whole messages."
)
