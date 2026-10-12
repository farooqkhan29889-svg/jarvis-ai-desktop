"""Scratch verification for whatsapp_cloud.py - run then delete."""
import hashlib
import hmac
import io
import json
import os
import sys
import tempfile
import time

TMP = tempfile.mkdtemp(prefix="jarvis-wa-test-")
os.environ["JARVIS_HOME"] = TMP
os.environ.pop("JARVIS_WA_TOKEN", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import whatsapp_cloud as wc

failures = []


def check(label, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f"\n   got: {got!r}\n  want: {want!r}"))
    if not ok:
        failures.append(label)


def check_true(label, cond):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


# ---- numbers ----
check("normalize strips +/spaces/dashes", wc.normalize_number("+91 98765-43210"), "919876543210")
check("normalize strips leading 00", wc.normalize_number("00919876543210"), "919876543210")
check_true("valid number", wc.valid_number("919876543210"))
check_true("rejects short number", not wc.valid_number("12345"))

# ---- contacts ----
print(wc.save_contact("Ali Khan", "+91 98765 43210", "supplier"))
num, name = wc.resolve("ali")
check("resolve partial name -> number", (num, name), ("919876543210", "Ali Khan"))
check("resolve raw number", wc.resolve("919876543210"), ("919876543210", "919876543210"))
try:
    wc.resolve("nobody")
    check_true("unknown contact raises", False)
except wc.CloudError as exc:
    check_true("unknown contact raises with a helpful list", "contact book" in str(exc))
print(wc.save_contact("Ali Khan", "+91 90000 00000"))
check("re-saving a name replaces it", len(wc.contacts()), 1)

# ---- webhook payload ----
NOW = str(int(time.time()))
OLD = str(int(time.time()) - 48 * 3600)
PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "111", "changes": [{
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {"display_phone_number": "15551234567",
                             "phone_number_id": "999888777"},
                "contacts": [{"profile": {"name": "Farooq"}, "wa_id": "919876543210"}],
                "messages": [{
                    "from": "919876543210", "id": "wamid.AAA", "timestamp": NOW,
                    "text": {"body": "is the clinic open tomorrow?"}, "type": "text",
                }, {
                    "from": "919876543210", "id": "wamid.BBB", "timestamp": NOW,
                    "type": "image", "image": {"caption": "report", "mime_type": "image/jpeg"},
                }],
            },
            "field": "messages",
        }],
    }],
}
parsed = wc.parse_payload(PAYLOAD)
check("parses both messages", len(parsed), 2)
check("text body extracted", parsed[0]["text"], "is the clinic open tomorrow?")
check("sender profile name", parsed[0]["name"], "Farooq")
check("media described", parsed[1]["text"], "[photo] report")
check("our phone id captured", parsed[0]["to_phone_id"], "999888777")

fresh = wc.record_inbound(parsed)
check("first record stores all", len(fresh), 2)
check("duplicate ids ignored", wc.record_inbound(wc.parse_payload(PAYLOAD)), [])
check("inbox newest first", wc.inbox(10)[0]["id"], "wamid.BBB")
check_true("24h window open after inbound", wc.window_open("919876543210"))
check_true("window closed for a stranger", not wc.window_open("911111111111"))

STALE = {"entry": [{"changes": [{"value": {
    "object": "whatsapp_business_account",
    "metadata": {"phone_number_id": "999888777"},
    "messages": [{"from": "915550000000", "id": "wamid.OLD", "timestamp": OLD,
                  "type": "text", "text": {"body": "two days ago"}}]}}]}]}
wc.record_inbound(wc.parse_payload(STALE))
check_true("window closed once 24h passed", not wc.window_open("915550000000"))

# status callbacks carry no messages -> nothing stored
STATUS_ONLY = {"entry": [{"changes": [{"value": {
    "object": "whatsapp_business_account", "metadata": {"phone_number_id": "999888777"},
    "statuses": [{"id": "wamid.CCC", "status": "delivered", "recipient_id": "919876543210"}],
}}]}]}
check("status callback yields no messages", wc.parse_payload(STATUS_ONLY), [])

# ---- signature ----
SECRET = "topsecret"
body = json.dumps(PAYLOAD).encode()
good = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
check_true("accepts a valid signature", wc._signature_ok(body, good, SECRET))
check_true("rejects a wrong signature", not wc._signature_ok(body, "sha256=" + "0" * 64, SECRET))
check_true("rejects a missing signature", not wc._signature_ok(body, "", SECRET))
check_true("no secret configured -> allowed", wc._signature_ok(body, "", ""))

