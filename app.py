"""J.A.R.V.I.S. - a JARVIS-style AI desktop assistant.

Streamlit front-end for the Groq/LangChain agent defined in agent.py.
Run with:  streamlit run app.py
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import time
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components
from langchain_core.messages import AIMessage, HumanMessage
from streamlit_mic_recorder import mic_recorder

from agent import (
    DEFAULT_MODEL,
    build_agent,
    list_chat_models,
    pick_default_model,
    run_agent,
    transcribe_audio,
)
from email_control import EmailConfig, from_env, test_connection
from followups import list_upcoming, pop_due, start_scheduler
from system_control import system_control_enabled
import memory
import wakeword

ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "jarvis_icon_256.png")

# Streamlit treats a non-emoji avatar string as an image path, so use the icon
# image for JARVIS and a real emoji for the user.
AVATAR_ASSISTANT = ICON_PATH if os.path.exists(ICON_PATH) else "🤖"
AVATAR_USER = "🧑"

st.set_page_config(
    page_title="J.A.R.V.I.S.",
    page_icon=ICON_PATH if os.path.exists(ICON_PATH) else "🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Fallback list; the sidebar refreshes this live from your Groq account.
MODELS = [
    DEFAULT_MODEL,
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
]

# PC control only exists on the local desktop build, never on a hosted deploy.
PC_CONTROL_AVAILABLE = system_control_enabled()

# Voice presets -> (preferred browser voice names, rate, pitch)
VOICE_PRESETS = {
    "British (JARVIS)": (
        ["Google UK English Male", "Daniel", "Microsoft George", "Microsoft Ryan", "UK English Male"],
        1.0, 0.85,
    ),
    "British (female)": (
        ["Google UK English Female", "Kate", "Microsoft Sonia", "Microsoft Hazel"],
        1.0, 1.0,
    ),
    "US (male)": (["Google US English", "Alex", "Microsoft David", "Microsoft Mark"], 1.0, 0.9),
    "System default": ([], 1.0, 1.0),
}

# --------------------------------------------------------------------------- #
# Styling - the JARVIS HUD look
# --------------------------------------------------------------------------- #
st.markdown(
    """
