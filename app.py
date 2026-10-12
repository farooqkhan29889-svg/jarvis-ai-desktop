"""J.A.R.V.I.S. - a JARVIS-style AI desktop assistant.

Streamlit front-end for the Groq/LangChain agent defined in agent.py.
Run with:  streamlit run app.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from langchain_core.messages import AIMessage, HumanMessage
from streamlit_mic_recorder import mic_recorder

from agent import (
    DEFAULT_MODEL,
    build_agent,
    list_chat_models,
    pick_default_model,
    quick_reply,
    stream_agent,
    synthesize_speech,
    transcribe_audio,
)
from email_control import EmailConfig, from_env, test_connection
from followups import list_upcoming, pop_due, start_scheduler
from system_control import system_control_enabled
import memory
import proactive
import stop_signal
import vision
import wakeword
import whatsapp_cloud
import whatsapp_control

# The Stop button and the hands-free heartbeat talk to the server over extra
# HTTP routes; make sure they exist before anything renders. The WhatsApp Cloud
# API webhook is registered the same way.
stop_signal.ensure_routes()
whatsapp_cloud.install_webhook()

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

# Voice presets -> (preferred browser voice names, rate, pitch, lang prefix)
VOICE_PRESETS = {
    "JARVIS (Avengers)": (
        ["Google UK English Male", "Daniel", "Microsoft George", "Microsoft Ryan", "UK English Male"],
        0.94, 0.7, "en-gb",
    ),
    "British (JARVIS)": (
        ["Google UK English Male", "Daniel", "Microsoft George", "Microsoft Ryan", "UK English Male"],
        1.0, 0.85, "en-gb",
    ),
    "British (female)": (
        ["Google UK English Female", "Kate", "Microsoft Sonia", "Microsoft Hazel"],
        1.0, 1.0, "en-gb",
    ),
    "Hindi (हिन्दी)": (
        ["Google हिन्दी", "Microsoft Heera", "Microsoft Kalpana", "Hindi"],
        1.0, 1.0, "hi",
    ),
    "US (male)": (["Google US English", "Alex", "Microsoft David", "Microsoft Mark"], 1.0, 0.9, "en"),
    "System default": ([], 1.0, 1.0, "en"),
}

_HINDI_TEXT = re.compile("[\u0900-\u097f]")

# Sentence cut points for streaming speech - English/Hindi terminators.
_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")
# Markdown noise that would be read aloud otherwise.
_MD_NOISE = re.compile(r"[*_`#>]+")

# Groq's neural TTS (Canopy Labs Orpheus). English only; Hindi replies keep
# using a browser voice. Display label -> Orpheus voice id.
NEURAL_VOICES = {
    "Daniel — deep British male": "daniel",
    "Troy — male": "troy",
    "Austin — male": "austin",
    "Hannah — female": "hannah",
    "Autumn — female": "autumn",
    "Diana — female": "diana",
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


_PHONE_WAKE_LANGS = {"Hindi": "hi-IN", "English": "en-IN"}


def _phone_wake_component(lang_label: str) -> str:
    """Always-on wake word inside the browser (used from the phone).

    Continuous SpeechRecognition listens for "Hello JARVIS" (English or
    Devanagari), answers "Yes, Sir?" aloud, then sends the next utterance as a
    chat command. Returns the captured command text, or None/'' when idle.
    """
    preset = VOICE_PRESETS.get(
        st.session_state.voice_preset, VOICE_PRESETS["JARVIS (Avengers)"]
    )
    voice_names, rate, pitch, _ = preset
    cfg = {
        "lang": _PHONE_WAKE_LANGS.get(lang_label, "hi-IN"),
        "voiceNames": voice_names,
        "rate": rate,
        "pitch": pitch,
    }
    html = r"""
<style>
.jw-bar{font-family:'Segoe UI',system-ui,sans-serif;font-size:12px;color:#8fdcf2;
  background:#071019;border:1px solid rgba(55,230,255,.25);border-radius:8px;
  padding:6px 10px;height:100%;box-sizing:border-box;overflow:hidden;white-space:nowrap;}