# ---- error mapping ----
check("131047 -> 24h window hint",
      "24-hour" in wc._friendly({"code": 131047, "message": "Re-engagement message"}), True)
check("190 -> token hint",
      "access token" in wc._friendly({"code": 190, "message": "Invalid OAuth access token"}), True)
check("unknown code passes Meta's text through",
      wc._friendly({"code": 42, "message": "weird"}), "Meta refused the call: weird (code 42).")

# ---- outgoing request shape (no network: capture the request) ----
captured = {}


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps({"messaging_product": "whatsapp", "contacts": [{"wa_id": "919876543210"}],
                           "messages": [{"id": "wamid.SENT"}]}).encode()


def fake_urlopen(req, timeout=None):
    captured["url"] = req.full_url
    captured["body"] = json.loads(req.data.decode() if req.data else "{}")
    captured["headers"] = dict(req.header_items())
    return _Resp()


wc.urllib.request.urlopen = fake_urlopen
CFG = wc.CloudConfig(token="EAAtoken", phone_number_id="999888777", waba_id="123456",
                     app_secret=SECRET, api_version="v25.0")
wc.send_text(CFG, "+91 98765 43210", "the clinic is open till 8pm")
check("posts to the phone number's /messages",
      captured["url"], "https://graph.facebook.com/v25.0/999888777/messages")
check("payload is a text message",
      captured["body"], {"messaging_product": "whatsapp", "recipient_type": "individual",
                         "to": "919876543210", "type": "text",
                         "text": {"preview_url": False, "body": "the clinic is open till 8pm"}})
check("bearer token header", captured["headers"].get("Authorization"), "Bearer EAAtoken")

wc.send_template(CFG, "919876543210", "appointment_reminder", "en_US", ["Ali", "6pm"])
check("template payload", captured["body"]["template"],
      {"name": "appointment_reminder", "language": {"code": "en_US"},
       "components": [{"type": "body", "parameters": [
           {"type": "text", "text": "Ali"}, {"type": "text", "text": "6pm"}]}]})

try:
    wc.send_text(CFG, "12345", "hi")
    check_true("rejects a bad number before calling Meta", False)
except wc.CloudError as exc:
    check_true("rejects a bad number before calling Meta", "international number" in str(exc))

# ---- outbound audit trail ----
rows = wc.outbox()
check("both sends are written down", [r["status"] for r in rows], ["sent", "sent"])
check("newest first", rows[0]["kind"], "template")
check("template row names the template", "appointment_reminder" in rows[0]["body"], True)
check("message id kept for read-back", rows[0]["detail"], "wamid.SENT")
check("text row keeps the body", rows[1]["body"], "the clinic is open till 8pm")
check("filter by number", len(wc.outbox(number="+91 98765 43210")), 2)


def failing_urlopen(req, timeout=None):
    raise wc.urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(
        json.dumps({"error": {"message": "Error validating access token",
                              "type": "OAuthException", "code": 190}}).encode()))


wc.urllib.request.urlopen = failing_urlopen
try:
    wc.send_text(CFG, "919876543210", "this one fails")
    check_true("a rejected send still raises", False)
except wc.CloudError:
    check_true("a rejected send still raises", True)
bad = wc.outbox()[0]
check("a rejected send is written down too", (bad["status"], bad["kind"]), ("failed", "text"))
check_true("it keeps Meta's reason", bool(bad["detail"]))
wc.urllib.request.urlopen = fake_urlopen

chunks = wc._split("word " * 2000)
check_true("long text is split into sendable chunks",
           bool(chunks) and all(len(c) <= wc.MAX_TEXT_LEN for c in chunks)
           and sum(len(c) for c in chunks) > 9000)
check("short text passes through", wc._split("hello"), ["hello"])

# ---- webhook routes over a real Starlette app ----
from starlette.applications import Starlette
from starlette.testclient import TestClient

import stop_signal

app = Starlette()
stop_signal._live_starlette_app = lambda: app
wc._installed = False
wc.set_runtime_config(CFG)
check_true("webhook routes installed", wc.install_webhook())
client = TestClient(app)

r = client.get(wc.WEBHOOK_ROUTE, params={"hub.mode": "subscribe",
                                          "hub.verify_token": CFG.verify_token,
                                          "hub.challenge": "1234"})