<style>
:root { --jarvis: #37e6ff; --jarvis-dim: #1b8fa8; }

.stApp {
    background:
        radial-gradient(circle at 50% 0%, rgba(55,230,255,0.12), transparent 55%),
        radial-gradient(circle at 80% 100%, rgba(20,120,160,0.18), transparent 50%),
        #04070d;
    color: #d7f7ff;
}
.stApp::before {
    content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
    background: repeating-linear-gradient(
        to bottom, rgba(55,230,255,0.035) 0px, rgba(55,230,255,0.035) 1px,
        transparent 1px, transparent 3px);
}
.block-container { padding-top: 1.2rem; max-width: 1100px; z-index: 1; }

.jarvis-head { display:flex; align-items:center; gap:1.1rem; margin-bottom:.4rem; }
.jarvis-title {
    font-size: 2.5rem; font-weight: 800; letter-spacing: .55rem; color: #eafcff;
    text-shadow: 0 0 8px var(--jarvis), 0 0 26px rgba(55,230,255,.55);
    font-family: 'Segoe UI', system-ui, sans-serif;
}
.jarvis-sub { color: var(--jarvis-dim); letter-spacing: .28rem; font-size: .72rem;
    text-transform: uppercase; margin-top: -2px; }

.reactor { position: relative; width: 74px; height: 74px; flex: none; }
.reactor .ring { position:absolute; inset:0; border-radius:50%;
    border: 2px solid rgba(55,230,255,.35); border-top-color: var(--jarvis);
    animation: spin 3.2s linear infinite; }
.reactor .ring.r2 { inset:11px; border-top-color: transparent;
    border-right-color: var(--jarvis); animation-duration: 2.1s; animation-direction: reverse; }
.reactor .ring.r3 { inset:22px; border-top-color: var(--jarvis);
    border-left-color: transparent; animation-duration: 1.4s; }
.reactor .core { position:absolute; inset:30px; border-radius:50%;
    background: radial-gradient(circle, #ffffff, var(--jarvis) 55%, rgba(55,230,255,0) 75%);
    box-shadow: 0 0 18px var(--jarvis), 0 0 40px rgba(55,230,255,.7);
    animation: pulse 1.8s ease-in-out infinite; }
.reactor.speaking .core { animation: pulse .6s ease-in-out infinite;
    box-shadow: 0 0 26px #fff, 0 0 60px var(--jarvis); }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes pulse { 0%,100% { opacity:.75; transform: scale(.92);} 50% {opacity:1; transform: scale(1.06);} }

.hud-line { height:1px; margin:.6rem 0 1.1rem;
    background: linear-gradient(90deg, transparent, var(--jarvis), transparent);
    box-shadow: 0 0 10px rgba(55,230,255,.6); }

.stChatMessage { background: rgba(9,20,32,.78); border: 1px solid rgba(55,230,255,.28);
    border-radius: 14px; margin-bottom: .7rem; box-shadow: inset 0 0 22px rgba(55,230,255,.06); }

/* Chat bubbles: Streamlit renders the text inside stChatMessageContent, and its
   own muted colour made replies nearly invisible on the dark HUD, so set it
   explicitly on every element type the markdown can produce. */
[data-testid="stChatMessage"],
[data-testid="stChatMessageContent"],
[data-testid="stChatMessageContent"] p,
[data-testid="stChatMessageContent"] li,
[data-testid="stChatMessageContent"] span,
[data-testid="stChatMessageContent"] strong,
[data-testid="stChatMessageContent"] h1,
[data-testid="stChatMessageContent"] h2,
[data-testid="stChatMessageContent"] h3 { color: #f2fdff; }
[data-testid="stChatMessageContent"] { font-size: 1.03rem; }
[data-testid="stChatMessageContent"] p { line-height: 1.62; margin-bottom: .6rem; }
[data-testid="stChatMessageContent"] a { color: var(--jarvis); text-decoration: underline; }
[data-testid="stChatMessageContent"] code { background: rgba(0,0,0,.5); color: var(--jarvis);
    border:1px solid rgba(55,230,255,.3); border-radius:6px; padding:1px 5px; }
[data-testid="stChatMessageContent"] pre { background:#04080f; border:1px solid rgba(55,230,255,.3); border-radius:10px; }
[data-testid="stStatusWidget"] { color: #bfe9f7; }
[data-testid="stChatMessage"] img { background: transparent; }

section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, rgba(6,16,26,.96), rgba(3,8,14,.96));
    border-right: 1px solid rgba(55,230,255,.2);
    position: relative; z-index: 2; }
section[data-testid="stSidebar"] .stMarkdown, section[data-testid="stSidebar"] label { color:#d6f5ff; }
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: #9fd8ea; }
.side-title { color: var(--jarvis); letter-spacing:.25rem; font-weight:700; font-size:1rem; }
.status-on { color:#5dffb0; } .status-off { color:#ff7a7a; }

.stButton > button, .stTextInput input, .stSelectbox > div > div { border-radius: 10px; }
.stButton > button { background: rgba(55,230,255,.1); border:1px solid var(--jarvis);
    color:#eafcff; font-weight:600; letter-spacing:.04rem; }
.stButton > button:hover { background: rgba(55,230,255,.25); box-shadow:0 0 14px rgba(55,230,255,.5); }

.stChatInput textarea { background: rgba(9,20,32,.9); border:1px solid rgba(55,230,255,.3);
    border-radius: 12px; color:#eafcff; }
[data-testid="stBottom"] , [data-testid="stBottomBlockContainer"] {
    background: transparent; position: relative; z-index: 2; }
[data-testid="stChatInput"] textarea::placeholder { color: #8fc9dd; }
.footnote { color: var(--jarvis-dim); font-size:.7rem; text-align:center; margin-top:.4rem; }
.mic-hint { color: #9fd8ea; font-size:.72rem; margin-top:.3rem; }
</style>
""",
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# State helpers
# --------------------------------------------------------------------------- #
def _lan_ip() -> str:
    """The laptop's IPv4 address a phone on the same Wi-Fi can reach."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))  # no traffic sent; just picks the default route
            ip = s.getsockname()[0]
            if ip and not ip.startswith(("127.", "169.254", "0.")):
                return ip
        finally:
            s.close()
    except OSError:
        pass
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith(("127.", "169.254", "0.")):
            return ip
    except OSError:
        pass
    return ""


def _phone_url() -> str:
    ip = _lan_ip()
    if not ip:
        return ""
    try:
        port = st.get_option("server.port") or 8501
    except Exception:  # noqa: BLE001
        port = 8501
    return f"http://{ip}:{port}"


def _qr_png(url: str) -> bytes | None:
    try:
        import io

        import qrcode

        buf = io.BytesIO()
        qrcode.make(url, box_size=6, border=2).save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return None


def _load_key_from_env() -> str:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:  # noqa: BLE001
        pass
    key = os.getenv("GROQ_API_KEY", "")
    if not key:
        try:
            key = st.secrets.get("GROQ_API_KEY", "")
        except Exception:  # noqa: BLE001
            key = ""
    return key


def init_state() -> None:
    defaults = {
        "messages": [],
        "chat_history": [],
        "executor": None,
        "api_key": _load_key_from_env(),
        "model": DEFAULT_MODEL,
        "models": None,
        "pc_control": PC_CONTROL_AVAILABLE,
        "caps_applied": None,
        "reminders_on": True,
        "email_cfg": from_env(),
        "email_note": "",
        "ready": False,
        "tts_enabled": True,
        "voice_preset": "British (JARVIS)",
        "always_on_note": "",
        "mem_fingerprint": "",
        "last_audio_hash": None,
        "pending_voice": None,
        "replay": False,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


def current_caps() -> tuple:
    """The capability set the running agent was built with."""
    return (
        bool(PC_CONTROL_AVAILABLE and st.session_state.pc_control),
        bool(st.session_state.reminders_on),
        bool(st.session_state.email_cfg.ready),
    )


def make_executor(api_key: str, model: str):
    st.session_state.executor = build_agent(
        api_key, model,
        pc_control=bool(PC_CONTROL_AVAILABLE and st.session_state.pc_control),
        reminders=st.session_state.reminders_on,
        email_cfg=st.session_state.email_cfg if st.session_state.email_cfg.ready else None,
    )
    st.session_state.api_key = api_key
    st.session_state.model = model
    st.session_state.caps_applied = current_caps()
    st.session_state.ready = True


def speak(text: str) -> None:
    """Speak text in the browser using a JARVIS-like voice (Web Speech API)."""
    if not text:
        return
    names, rate, pitch = VOICE_PRESETS.get(
        st.session_state.voice_preset, VOICE_PRESETS["British (JARVIS)"]
    )
    payload = {
        "text": text,
        "names": names,
        "rate": rate,
        "pitch": pitch,
    }
    js = """
<script>
(function(){
  const cfg = %s;
  if(!('speechSynthesis' in window)) return;
  function pickVoice(voices){
    for(const n of cfg.names){
      const v = voices.find(x => x.name === n) || voices.find(x => x.name && x.name.includes(n));
      if(v) return v;
    }
    return voices.find(x => (x.lang||'').toLowerCase().startsWith('en-gb'))
        || voices.find(x => (x.lang||'').toLowerCase().startsWith('en'))
        || null;
  }
  function speak(){
    try { window.speechSynthesis.cancel(); } catch(e){}
    const u = new SpeechSynthesisUtterance(cfg.text);
    const v = pickVoice(window.speechSynthesis.getVoices());
    if(v) u.voice = v;
    u.rate = cfg.rate; u.pitch = cfg.pitch; u.volume = 1;
    window.speechSynthesis.speak(u);
  }
  if(window.speechSynthesis.getVoices().length){ speak(); }
  else { window.speechSynthesis.onvoiceschanged = speak; }
})();
</script>
""" % json.dumps(payload)
    components.html(js, height=0)


def render_always_on() -> None:
    """The native "Hello JARVIS" listener.

    This runs *outside* the window (Windows' offline speech engine in its own
    process), so JARVIS is reachable at any moment - even when nothing of ours
    is open. Turning it on also drops a sign-in entry so it survives a reboot.
    """
    if not wakeword.is_supported():
        st.caption("Hands-free wake word needs the Windows desktop app.")
        return

    live = wakeword.status()
    want = st.toggle(
        "Always listen: “Hello JARVIS”",
        value=live["alive"],
        help="Say “Hello JARVIS” anytime — even with JARVIS closed. It answers, opens the "
             "window and listens for your command. Uses Windows' built-in offline speech.",
    )
    if want != live["alive"]:
        extra = ""
        if want:
            ok, msg = wakeword.enable()
            wakeword.set_prefers_on(True)
            if ok:
                boot_ok, boot_msg = wakeword.install_startup()
                extra = (" I will also start myself at sign-in." if boot_ok
                         else f" (sign-in start failed: {boot_msg})")
        else:
            ok, msg = wakeword.disable()
            wakeword.set_prefers_on(False)
            wakeword.remove_startup()
            extra = " JARVIS will no longer start at sign-in."
        st.session_state.always_on_note = (msg if ok else f"⚠️ {msg}") + extra
        st.rerun()

    state = live["state"]
    dot = {"listening": "🟢", "armed": "🔵"}.get(state, "⚪")
    label = {
        "listening": "Listening for “Hello JARVIS”…",
        "armed": "Heard you — say your command.",
        "off": "Off — JARVIS will not wake to your voice.",
    }.get(state, state)
    st.caption(f"{dot} {label}")
    if live["mode"] and state != "off":
        st.caption(f"Offline engine: {live['mode']} · {live['engine']}")
    if st.session_state.always_on_note:
        st.caption(st.session_state.always_on_note)


def run_and_render(prompt: str) -> None:
    """Handle one user turn: run the agent, render, and speak the reply."""
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar=AVATAR_USER):
        st.markdown(prompt)

    answer = ""
    steps = []
    with st.chat_message("assistant", avatar=AVATAR_ASSISTANT):
        status = st.status("Processing…", expanded=False)
        try:
            answer, steps = run_agent(
                st.session_state.executor, prompt, st.session_state.chat_history
            )
            if steps:
                used = ", ".join(
                    sorted({(s[0].tool if hasattr(s[0], "tool") else str(type(s[0]))) for s in steps})
                )
                status.update(label=f"Used tools: {used}", state="complete")
            else:
                status.update(label="Reasoned directly", state="complete")
            st.markdown(answer or "…")
        except Exception as exc:  # noqa: BLE001
            status.update(label="Error", state="error")
            answer = f"⚠️ I hit a problem completing that: `{exc}`"
            st.markdown(answer)

    st.session_state.messages.append({"role": "assistant", "content": answer})
    st.session_state.chat_history.append(HumanMessage(content=prompt))
    st.session_state.chat_history.append(AIMessage(content=answer))
    if len(st.session_state.chat_history) > 20:
        st.session_state.chat_history = st.session_state.chat_history[-20:]

    if st.session_state.tts_enabled:
        # Strip code fences / markdown noise for a cleaner spoken reply.
        spoken = answer.split("```")[0][:1200]
        speak(spoken)

    # A turn that changed the follow-up store: rerun so the sidebar list is current.
    if {getattr(s[0], "tool", "") for s in steps} & {
            "add_followup", "complete_followup", "remove_followup"}:
        st.rerun()

    # A turn that changed memory: rebuild the agent so its system prompt carries
    # the fresh digest, then rerun so the sidebar list is current.
    new_fp = memory.fingerprint()
    if new_fp != st.session_state.mem_fingerprint:
        st.session_state.mem_fingerprint = new_fp
        if st.session_state.ready:
            make_executor(st.session_state.api_key.strip(), st.session_state.model)
        st.rerun()


init_state()

# Hands-free is meant to survive restarts: if the user switched it on once, the
# listener comes back with the app instead of waiting for another click.
if not st.session_state.get("wake_checked"):
    st.session_state.wake_checked = True
    if wakeword.is_supported() and wakeword.prefers_on() and not wakeword.is_on():
        wakeword.enable()

# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
with st.sidebar:
    if os.path.exists(ICON_PATH):
        st.image(ICON_PATH, width=72)
    st.markdown('<div class="side-title">◉ CORE SYSTEM</div>', unsafe_allow_html=True)
    st.markdown("---")

    key = st.session_state.api_key
    if key:
        # Key comes from .env / st.secrets / a previous unlock — never echo it back.
        st.success("API key configured ✔ (hidden)", icon="🔑")
        if st.button("Change key", use_container_width=True):
            st.session_state.api_key = ""
            st.session_state.ready = False
            st.rerun()
    else:
        with st.expander("🔑 Unlock JARVIS (API key)", expanded=False):
            st.caption("Stored only in this browser session — never shown again after unlock.")
            entered = st.text_input(
                "Groq API key",
                value="",
                type="password",
                placeholder="gsk_...",
                help="Get a free key at console.groq.com.",
            )
            if entered.strip() and entered.strip() != key:
                st.session_state.api_key = entered.strip()
                st.session_state.models = None
                st.rerun()

    if st.session_state.api_key and st.session_state.models is None:
        try:
            with st.spinner("Loading models from Groq..."):
                st.session_state.models = list_chat_models(st.session_state.api_key)
        except Exception:  # noqa: BLE001
            st.session_state.models = list(MODELS)
        if st.session_state.model not in st.session_state.models:
            st.session_state.model = pick_default_model(st.session_state.models)

    model_choices = st.session_state.models or list(MODELS)
    model_val = st.selectbox(
        "Model", model_choices,
        index=model_choices.index(st.session_state.model) if st.session_state.model in model_choices else 0,
        help="Live list of models your Groq key can access.",
    )

    if PC_CONTROL_AVAILABLE:
        st.session_state.pc_control = st.toggle(
            "🖥 Control this PC", value=st.session_state.pc_control,
            help="Lets JARVIS open websites and apps, WhatsApp, and read/write "
                 "files in your own folders. Only available in the local desktop app.",
        )
        if st.session_state.pc_control:
            st.caption("JARVIS can open apps, websites and files on this computer.")

        # ---- Phone remote (desktop builds only) ----
        phone_url = _phone_url()
        if phone_url:
            with st.expander("📱 Control from your phone", expanded=False):
                st.caption(f"On the same Wi-Fi, open **{phone_url}** on your phone — "
                           "full JARVIS chat, and it can drive this PC.")
                qr = _qr_png(phone_url)
                if qr:
                    st.image(qr, width=190)
                st.caption("Anyone on your Wi-Fi can open this page. If the phone "
                           "won't connect, allow JARVIS through the Windows firewall "
                           "(private networks).")
    elif os.environ.get("JARVIS_SYSTEM_CONTROL") != "1":
        st.caption("🖥 PC control is off — run the desktop app or `run.bat` to enable it.")

    # ---- Follow-up reminders ----
    st.session_state.reminders_on = st.toggle(
        "⏰ Follow-up reminders", value=st.session_state.reminders_on,
        help="JARVIS keeps a saved list of follow-ups and pops an alert when one is due.",
    )
    upcoming = list_upcoming() if st.session_state.reminders_on else []
    if upcoming:
        now = datetime.now()
        for item in upcoming[:6]:
            try:
                overdue = datetime.strptime(item["due"], "%Y-%m-%d %H:%M") < now
            except (KeyError, ValueError):
                overdue = False
            icon = "🔴" if overdue else "🟡"
            st.caption(f"{icon} {item.get('due', '?')} — {item.get('text', '')[:60]}")
        st.caption(f"{len(upcoming)} open follow-up(s). Ask JARVIS to list or close them.")
    else:
        st.caption("No follow-ups scheduled. Say *remind me to call Ali at 6*.")

    # ---- Memory ----
    mem_items = memory.memories()
    if mem_items:
        for m in mem_items[:4]:
            st.caption(f"🧠 {m.get('text', '')[:70]}")
        with st.popover(f"🧠 Memory ({len(mem_items)})", use_container_width=True):
            st.caption("Facts JARVIS keeps saved. Ask it to forget one, or clear here.")
            for m in mem_items:
                col1, col2 = st.columns([6, 1])
                col1.caption(f"`{m['id']}` · {m.get('text', '')[:90]}")
                if col2.button("✖", key=f"forget_{m['id']}", help="Forget this fact"):
                    memory.forget_memory(m["id"])
                    st.session_state.mem_fingerprint = memory.fingerprint()
                    if st.session_state.ready:
                        make_executor(st.session_state.api_key.strip(), st.session_state.model)
                    st.rerun()
            if st.button("Forget everything", use_container_width=True):
                memory.clear_memory()
                st.session_state.mem_fingerprint = memory.fingerprint()
                if st.session_state.ready:
                    make_executor(st.session_state.api_key.strip(), st.session_state.model)
                st.rerun()
    else:
        st.caption("No memories yet. Say *JARVIS, save this: …* — I also remember "
                   "important things on my own.")

    # ---- Email (read-only) ----
    cfg = st.session_state.email_cfg
    if cfg.ready:
        st.caption(f"✉️ Email connected: {cfg.masked()} (read-only)")
        if st.button("Disconnect email", use_container_width=True):
            st.session_state.email_cfg = EmailConfig("", "")
            st.session_state.email_note = ""
            st.rerun()
    else:
        with st.expander("✉️ Connect email (read-only)", expanded=False):
            st.caption("Needs an **app password** (Gmail/Outlook/Yahoo with 2-step verification). "
                       "JARVIS only ever reads — it cannot send, delete or mark mail.")
            addr = st.text_input("Email address", value="", placeholder="you@gmail.com",
                                 key="_email_addr")
            pwd = st.text_input("App password", value="", type="password",
                                placeholder="xxxx xxxx xxxx xxxx", key="_email_pwd")
            host = st.text_input("IMAP host (optional — auto-detected)", value="",
                                 placeholder="imap.gmail.com", key="_email_host")
            if st.button("Connect mailbox", use_container_width=True):
                if not addr.strip() or not pwd:
                    st.error("Enter the address and its app password.")
                else:
                    trial = EmailConfig(addr.strip(), pwd, host.strip())
                    try:
                        with st.spinner("Signing in..."):
                            st.session_state.email_note = test_connection(trial)
                        st.session_state.email_cfg = trial
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Could not connect: {exc}")
            if st.session_state.email_note:
                st.success(st.session_state.email_note)

    caps = current_caps()
    if st.session_state.ready and caps != st.session_state.caps_applied:
        try:
            make_executor(st.session_state.api_key.strip(), st.session_state.model)
            st.toast("Capabilities re-armed.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Re-arm failed: {exc}")

    if st.button("⏻ INITIALIZE JARVIS", use_container_width=True):
        if not st.session_state.api_key.strip():
            st.error("Please unlock JARVIS with your Groq API key first.")
        else:
            try:
                with st.spinner("Booting J.A.R.V.I.S. ..."):
                    make_executor(st.session_state.api_key.strip(), model_val)
                st.success("Systems online.")
            except Exception as exc:  # noqa: BLE001
                st.session_state.ready = False
                st.error(f"Initialization failed: {exc}")

    st.markdown("---")
    if st.session_state.ready:
        st.markdown('STATUS: <span class="status-on">● ONLINE</span>', unsafe_allow_html=True)
        st.caption(f"Model: {st.session_state.model}")
        if st.session_state.pc_control and PC_CONTROL_AVAILABLE:
            st.caption("🖥 PC control: armed")
        if st.session_state.reminders_on:
            st.caption("⏰ Reminders: armed")
        if st.session_state.email_cfg.ready:
            st.caption("✉️ Mailbox: linked")
    else:
        st.markdown('STATUS: <span class="status-off">● OFFLINE</span>', unsafe_allow_html=True)

    # ---- Voice controls ----
    st.markdown("---")
    st.markdown('<div class="side-title">🎙 VOICE</div>', unsafe_allow_html=True)
    st.session_state.tts_enabled = st.toggle(
        "Speak replies aloud", value=st.session_state.tts_enabled,
        help="JARVIS reads its answers using your browser's speech engine.",
    )
    preset_names = list(VOICE_PRESETS.keys())
    st.session_state.voice_preset = st.selectbox(
        "Voice", preset_names,
        index=preset_names.index(st.session_state.voice_preset)
        if st.session_state.voice_preset in preset_names else 0,
        help="Available voices depend on your OS/browser. British = classic JARVIS.",
    )

    render_always_on()

    st.caption("Hold to record a voice command (transcribed by Groq Whisper):")
    audio = None
    if st.session_state.ready:
        audio = mic_recorder(
            start_prompt="🎙 Record",
            stop_prompt="⏹ Stop",
            just_once=True,
            use_container_width=True,
            format="wav",
            key="jarvis_mic",
        )
    else:
        st.markdown('<div class="mic-hint">Initialize JARVIS to enable the mic.</div>',
                    unsafe_allow_html=True)

    if st.button("🔊 Replay last reply", use_container_width=True):
        st.session_state.replay = True

    st.markdown("---")
    if st.button("🧹 Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.chat_history = []
        st.session_state.pending_voice = None
        st.rerun()

    lines = ["**Tools:** web search · Wikipedia · calculator · date/time · voice"]
    if PC_CONTROL_AVAILABLE and st.session_state.pc_control:
        lines.append("\n\n**PC control:** apps · websites · WhatsApp · files & folders")
    if st.session_state.reminders_on:
        lines.append("\n\n**Follow-ups:** add · list · complete · remove (saved on disk)")
    lines.append("\n\n**Memory:** say “save this” — I keep it and remember it next time")
    if st.session_state.email_cfg.ready:
        lines.append("\n\n**Mailbox:** read-only inbox check")
    if wakeword.is_on():
        lines.append("\n\n**Hands-free:** say “Hello JARVIS” — I wake even when closed")
    lines.append("\n\nType or speak a task: research, calculate, summarise, plan, write, explain.")
    st.caption("".join(lines))

# --------------------------------------------------------------------------- #
# A key from .env means nobody has to click INITIALIZE: the desktop app is ready
# the moment it opens - which is what lets a wake-word command run unattended.
# --------------------------------------------------------------------------- #
if (
    not st.session_state.ready
    and not st.session_state.get("boot_init_tried")
    and st.session_state.api_key
    and st.session_state.models
):
    st.session_state.boot_init_tried = True
    try:
        make_executor(st.session_state.api_key.strip(), st.session_state.model)
    except Exception as exc:  # noqa: BLE001
        st.session_state.always_on_note = f"⚠️ Could not start automatically: {exc}"

# --------------------------------------------------------------------------- #
# Reminder scheduler: start the watcher, then surface anything due since the
# last rerun (native popup already fired; this keeps it visible in the chat).
# --------------------------------------------------------------------------- #
if st.session_state.reminders_on:
    start_scheduler()
    due = pop_due()
    for item in due:
        st.session_state.messages.append({
            "role": "assistant",
            "content": (f"⏰ **Follow-up due** — {item.get('text', '')} "
                        f"_(scheduled {item.get('due', '')})_"),
        })
    if due and st.session_state.tts_enabled:
        speak("Reminder, Sir. " + "; ".join(str(i.get("text", "")) for i in due))

# --------------------------------------------------------------------------- #
# Handle voice recording -> transcription
# --------------------------------------------------------------------------- #
if audio and audio.get("bytes"):
    blob = audio["bytes"]
    digest = hashlib.md5(blob).hexdigest()
    if digest != st.session_state.last_audio_hash:
        st.session_state.last_audio_hash = digest
        try:
            with st.spinner("Transcribing…"):
                transcript = transcribe_audio(blob, st.session_state.api_key, filename="command.wav")
            if transcript:
                st.session_state.pending_voice = transcript
            else:
                st.info("I didn't catch that, Sir. Please try again.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Transcription failed: {exc}")

# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
st.markdown(
    """
<div class="jarvis-head">
  <div class="reactor">
    <div class="ring"></div><div class="ring r2"></div>
    <div class="ring r3"></div><div class="core"></div>
  </div>
  <div>
    <div class="jarvis-title">J.A.R.V.I.S.</div>
    <div class="jarvis-sub">Just A Rather Very Intelligent System</div>
  </div>
</div>
<div class="hud-line"></div>
""",
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- #
# Chat history
# --------------------------------------------------------------------------- #
for msg in st.session_state.messages:
    with st.chat_message(
        msg["role"],
        avatar=AVATAR_ASSISTANT if msg["role"] == "assistant" else AVATAR_USER,
    ):
        st.markdown(msg["content"])

# --------------------------------------------------------------------------- #
# Input handling (text or voice)
# --------------------------------------------------------------------------- #
text_prompt = st.chat_input("Speak or type, Sir… give JARVIS a task")

# A command dictated to the native "Hello JARVIS" listener, if one just landed.
# Only taken once JARVIS is initialised - until then it stays queued on disk,
# so nothing you said out loud is silently thrown away.
dictated = (
    wakeword.pop_pending_command()
    if wakeword.is_supported() and st.session_state.ready
    else ""
)

prompt = text_prompt or st.session_state.pending_voice or dictated
st.session_state.pending_voice = None

if prompt:
    if not st.session_state.ready:
        st.warning("JARVIS is offline. Open **🔑 Unlock JARVIS** in the sidebar, enter your Groq API key and press **INITIALIZE JARVIS**.")
        st.stop()
    run_and_render(prompt)

# Replay button -> speak the most recent assistant answer again.
if st.session_state.replay:
    st.session_state.replay = False
    last = next((m["content"] for m in reversed(st.session_state.messages)
                 if m["role"] == "assistant"), "")
    if last:
        speak(last.split("```")[0][:1200])

st.markdown(
    '<div class="footnote">At your service · J.A.R.V.I.S. desktop assistant</div>',
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- #
# Hands-free tick: while the native listener holds the microphone, keep the page
# re-running so a dictated command lands within a second or two of you saying it.
# --------------------------------------------------------------------------- #
if wakeword.is_supported() and wakeword.is_on():
    time.sleep(1.2)
    st.rerun()