.jw-bar .dot{display:inline-block;width:7px;height:7px;border-radius:50%;
  background:#2f9c4a;margin-right:6px;vertical-align:1px;box-shadow:0 0 6px #2f9c4a;}
.jw-bar.err{color:#ff9d9d;border-color:rgba(255,90,90,.4);}
.jw-bar.err .dot{background:#d04545;box-shadow:0 0 6px #d04545;}
.jw-bar.armed{color:#ffe9a8;border-color:rgba(255,220,120,.4);}
.jw-bar.armed .dot{background:#f2b23e;box-shadow:0 0 6px #f2b23e;}
</style>
<div id="jw-status" class="jw-bar"><span class="dot"></span><span id="jw-label">Starting…</span></div>
<script>
(function(){
  const cfg = __CFG__;
  const bar = document.getElementById('jw-status');
  const label = document.getElementById('jw-label');
  function setStatus(cls, txt){ bar.className = 'jw-bar' + (cls ? ' ' + cls : ''); label.textContent = txt; }

  if(window.__jw){
    window.__jw.setLang(cfg.lang);
    return;
  }
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if(!SR){
    setStatus('err', '🔴 This browser has no speech recognition — the 🎙 Record button still works.');
    return;
  }
  let armed = false, rec = null, alive = true, wakeLock = null;
  const WAKE_RE = /(^|[\s,.])((hey|hello|okay|ok)\s+)?(jar+vis|जार्विस|जारविस)/i;

  function send(cmd){
    try{
      const w = window.parent, d = w.document;
      const ta = d.querySelector('[data-testid="stChatInputTextArea"]');
      if(!ta){ setStatus('err', '🔴 Chat box not found on the page.'); return; }
      const setter = Object.getOwnPropertyDescriptor(w.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(ta, cmd);
      ta.dispatchEvent(new Event('input', { bubbles: true }));
      ta.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
      setStatus('on', '✅ Command sent: ' + cmd.slice(0, 40));
    }catch(e){
      setStatus('err', '🔴 Could not send the command: ' + e.message);
    }
  }
  function say(t){
    if(!('speechSynthesis' in window)) return;
    try { window.speechSynthesis.cancel(); } catch(e){}
    const u = new SpeechSynthesisUtterance(t);
    const voices = window.speechSynthesis.getVoices();
    for(const n of cfg.voiceNames){
      const v = voices.find(x => x.name === n) || voices.find(x => x.name && x.name.includes(n));
      if(v){ u.voice = v; break; }
    }
    u.rate = cfg.rate; u.pitch = cfg.pitch;
    window.speechSynthesis.speak(u);
  }
  function detectWake(raw, isFinal){
    const t = (raw || '').toLowerCase();
    const m = t.match(WAKE_RE);
    if(!m) return false;
    armed = true;
    setStatus('armed', '🔵 Yes, Sir? — say your command…');
    say('Yes, Sir?');
    if(isFinal){
      const rest = t.slice(m.index + m[0].length).replace(/^[\s,.]+/, '');
      if(rest.length > 3){ armed = false; send(rest); }
    }
    return true;
  }
  function handleFinal(t){
    if(detectWake(t, true)) return;
    if(armed){
      const cmd = t.trim();
      if(cmd.length > 2){ armed = false; send(cmd); }
    }
  }
  function holdScreen(){
    try{
      if(navigator.wakeLock && document.visibilityState === 'visible'){
        navigator.wakeLock.request('screen').then(function(l){ wakeLock = l; }).catch(function(){});
      }
    }catch(e){}
  }
  function start(){
    if(!alive) return;
    try{
      rec = new SR();
      rec.continuous = true;
      rec.interimResults = true;
      rec.lang = cfg.lang;
      rec.onstart = function(){ setStatus('on', '🟢 Listening — say “Hello JARVIS”'); holdScreen(); };
      rec.onerror = function(e){
        if(e.error === 'not-allowed' || e.error === 'service-not-allowed'){
          alive = false;
          setStatus('err', '🔴 Mic blocked — allow the microphone for this page.');
          return;
        }
        // no-speech / aborted / network errors: onend restarts us.
      };
      rec.onresult = function(ev){
        for(let i = ev.resultIndex; i < ev.results.length; i++){
          const r = ev.results[i], txt = r[0].transcript || '';
          if(r.isFinal){ handleFinal(txt); }
          else { detectWake(txt, false); }
        }
      };
      rec.onend = function(){ if(alive){ setTimeout(start, 300); } };
      rec.start();
    }catch(e){
      setStatus('err', '🔴 Could not start the microphone: ' + e.message);
    }
  }
  document.addEventListener('visibilitychange', holdScreen);
  window.__jw = {
    setLang: function(l){ cfg.lang = l; },
    test: function(t){ handleFinal(t); },
  };
  setStatus('on', '🟢 Listening — say “Hello JARVIS”');
  start();
})();
</script>
"""
    return components.html(html.replace("__CFG__", json.dumps(cfg)), height=56)


def _load_key_from_env() -> str:
    try:
        from dotenv import load_dotenv

        # CWD first (dev run), then next to the frozen exe and its parents so a
        # double-clicked JARVIS.exe finds .env no matter where it was started.
        candidates = [Path.cwd()]
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            for level in (exe_dir, exe_dir.parent, exe_dir.parent.parent):
                candidates.append(level)
        for folder in candidates:
            env_file = folder / ".env"
            if env_file.exists():
                load_dotenv(env_file)
                break
        else:
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
        "wa_note": "",
        "wa_cloud_cfg": whatsapp_cloud.startup_config(),
        "wa_cloud_note": "",
        "wa_public_ok": False,
        "ready": False,
        "tts_enabled": True,
        "voice_preset": "JARVIS (Avengers)",
        "voice_lang": "Auto",
        "neural_tts": True,
        "neural_voice": "daniel",
        "neural_note": "",
        "_spoken_key": None,
        "phone_wake_on": False,
        "phone_wake_lang": "Hindi",
        "always_on_note": "",
        "mem_fingerprint": "",
        "last_audio_hash": None,
        "pending_voice": None,
        "pending_image": "",
        "replay": False,
        "gemini_key": vision.from_env(),
        "vision_note": "",
        "briefing_on": bool(proactive.load_prefs().get("briefing_on", True)),
        "briefing_hour": int(proactive.load_prefs().get("briefing_hour", 8) or 8),
        "mail_watch_on": bool(proactive.load_prefs().get("mail_watch_on")),
        "wa_watch_on": bool(proactive.load_prefs().get("wa_watch_on")),
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


def current_caps() -> tuple:
    """The capability set the running agent was built with."""
    return (
        bool(PC_CONTROL_AVAILABLE and st.session_state.pc_control),
        bool(st.session_state.reminders_on),
        bool(st.session_state.email_cfg.ready),
        bool(st.session_state.wa_cloud_cfg.ready),
    )


def make_executor(api_key: str, model: str) -> None:
    """Build the agent. State flips to ready only after a clean build, so a
    failure leaves the previous executor (and any in-flight turn) intact."""
    wa_cfg = st.session_state.wa_cloud_cfg
    executor = build_agent(
        api_key, model,
        pc_control=bool(PC_CONTROL_AVAILABLE and st.session_state.pc_control),
        reminders=st.session_state.reminders_on,
        email_cfg=st.session_state.email_cfg if st.session_state.email_cfg.ready else None,
        vision_key=(st.session_state.gemini_key or "").strip(),
        vision_desktop=PC_CONTROL_AVAILABLE,
        wa_cfg=wa_cfg if wa_cfg.ready else None,
    )
    st.session_state.executor = executor
    st.session_state.api_key = api_key
    st.session_state.model = model
    st.session_state.caps_applied = current_caps()
    st.session_state.ready = True


def _play_audio(wav_bytes: bytes) -> None:
    """Play WAV bytes invisibly in the page."""
    b64 = base64.b64encode(wav_bytes).decode("ascii")
    components.html(
        f"""<audio id="jw-tts" autoplay></audio>
<script>
(function(){{
  const a = document.getElementById('jw-tts');
  a.src = 'data:audio/wav;base64,{b64}';
  a.play().catch(function(){{}});
}})();
</script>""",
        height=0,
    )


def speak(text: str) -> None:
    """Speak text in the browser using a JARVIS-like voice (Web Speech API).

    English replies use Groq's neural Orpheus voice when enabled (like
    Siri/GPT voice); replies written in Hindi (Devanagari) automatically
    switch to a Hindi voice, whatever preset is selected.
    """
    if not text:
        return
    text = _MD_NOISE.sub("", text).strip()
    if not text:
        return
    api_key = st.session_state.get("api_key") or ""
    if st.session_state.neural_tts and api_key and not _HINDI_TEXT.search(text):
        voice = st.session_state.get("neural_voice") or "daniel"
        spoken_key = ("neural", voice, text)
        if spoken_key != st.session_state.get("_spoken_key"):
            try:
                audio = synthesize_speech(text, api_key, voice=voice)
            except Exception as exc:  # noqa: BLE001
                audio = b""
                msg = str(exc)
                if "terms" in msg.lower():
                    st.session_state.neural_note = (
                        "Accept the Orpheus terms once in your Groq console to "
                        "enable it: https://console.groq.com/playground"
                        "?model=canopylabs/orpheus-v1-english"
                    )
                else:
                    st.session_state.neural_note = msg[:200]
            if audio:
                st.session_state._spoken_key = spoken_key
                st.session_state.neural_note = ""
                _play_audio(audio)
                return
            # Terms not accepted / no access / network: fall back to the
            # browser voices below.
    preset = VOICE_PRESETS.get(
        st.session_state.voice_preset, VOICE_PRESETS["JARVIS (Avengers)"]
    )
    names, rate, pitch, lang = preset
    if _HINDI_TEXT.search(text) and lang != "hi":
        names, rate, pitch, lang = VOICE_PRESETS["Hindi (हिन्दी)"]
    payload = {
        "text": text,
        "names": names,
        "rate": rate,
        "pitch": pitch,
        "lang": lang,
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
    return voices.find(x => (x.lang||'').toLowerCase().startsWith(cfg.lang))
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


def _cut_sentence(buf: str) -> tuple:
    """Split the last complete sentence off a streaming buffer."""
    matches = list(_SENTENCE_END.finditer(buf))
    if not matches:
        return "", buf
    cut = matches[-1].end()
    head, tail = buf[:cut].strip(), buf[cut:].strip()
    return (head, tail) if head else ("", buf)


_STOP_BUTTON_HTML = """
<style>
  html,body{margin:0;padding:0;background:transparent;overflow:hidden}
  #jb{font-size:.85rem;padding:.34rem .85rem;border-radius:.5rem;
      border:1px solid rgba(55,230,255,.45);background:rgba(55,230,255,.08);
      color:#37e6ff;cursor:pointer;font-family:inherit}
  #jb:hover{background:rgba(55,230,255,.2)}
  #jb:disabled{opacity:.5;cursor:default}
</style>
<button id="jb">⏹ Stop</button>
<script>
document.getElementById("jb").onclick = async function () {
  const b = this; b.disabled = true; b.textContent = "⏹ Stopping…";
  let base = "";
  try { base = document.referrer || ""; } catch (e) {}
  if (!base) { try { base = parent.location.href; } catch (e) { base = location.href; } }
  const urls = [];
  try { urls.push(new URL("__STOP_PATH__", base).href); } catch (e) {}
  urls.push("__STOP_PATH__");
  for (const u of urls) {
    try {
      const r = await fetch(u, {cache: "no-store"});
      if (r.ok) { b.textContent = "⏹ Stopped"; return; }
    } catch (e) {}
  }
  b.textContent = "⚠ Stop failed";
};
</script>
"""


def _render_stop_button() -> None:
    """Stop control that does not kill the running script (see stop_signal)."""
    components.html(
        _STOP_BUTTON_HTML.replace("__STOP_PATH__", stop_signal.STOP_ROUTE),
        height=46,
    )


# Invisible. If the wake tick chain ever dies, this timer is the only thing
# still alive on the page: it pings /_jarvis/tick and the server nudges the
# page back to life whenever a dictated command is waiting (see stop_signal).
_HEARTBEAT_HTML = """
<script>
(function () {
  var base = "";
  try { base = document.referrer || ""; } catch (e) {}
  if (!base) { try { base = parent.location.href; } catch (e) { base = location.href; } }
  var url = "__TICK_PATH__";
  try { url = new URL("__TICK_PATH__", base).href; } catch (e) {}
  function ping() {
    fetch(url, {cache: "no-store"}).catch(function () {
      try { fetch("__TICK_PATH__", {cache: "no-store"}); } catch (e) {}
    });
  }
  ping();
  setInterval(ping, 3000);
})();
</script>
"""


def _render_heartbeat() -> None:
    components.html(
        _HEARTBEAT_HTML.replace("__TICK_PATH__", stop_signal.TICK_ROUTE),
        height=0,
    )


def run_and_render(prompt: str, image_path: str | None = None) -> None:
    """Handle one user turn: run the agent, render, and speak the reply.

    The answer streams in as the model generates it, and each completed
    sentence is spoken straight away - JARVIS starts talking before the
    whole answer exists, and the Stop button cuts him off mid-answer.
    image_path: an attached image to show with the message; the agent is
    told where the file sits so look_at_image can study it.
    """
    attached = image_path if image_path and os.path.exists(image_path) else None
    entry = {"role": "user", "content": prompt}
    if attached:
        entry["img"] = attached
    st.session_state.messages.append(entry)
    with st.chat_message("user", avatar=AVATAR_USER):
        if attached:
            st.image(attached, width=300)
        st.markdown(prompt)
    agent_input = (
        f"[The user attached an image, saved at: {attached}]\n{prompt}"
        if attached else prompt
    )

    st.session_state.stop_talking = False
    stop_signal.clear_stop()
    stopped = False
    answer = ""
    tools_used = {}
    with st.chat_message("assistant", avatar=AVATAR_ASSISTANT):
        # The Stop control must not be a Streamlit widget: any widget interaction
        # during a run kills the script (1.64), losing the partial answer. Prefer
        # the HTML sidecar (hits our extra route); fall back to a widget otherwise.
        if not stop_signal.ensure_routes():
            st.button("⏹ Stop", key="stop_talking_btn",
                      help="Cut JARVIS off mid-answer.")
        else:
            _render_stop_button()
        status = st.status("Processing…", expanded=False)
        try:
            buffer = ""
            answer_parts = []

            def gen():
                nonlocal buffer, stopped
                for piece in stream_agent(
                    st.session_state.executor, agent_input,
                    st.session_state.chat_history, tool_collector=tools_used,
                ):
                    if stop_signal.stop_requested() or st.session_state.stop_talking:
                        stopped = True
                        return
                    buffer += piece
                    answer_parts.append(piece)
                    if len(buffer) > 60:
                        head, buffer = _cut_sentence(buffer)
                        if head and st.session_state.tts_enabled:
                            speak(head)
                    yield piece
                if buffer.strip() and st.session_state.tts_enabled:
                    speak(buffer.strip())

            answer = st.write_stream(gen()).strip() or "".join(answer_parts).strip()
            if stopped:
                stop_signal.clear_stop()
                status.update(label="Stopped — partial answer kept", state="complete")
                st.caption("⏹ Stopped by you — partial answer kept.")
            elif tools_used:
                status.update(
                    label=f"Used tools: {', '.join(sorted(tools_used))}",
                    state="complete",
                )
            else:
                status.update(label="Reasoned directly", state="complete")
        except Exception as exc:  # noqa: BLE001
            status.update(label="Error", state="error")
            answer = f"⚠️ I hit a problem completing that: `{exc}`"
            st.markdown(answer)

    if stopped and not answer:
        answer = "⏹ Stopped before I could answer."
    entry = {"role": "assistant", "content": answer}
    if stopped:
        entry["stopped"] = True
    st.session_state.messages.append(entry)
    st.session_state.chat_history.append(HumanMessage(content=agent_input))
    st.session_state.chat_history.append(AIMessage(content=answer))
    if len(st.session_state.chat_history) > 20:
        st.session_state.chat_history = st.session_state.chat_history[-20:]

    # A turn that changed the follow-up store: rerun so the sidebar list is current.
    if tools_used.keys() & {"add_followup", "complete_followup", "remove_followup"}:
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

# The extra HTTP routes can only be attached once this process has a live
# server, which the first run of the script may predate - so retry every rerun.
stop_signal.ensure_routes()
whatsapp_cloud.install_webhook()

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

    # A desktop install keeps its key in a local .env, so it comes online by
    # itself at every launch - a desk assistant that needs a click after each
    # restart cannot hear you, it only queues your voice commands. When the key
    # comes from st.secrets instead (cloud), the app waits for the deliberate
    # INITIALIZE click so a shared URL cannot silently spend the key.
    if (
        not st.session_state.ready
        and st.session_state.api_key
        and os.getenv("GROQ_API_KEY")
    ):
        try:
            make_executor(st.session_state.api_key.strip(), model_val)
        except Exception:  # noqa: BLE001
            st.caption("Auto-start did not complete — press ⏻ INITIALIZE JARVIS.")

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
        st.markdown("---")
        st.session_state.phone_wake_on = st.toggle(
            "🎙 Always listen on this device",
            value=st.session_state.phone_wake_on,
            help="Say “Hello JARVIS” and it answers without pressing Record. "
                 "Turn this on from the phone itself; keep the page open with "
                 "the screen on. Works best in Chrome.",
        )
        if st.session_state.phone_wake_on:
            st.session_state.phone_wake_lang = st.selectbox(
                "Command language",
                list(_PHONE_WAKE_LANGS),
                index=list(_PHONE_WAKE_LANGS).index(st.session_state.phone_wake_lang)
                if st.session_state.phone_wake_lang in _PHONE_WAKE_LANGS else 0,
                help="The language your spoken commands will be recognised in.",
            )
            _phone_wake_component(st.session_state.phone_wake_lang)
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

    # ---- WhatsApp (read + send by contact name, via WhatsApp Web) ----
    wa_state = whatsapp_control.quick_status() if PC_CONTROL_AVAILABLE else "off"
    if wa_state == "linked":
        st.caption("💬 WhatsApp linked — JARVIS can read chats and send to any contact by name.")
    else:
        with st.expander("💬 Link WhatsApp (one-time QR)", expanded=False):
            st.caption(
                "JARVIS drives WhatsApp Web in its own small Edge window — your "
                "normal browser and phone stay untouched. Scan the QR once and "
                "the link lasts for weeks."
            )
            if st.button("Open WhatsApp login", use_container_width=True):
                with st.spinner("Opening WhatsApp Web…"):
                    try:
                        st.session_state.wa_note = whatsapp_control.open_login_window()
                    except Exception as exc:  # noqa: BLE001
                        st.session_state.wa_note = f"Could not open it: {exc}"
                st.rerun()
            if st.session_state.wa_note:
                st.info(st.session_state.wa_note)
            if wa_state == "qr":
                st.caption("Waiting for the scan — WhatsApp → Settings → Linked devices → Link a device.")

    # ---- WhatsApp Cloud API (official Meta business channel) ----
    cloud = st.session_state.wa_cloud_cfg
    if cloud.ready:
        st.caption(f"🟢 WhatsApp Cloud API — {cloud.masked()}")
    with st.expander("🟢 Meta WhatsApp Cloud API", expanded=not cloud.ready):
        st.caption(
            "The official Meta channel for a **WhatsApp Business** number — no QR "
            "scan, no browser window. JARVIS sends texts, approved templates and "
            "broadcasts, and can answer people who message the number."
        )
        token_in = st.text_input(
            "Permanent access token", value="", type="password", key="_wa_token",
            placeholder="EAA…",
            help="Meta Business Settings → System Users → your user → Generate "
                 "token, with the whatsapp_business_messaging and "
                 "business_management permissions.",
        )
        phone_in = st.text_input("Phone Number ID", value=cloud.phone_number_id,
                                 key="_wa_phone", placeholder="123456789012345",
                                 help="Meta developer console → WhatsApp → API Setup.")
        waba_in = st.text_input("Business Account ID", value=cloud.waba_id,
                                key="_wa_waba", placeholder="9876543210",
                                help="Needed to list and send message templates.")
        secret_in = st.text_input("App secret", value="", type="password",
                                  key="_wa_secret",
                                  help="Meta app → App settings → Basic → App "
                                       "secret. Lets JARVIS prove an incoming "
                                       "webhook really came from Meta.")
        with st.popover("Advanced"):
            verify_in = st.text_input("Webhook verify token",
                                      value=cloud.verify_token or "jarvis-whatsapp")
            version_in = st.text_input(
                "Graph API version",
                value=cloud.api_version or whatsapp_cloud.DEFAULT_API_VERSION)
            st.caption("Usually left as they are.")
        remember_in = st.checkbox(
            "Remember on this PC", value=cloud.remember,
            help="Keeps the token in your Windows user folder (~/.jarvis) — never "
                 "in the project folder — so it is not pasted again every launch.",
        )
        c1, c2 = st.columns(2)
        if c1.button("Connect & test", use_container_width=True):
            trial = whatsapp_cloud.CloudConfig(
                token=token_in.strip(), phone_number_id=phone_in.strip(),
                waba_id=waba_in.strip(), app_secret=secret_in.strip(),
                verify_token=verify_in.strip() or "jarvis-whatsapp",
                api_version=version_in.strip() or whatsapp_cloud.DEFAULT_API_VERSION,
                business_name=cloud.business_name, our_number=cloud.our_number,
                remember=remember_in,
            )
            if not trial.token or not trial.phone_number_id:
                st.error("Paste the access token and the Phone Number ID.")
            else:
                try:
                    with st.spinner("Asking Meta…"):
                        st.session_state.wa_cloud_note = whatsapp_cloud.test_connection(trial)
                    whatsapp_cloud.save_config(trial)
                    st.session_state.wa_cloud_cfg = trial
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))
        if cloud.ready and c2.button("Disconnect", use_container_width=True):
            whatsapp_cloud.forget_config()
            whatsapp_cloud.set_runtime_config(None)
            st.session_state.wa_cloud_cfg = whatsapp_cloud.CloudConfig()
            st.session_state.wa_cloud_note = ""
            st.rerun()
        if st.session_state.wa_cloud_note:
            st.success(st.session_state.wa_cloud_note)

        if cloud.ready:
            st.markdown("**Contact book** — so JARVIS can message people by name")
            for row in whatsapp_cloud.contacts():
                k1, k2 = st.columns([6, 1])
                k1.caption(f"{row.get('name')} · +{row.get('number')}")
                if k2.button("✖", key=f"wac_{row.get('name')}_{row.get('number')}",
                             help="Remove from the book"):
                    whatsapp_cloud.remove_contact(str(row.get("name", "")))
                    st.rerun()
            n1, n2 = st.columns(2)
            c_name = n1.text_input("Name", key="_wa_c_name", placeholder="Ali")
            c_num = n2.text_input("Number", key="_wa_c_num", placeholder="919876543210")
            if st.button("Save contact", use_container_width=True):
                note = whatsapp_cloud.save_contact(c_name, c_num)
                if note.startswith("Saved"):
                    st.toast(note)
                    st.rerun()
                else:
                    st.error(note)

            st.markdown("**Incoming messages**")
            wa_prefs = whatsapp_cloud.load_prefs()
            public = whatsapp_cloud.public_webhook_url()
            if public:
                st.code(public)
                st.caption(
                    "Meta → WhatsApp → Configuration → Webhook: paste that as the "
                    f"callback URL with verify token `{cloud.verify_token}`, then "
                    "subscribe to the `messages` field."
                )
            else:
                st.caption("Meta delivers messages to a public HTTPS address, so "
                           "this PC needs a tunnel (one click below) or a host.")
            t1, t2 = st.columns(2)
            # A quick tunnel publishes every route on this port to the internet,
            # not just the webhook - so it has to cost an explicit opt-in, and
            # inbound payloads must be signed or anyone who finds the address can
            # feed JARVIS fake messages from any number.
            public_ok = st.toggle(
                "⚠ Allow public access", value=st.session_state.wa_public_ok,
                help="Starts a tunnel that puts this whole assistant at a public "
                     "https address. Anyone who reaches that address gets JARVIS "
                     "with your file, app and PC tools - the address is unguessable "
                     "but not private. Keeping this off and hosting the webhook "
                     "somewhere without PC control is the safer setup.",
            )
            if t1.button("Start public tunnel", use_container_width=True,
                         disabled=not public_ok,
                         help="Runs Cloudflare's free quick tunnel so Meta can "
                              "reach JARVIS on this PC."):
                if not cloud.app_secret.strip():
                    st.error("Paste the **App secret** above first. Without it Meta's "
                             "delivery cannot be signature-checked, so a public address "
                             "would accept forged messages from any number.")
                    st.stop()
                if not whatsapp_cloud.find_tunnel_binary():
                    with st.spinner("Downloading cloudflared…"):
                        try:
                            whatsapp_cloud.download_cloudflared()
                        except Exception as exc:  # noqa: BLE001
                            st.error(str(exc))
                            st.stop()
                with st.spinner("Opening a tunnel…"):
                    try:
                        url = whatsapp_cloud.start_tunnel()
                        st.session_state.wa_cloud_note = f"Tunnel up — {url}"
                    except Exception as exc:  # noqa: BLE001
                        st.error(str(exc))
                st.rerun()
            if whatsapp_cloud.tunnel_url():
                if t2.button("Stop tunnel", use_container_width=True):
                    whatsapp_cloud.stop_tunnel()
                    st.rerun()
            elif whatsapp_cloud.tunnel_error():
                st.caption(f"Tunnel: {whatsapp_cloud.tunnel_error()}")

            auto = st.toggle(
                "🤖 JARVIS answers incoming messages",
                value=bool(wa_prefs.get("auto_reply")),
                help="Replies on its own with a plain, short answer. It runs "
                     "without any tools, so nothing on this PC — no files, no "
                     "apps, no mailbox — can be reached from WhatsApp.",
            )
            allowed_in = st.text_input(
                "Only answer these numbers (blank = anyone)",
                value=", ".join(wa_prefs.get("allowed_senders") or []),
                placeholder="919876543210, 919000000000", key="_wa_allowed")
            notify_in = st.text_input(
                "Push my reminders & briefing to",
                value=", ".join(wa_prefs.get("notify_to") or []),
                placeholder="919876543210", key="_wa_notify",
                help="Free texts only arrive while the 24-hour window is open — "
                     "message the business number once from that phone first.")
            whatsapp_cloud.save_prefs({
                "auto_reply": bool(auto),
                "allowed_senders": [whatsapp_cloud.normalize_number(x)
                                    for x in allowed_in.split(",") if x.strip()],
                "notify_to": [whatsapp_cloud.normalize_number(x)
                              for x in notify_in.split(",") if x.strip()],
            })
            for line in (whatsapp_cloud.webhook_status(), whatsapp_cloud.reply_status()):
                if line:
                    st.caption(line)
            recent = whatsapp_cloud.inbox(5)
            if recent:
                st.markdown("**Latest on the business number**")
                for row in recent:
                    arrow = "→" if row.get("direction") == "out" else "←"
                    st.caption(f"{arrow} {row.get('at', '')} {row.get('name', '')}: "
                               f"{str(row.get('text', ''))[:80]}")

            sent_rows = whatsapp_cloud.outbox(5)
            if sent_rows:
                st.markdown("**What JARVIS has sent**")
                for row in sent_rows:
                    mark = "✅" if row.get("status") == "sent" else "❌"
                    tail = "" if row.get("status") == "sent" else f" — {str(row.get('detail', ''))[:90]}"
                    st.caption(f"{mark} {row.get('at', '')} → +{row.get('to', '')} "
                               f"[{row.get('kind', '')}] {str(row.get('body', ''))[:60]}{tail}")

    # ---- Proactivity: morning briefing + new-mail alerts ----
    with st.expander("🌅 Proactivity — briefing & alerts", expanded=False):
        st.session_state.briefing_on = st.toggle(
            "🌅 Morning briefing",
            value=st.session_state.briefing_on,
            help="Once a day, after the hour below, JARVIS greets you with the "
                 "date, your follow-ups and your mailbox.",
        )
        hours = list(range(5, 12))
        cur_hour = st.session_state.briefing_hour if st.session_state.briefing_hour in hours else 8
        picked = st.selectbox(
            "Briefing time", hours, index=hours.index(cur_hour),
            format_func=lambda h: f"{h:02d}:00",
            disabled=not st.session_state.briefing_on,
        )
        st.session_state.briefing_hour = int(picked)
        if cfg.ready:
            st.session_state.mail_watch_on = st.toggle(
                "📬 New-mail alerts",
                value=st.session_state.mail_watch_on,
                help="While JARVIS is open, he checks the inbox every couple of "
                     "minutes and announces new mail. Read-only, as always.",
            )
        else:
            st.session_state.mail_watch_on = False
            st.caption("Connect email above to get new-mail alerts.")
        if wa_state == "linked":
            st.session_state.wa_watch_on = st.toggle(
                "💬 New WhatsApp-message alerts",
                value=st.session_state.wa_watch_on,
                help="While JARVIS is open, he peeks at the WhatsApp sidebar "
                     "every minute or so and announces new messages — read-only, "
                     "nothing is marked as read.",
            )
        else:
            st.session_state.wa_watch_on = False
            st.caption("Link WhatsApp above to get new-message alerts.")
        if cloud.ready:
            wa_push = whatsapp_cloud.load_prefs()
            push_briefing = st.toggle(
                "🟢 Send the briefing to my WhatsApp",
                value=bool(wa_push.get("notify_briefing")),
                help="The same morning briefing lands on your phone through the "
                     "WhatsApp Cloud API business number.",
            )
            push_reminders = st.toggle(
                "🟢 Send follow-up reminders to my WhatsApp",
                value=bool(wa_push.get("notify_reminders")),
                help="Goes to the number(s) in “Push my reminders & briefing to” "
                     "in the Cloud API panel above.",
            )
            whatsapp_cloud.save_prefs({
                "notify_briefing": bool(push_briefing),
                "notify_reminders": bool(push_reminders),
            })
            if not wa_push.get("notify_to"):
                st.caption("Add a number in the Cloud API panel to receive them.")
        proactive.save_prefs({
            "briefing_on": st.session_state.briefing_on,
            "briefing_hour": st.session_state.briefing_hour,
            "mail_watch_on": st.session_state.mail_watch_on,
            "wa_watch_on": st.session_state.wa_watch_on,
        })
        if st.session_state.mail_watch_on and cfg.ready:
            proactive.start_mail_watch(cfg)
        else:
            proactive.stop_mail_watch()
        mail_status = proactive.mail_watch_status()
        if mail_status:
            st.caption(mail_status)
        if st.session_state.wa_watch_on and wa_state == "linked":
            proactive.start_wa_watch()
        else:
            proactive.stop_wa_watch()
        wa_status = proactive.wa_watch_status()
        if wa_status:
            st.caption(wa_status)

    # ---- Vision (Gemini) ----
    vision_key = (st.session_state.gemini_key or "").strip()
    if vision_key:
        eyes = "images and this PC's screen" if PC_CONTROL_AVAILABLE else "images"
        st.caption(f"👁 Vision on: JARVIS can see {eyes}.")
        with st.expander("📷 Show JARVIS an image", expanded=False):
            up = st.file_uploader(
                "Image", type=["png", "jpg", "jpeg", "webp", "gif", "bmp"],
                label_visibility="collapsed",
            )
            q = st.text_input(
                "Question (optional)", value="",
                placeholder="What is in this image?", key="_vision_q",
            )
            if up is not None and st.button("Look at it", use_container_width=True):
                if not st.session_state.ready:
                    st.warning("Initialize JARVIS first.")
                else:
                    try:
                        path = vision.save_upload(up.name, up.getvalue())
                        st.session_state.pending_image = path
                        st.session_state.pending_voice = (
                            q.strip()
                            or "Look at this image and describe everything important in it."
                        )
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Could not save the image: {exc}")
        if st.button("Change vision key", use_container_width=True):
            st.session_state.gemini_key = ""
            if st.session_state.ready:
                try:
                    make_executor(st.session_state.api_key.strip(), st.session_state.model)
                except Exception:  # noqa: BLE001
                    pass
            st.rerun()
    else:
        with st.expander("👁 Give JARVIS vision (Gemini)", expanded=False):
            st.caption(
                "Add a free Google AI Studio key and JARVIS can look at images"
                + (" — and at your screen" if PC_CONTROL_AVAILABLE else "")
                + ". Get one at aistudio.google.com/apikey. On a hosted deploy, "
                "set GEMINI_API_KEY in the app's Secrets instead."
            )
            entered = st.text_input(
                "Gemini API key", value="", type="password",
                placeholder="AIza...", key="_vision_key",
            )
            if entered.strip():
                st.session_state.gemini_key = entered.strip()
                if os.getenv("GROQ_API_KEY"):
                    saved = vision.save_key(st.session_state.gemini_key)
                    st.session_state.vision_note = (
                        f"Key saved to {saved} — JARVIS keeps his eyes." if saved
                        else "Key active for this session only."
                    )
                else:
                    st.session_state.vision_note = "Key active for this session only."
                if st.session_state.ready:
                    try:
                        make_executor(st.session_state.api_key.strip(), st.session_state.model)
                        st.toast("Vision armed.")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Vision arm failed: {exc}")
                st.rerun()
    if st.session_state.vision_note:
        st.caption(st.session_state.vision_note)

    caps = current_caps()
    if st.session_state.ready and caps != st.session_state.caps_applied:
        try:
            make_executor(st.session_state.api_key.strip(), st.session_state.model)
            st.toast("Capabilities re-armed.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Re-arm failed: {exc}")

    # The webhook runs outside any Streamlit session, so hand it what to answer
    # with: the config, and a deliberately tool-free reply function. On a hosted
    # deployment only .env credentials are used - one viewer's key must never
    # answer another viewer's business number.
    #
    # On the desktop the global is only ever *replaced*, never blanked: the phone
    # page and any extra window share this process with an empty session, and
    # their reruns must not strip the credentials the main window connected with.
    # Disconnecting clears it explicitly instead.
    if PC_CONTROL_AVAILABLE:
        runtime_cfg = cloud if cloud.ready else whatsapp_cloud.startup_config()
        if runtime_cfg.ready:
            whatsapp_cloud.set_runtime_config(runtime_cfg)
    else:
        whatsapp_cloud.set_runtime_config(None)
    reply_key = _load_key_from_env() or (
        st.session_state.api_key.strip() if PC_CONTROL_AVAILABLE else "")
    if reply_key:
        whatsapp_cloud.set_reply_handler(
            lambda text, name, number, _k=reply_key, _m=st.session_state.model:
                quick_reply(_k, _m, f"{name}: {text}"))
    else:
        whatsapp_cloud.set_reply_handler(None)

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
        if st.session_state.gemini_key:
            st.caption("👁 Vision: images" + (" + screen" if PC_CONTROL_AVAILABLE else ""))
        if st.session_state.briefing_on:
            st.caption(f"🌅 Briefing: after {int(st.session_state.briefing_hour):02d}:00")
        if st.session_state.mail_watch_on:
            st.caption("📬 New-mail alerts: on")
        if st.session_state.wa_watch_on:
            st.caption("💬 New WhatsApp-message alerts: on")
    else:
        st.markdown('STATUS: <span class="status-off">● OFFLINE</span>', unsafe_allow_html=True)

    # ---- Voice controls ----
    st.markdown("---")
    st.markdown('<div class="side-title">🎙 VOICE</div>', unsafe_allow_html=True)
    st.session_state.tts_enabled = st.toggle(
        "Speak replies aloud", value=st.session_state.tts_enabled,
        help="JARVIS reads its answers aloud.",
    )
    st.session_state.neural_tts = st.toggle(
        "Natural neural voice (Groq)",
        value=st.session_state.neural_tts,
        help="High-quality AI voice (Orpheus) for English replies — like the "
             "Siri/GPT voice. Hindi replies use the Hindi system voice. Needs a "
             "one-time terms acceptance in your Groq console.",
    )
    if st.session_state.neural_note:
        st.caption(f"⚠️ Neural voice unavailable: {st.session_state.neural_note}")
    if st.session_state.neural_tts:
        neural_ids = list(NEURAL_VOICES.values())
        st.session_state.neural_voice = st.selectbox(
            "Neural voice",
            neural_ids,
            index=neural_ids.index(st.session_state.neural_voice)
            if st.session_state.neural_voice in neural_ids else 0,
            format_func=lambda v: next(
                k for k, val in NEURAL_VOICES.items() if val == v
            ),
            help="The Orpheus voice JARVIS speaks with. Daniel is the deep "
                 "British male — closest to the movie JARVIS.",
        )
    preset_names = list(VOICE_PRESETS.keys())
    st.session_state.voice_preset = st.selectbox(
        "Voice", preset_names,
        index=preset_names.index(st.session_state.voice_preset)
        if st.session_state.voice_preset in preset_names else 0,
        help="The system (browser) voice — used for Hindi replies, the phone's "
             "\"Yes, Sir?\" wake-up, and as a fallback if the neural voice fails. "
             "'JARVIS (Avengers)' is the deep movie-assistant voice.",
    )
    st.session_state.voice_lang = st.selectbox(
        "Speech language", ["Auto", "Hindi", "English"],
        index=["Auto", "Hindi", "English"].index(st.session_state.voice_lang)
        if st.session_state.voice_lang in ("Auto", "Hindi", "English") else 0,
        help="Language of your spoken commands. Auto lets Whisper detect it — use "
             "Hindi or English to force one.",
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
    if PC_CONTROL_AVAILABLE and whatsapp_control.quick_status() == "linked":
        lines.append("\n\n**WhatsApp:** read chats & send by contact name")
    if st.session_state.wa_cloud_cfg.ready:
        bits = ["send by name or number", "templates", "broadcast"]
        if whatsapp_cloud.load_prefs().get("auto_reply"):
            bits.append("auto-answers incoming")
        lines.append("\n\n**WhatsApp Cloud API:** " + " · ".join(bits))
    if st.session_state.gemini_key:
        lines.append("\n\n**Vision:** look at images"
                     + (" and the screen" if PC_CONTROL_AVAILABLE else ""))
    proactive_bits = []
    if st.session_state.briefing_on:
        proactive_bits.append(f"daily briefing at {int(st.session_state.briefing_hour):02d}:00")
    if st.session_state.mail_watch_on:
        proactive_bits.append("new-mail alerts")
    if st.session_state.wa_watch_on:
        proactive_bits.append("new WhatsApp-message alerts")
    if proactive_bits:
        lines.append("\n\n**Proactive:** " + " · ".join(proactive_bits))
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
# Proactive items: the daily briefing and new-mail alerts. The native popup
# already fired; this keeps them in the chat and speaks them aloud.
# --------------------------------------------------------------------------- #
for item in proactive.pop_proactive():
    st.session_state.messages.append({
        "role": "assistant",
        "content": item["text"],
    })
    if st.session_state.tts_enabled and item.get("speak"):
        speak(item["speak"])

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
                transcript = transcribe_audio(
                    blob, st.session_state.api_key, filename="command.wav",
                    language={"Hindi": "hi", "English": "en"}.get(st.session_state.voice_lang),
                )
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
# WhatsApp Cloud API: whatever reached the business number since the last rerun.
# Drained BEFORE the history renders, so a message the heartbeat woke us for
# appears in this run instead of waiting for the next one.
# --------------------------------------------------------------------------- #
for wa_msg in whatsapp_cloud.pop_events():
    wa_who = wa_msg.get("name") or wa_msg.get("from")
    wa_body = str(wa_msg.get("text", ""))
    st.session_state.messages.append({
        "role": "assistant",
        "content": f"💬 **WhatsApp from {wa_who}** — {wa_body}",
    })
    if st.session_state.tts_enabled:
        speak(f"WhatsApp message from {wa_who}. {wa_body[:200]}")

# --------------------------------------------------------------------------- #
# Chat history
# --------------------------------------------------------------------------- #
for msg in st.session_state.messages:
    with st.chat_message(
        msg["role"],
        avatar=AVATAR_ASSISTANT if msg["role"] == "assistant" else AVATAR_USER,
    ):
        if msg.get("img") and os.path.exists(msg["img"]):
            st.image(msg["img"], width=300)
        st.markdown(msg["content"])
        if msg.get("stopped"):
            st.caption("⏹ Stopped by you — partial answer kept.")

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
img_path = st.session_state.pop("pending_image", "")

if prompt:
    if not st.session_state.ready:
        st.warning("JARVIS is offline. Open **🔑 Unlock JARVIS** in the sidebar, enter your Groq API key and press **INITIALIZE JARVIS**.")
        st.stop()
    run_and_render(prompt, image_path=img_path or None)

# Replay button -> speak the most recent assistant answer again.
if st.session_state.replay:
    st.session_state.replay = False
    last = next((m["content"] for m in reversed(st.session_state.messages)
                 if m["role"] == "assistant"), "")
    if last:
        st.session_state._spoken_key = None
        speak(last.split("```")[0][:1200])

st.markdown(
    '<div class="footnote">At your service · J.A.R.V.I.S. desktop assistant</div>',
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------- #
# Hands-free tick: while the native listener holds the microphone, keep the page
# re-running so a dictated command lands within a second or two of you saying it.
# The heartbeat timer survives a missed tick, so the chain can always be nudged
# back to life on the next dictated command instead of dying silently.
# The same heartbeat surfaces an inbound WhatsApp Cloud API message: the server
# only nudges a rerun when something is actually waiting, so an idle page costs
# one tiny ping every few seconds.
# --------------------------------------------------------------------------- #
if (wakeword.is_supported() and (wakeword.is_on() or wakeword.prefers_on())) \
        or st.session_state.wa_cloud_cfg.ready:
    _render_heartbeat()

if wakeword.is_supported() and wakeword.is_on():
    time.sleep(1.2)
    st.rerun()