check("verify handshake echoes the challenge", (r.status_code, r.text), (200, "1234"))
r = client.get(wc.WEBHOOK_ROUTE, params={"hub.mode": "subscribe",
                                          "hub.verify_token": "wrong",
                                          "hub.challenge": "1234"})
check("wrong verify token refused", r.status_code, 403)

r = client.post(wc.WEBHOOK_ROUTE, content=body, headers={"X-Hub-Signature-256": good})
check("signed POST accepted", (r.status_code, r.json()), (200, {"ok": True}))
r = client.post(wc.WEBHOOK_ROUTE, content=body, headers={"X-Hub-Signature-256": "sha256=deadbeef"})
check("unsigned/bad POST rejected", r.status_code, 401)
r = client.post(wc.WEBHOOK_ROUTE, content=b"not json", headers={"X-Hub-Signature-256": "x"})
check("garbage body rejected without a 500", r.status_code, 401)

# ---- a webhook with no app secret is unreachable from outside the PC ----
NOSCRT = wc.CloudConfig(token="EAAtoken", phone_number_id="999888777",
                        waba_id="123456", verify_token=CFG.verify_token,
                        api_version="v25.0")
wc.set_runtime_config(NOSCRT)
far = TestClient(app, client=("203.0.113.9", 1234))
near = TestClient(app, client=("127.0.0.1", 54321))
r = far.post(wc.WEBHOOK_ROUTE, content=body, headers={"X-Hub-Signature-256": good})
check_true("an unverifiable remote delivery is refused", r.status_code == 403)
check_true("the refusal says why", "app secret" in r.text.lower())
r = near.post(wc.WEBHOOK_ROUTE, content=body)
check("loopback testing still works without a secret", r.status_code, 200)
wc.set_runtime_config(CFG)
r = far.post(wc.WEBHOOK_ROUTE, content=body, headers={"X-Hub-Signature-256": good})
check("with a secret set, a signed delivery from anywhere is accepted", r.status_code, 200)

# ---- auto-reply worker ----
replies = []
wc.set_reply_handler(lambda text, name, number: replies.append((name, text)) or "Yes, 9 to 8.")
sent = []
wc.send_text = lambda cfg, to, text, preview_url=False: sent.append((to, text)) or {}
wc.mark_read = lambda cfg, mid, typing=False: None
wc.save_prefs({"auto_reply": True})
new = wc.parse_payload({**PAYLOAD, "entry": [{**PAYLOAD["entry"][0], "changes": [
    {**PAYLOAD["entry"][0]["changes"][0], "value": {
        **PAYLOAD["entry"][0]["changes"][0]["value"],
        "messages": [{"from": "919876543210", "id": "wamid.NEW",
                      "timestamp": "1760009999", "type": "text",
                      "text": {"body": "are you open?"}}]}}]}]})
wc._push_events(new)
check("UI event queue gets the message", [m["id"] for m in wc.pop_events()], ["wamid.NEW"])
wc.enqueue(new)
for _ in range(100):
    if replies and sent:
        break
    import time as _t
    _t.sleep(0.1)
check("the agent handler saw the message", replies, [("Farooq", "are you open?")])
check("the reply was sent back to the sender", sent, [("919876543210", "Yes, 9 to 8.")])
check_true("auto-reply counted", wc.reply_status().startswith("💬 Auto-reply: 1 message(s) in, 1 answered"))

# a message from our own number must never be answered
wc.save_prefs({"allowed_senders": ["919876543210"]})
own = [{"id": "wamid.OWN", "from": CFG.our_number or "919876543210", "name": "us",
        "type": "text", "text": "echo", "ts": 1.0, "at": "now", "direction": "in"}]
CFG.our_number = "919876543210"
wc.enqueue(own)
import time as _t
_t.sleep(0.6)
check("never answers our own number", len(sent), 1)

wc.save_prefs({"allowed_senders": ["910000000000"]})
wc.enqueue([{"id": "wamid.OTHER", "from": "919876543210", "name": "Farooq", "type": "text",
             "text": "hello?", "ts": 2.0, "at": "now", "direction": "in"}])
_t.sleep(0.6)
check("allow-list blocks other senders", len(sent), 1)

print("\n" + ("ALL CHECKS PASSED" if not failures else f"{len(failures)} FAILURE(S): {failures}"))
sys.exit(1 if failures else 0)
