"""J.A.R.V.I.S. - a JARVIS-style AI desktop assistant.

Streamlit front-end for the Groq/LangChain agent defined in agent.py.
Run with:  streamlit run app.py
"""

from __future__ import annotations

import hashlib
import json
import os

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
from system_control import system_control_enabled

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

.stChatMessage { background: rgba(9,20,32,.72); border: 1px solid rgba(55,230,255,.22);
    border-radius: 14px; margin-bottom: .7rem; box-shadow: inset 0 0 22px rgba(55,230,255,.05); }
.stChatMessage[data-testid="stChatMessageContent"] { color:#e6fbff; }
.stChatMessage .stMarkdown p { line-height:1.5; }
.stChatMessage .stMarkdown code { background: rgba(0,0,0,.45); color: var(--jarvis);
    border:1px solid rgba(55,230,255,.25); border-radius:6px; padding:1px 5px; }
.stChatMessage .stMarkdown pre { background:#04080f; border:1px solid rgba(55,230,255,.25); border-radius:10px; }

section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, rgba(6,16,26,.96), rgba(3,8,14,.96));
    border-right: 1px solid rgba(55,230,255,.2); }
section[data-testid="stSidebar"] .stMarkdown, section[data-testid="stSidebar"] label { color:#bfeeff; }
.side-title { color: var(--jarvis); letter-spacing:.25rem; font-weight:700; font-size:1rem; }
.status-on { color:#5dffb0; } .status-off { color:#ff7a7a; }

.stButton > button, .stTextInput input, .stSelectbox > div > div { border-radius: 10px; }
.stButton > button { background: rgba(55,230,255,.1); border:1px solid var(--jarvis);
    color:#eafcff; font-weight:600; letter-spacing:.04rem; }
.stButton > button:hover { background: rgba(55,230,255,.25); box-shadow:0 0 14px rgba(55,230,255,.5); }

.stChatInput textarea { background: rgba(9,20,32,.9); border:1px solid rgba(55,230,255,.3);
    border-radius: 12px; color:#eafcff; }
[data-testid="stBottomBlockContainer"] { background: transparent; }
.footnote { color: var(--jarvis-dim); font-size:.7rem; text-align:center; margin-top:.4rem; }
.mic-hint { color: var(--jarvis-dim); font-size:.72rem; margin-top:.3rem; }
</style>
""",
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# State helpers
# --------------------------------------------------------------------------- #
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
        "pc_control_applied": False,
        "ready": False,
        "tts_enabled": True,
        "voice_preset": "British (JARVIS)",
        "wake_word": False,
        "last_audio_hash": None,
        "pending_voice": None,
        "replay": False,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


def make_executor(api_key: str, model: str):
    pc = bool(PC_CONTROL_AVAILABLE and st.session_state.pc_control)
    st.session_state.executor = build_agent(api_key, model, pc_control=pc)
    st.session_state.api_key = api_key
    st.session_state.model = model
    st.session_state.pc_control_applied = pc
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


def render_wake_word() -> None:
    """Hands-free wake word. Listens for 'Hey JARVIS' with the browser's Speech
    Recognition, then captures the next utterance and injects it into the chat
    input so the normal agent pipeline (and voice reply) handles it.

    Requires Chrome/Edge. Rendered at a stable top-of-page position so chat
    reruns don't remount it and drop the live microphone session.
    """
    names, _rate, pitch = VOICE_PRESETS.get(
        st.session_state.voice_preset, VOICE_PRESETS["British (JARVIS)"]
    )
    cfg = {"names": names, "pitch": pitch, "tts": st.session_state.tts_enabled}
    html = """
<div id="ww" style="font-family:'Segoe UI',sans-serif;font-size:.8rem;letter-spacing:.05rem;
     color:#9fe9ff;border:1px solid rgba(55,230,255,.25);background:rgba(9,20,32,.6);
     border-radius:10px;padding:6px 12px;display:inline-block;">
  <span id="ww-dot" style="display:inline-block;width:8px;height:8px;border-radius:50%;
     background:#ff7a7a;margin-right:8px;box-shadow:0 0 8px #ff7a7a;"></span>
  <span id="ww-msg">Starting hands-free…</span>
</div>
<script>
(function(){
  const cfg = __CFG__;
  const dot = document.getElementById('ww-dot');
  const msg = document.getElementById('ww-msg');
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const WAKE = ['jarvis','javis','jarvice','travis'];

  function set(state, text){
    msg.textContent = text;
    const colors = {idle:'#37e6ff', armed:'#5dffb0', off:'#ff7a7a'};
    dot.style.background = colors[state] || '#37e6ff';
    dot.style.boxShadow = '0 0 8px ' + (colors[state] || '#37e6ff');
  }
  function say(text){
    if(!(cfg.tts && 'speechSynthesis' in window)) return;
    try{ speechSynthesis.cancel(); }catch(e){}
    const u = new SpeechSynthesisUtterance(text);
    const voices = speechSynthesis.getVoices();
    let v=null; for(const n of cfg.names){ v = voices.find(x=>x.name===n)||voices.find(x=>x.name&&x.name.includes(n)); if(v)break; }
    if(!v) v = voices.find(x=>(x.lang||'').toLowerCase().startsWith('en-gb'));
    if(v) u.voice=v; u.pitch=cfg.pitch; u.rate=1; speechSynthesis.speak(u);
  }
  function submit(text){
    const doc = window.parent.document;
    const ta = doc.querySelector('[data-testid="stChatInput"] textarea') || doc.querySelector('textarea');
    if(!ta) return false;
    const proto = window.parent.HTMLTextAreaElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto,'value').set;
    setter.call(ta, text);
    ta.dispatchEvent(new window.parent.Event('input',{bubbles:true}));
    setTimeout(()=>{
      ta.focus();
      ['keydown','keypress','keyup'].forEach(type=>{
        ta.dispatchEvent(new window.parent.KeyboardEvent(type,
          {key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}));
      });
    }, 80);
    return true;
  }

  if(!SR){ set('off','Hands-free needs Chrome or Edge'); return; }

  const rec = new SR();
  rec.continuous = true; rec.interimResults = true; rec.lang = 'en-US';
  let armed = false, armedAt = 0;

  rec.onstart = ()=> set('idle', armed ? 'Listening for command…' : 'Say “Hey JARVIS”…');
  rec.onerror = (e)=> { if(e.error==='not-allowed') set('off','Mic blocked — allow microphone'); };
  rec.onend = ()=>{ try{ rec.start(); }catch(_){} };
  rec.onresult = (e)=>{
    let fin='', inter='';
    for(let i=e.resultIndex;i<e.results.length;i++){
      const t=e.results[i][0].transcript;
      if(e.results[i].isFinal) fin+=t; else inter+=t;
    }
    const heard=(fin||inter).toLowerCase();
    if(!armed){
      if(WAKE.some(w=>heard.includes(w))){
        armed=true; armedAt=Date.now(); set('armed','Listening for command…'); say('Yes, Sir?');
      }
    } else {
      let cmd=(fin||'').trim();
      if(!cmd) return;
      let low=cmd.toLowerCase();
      WAKE.forEach(w=>{ low=low.replace(new RegExp('^(hey |ok |okay )?'+w+'[,!.]?\\\\s*','i'),''); });
      cmd=cmd.replace(/^[^a-z0-9]*/i,'');
      // drop the wake word itself if that is all we got
      const stripped=cmd.toLowerCase().replace(/^(hey |ok |okay )?/,'').replace(/[,.!]/g,'').trim();
      if(!stripped || WAKE.includes(stripped)){ return; }
      // remove a leading wake token from the command text
      let clean=cmd;
      const m=clean.match(/^(hey |ok |okay )?\\w+[,!.]?\\s+/i);
      if(m && WAKE.some(w=>m[0].toLowerCase().includes(w))) clean=clean.slice(m[0].length);
      clean=clean.trim();
      if(clean.length>1){ submit(clean); armed=false; set('idle','Sent: “'+clean.slice(0,40)+'”'); say('On it, Sir.'); }
    }
  };
  try{ rec.start(); }catch(_){}
})();
</script>
"""
    components.html(html.replace("__CFG__", json.dumps(cfg)), height=44)


def run_and_render(prompt: str) -> None:
    """Handle one user turn: run the agent, render, and speak the reply."""
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar=AVATAR_USER):
        st.markdown(prompt)

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


init_state()

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
        if st.session_state.ready and st.session_state.pc_control != st.session_state.pc_control_applied:
            try:
                make_executor(st.session_state.api_key.strip(), st.session_state.model)
                st.toast("PC control re-armed.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Re-arm failed: {exc}")
    elif os.environ.get("JARVIS_SYSTEM_CONTROL") != "1":
        st.caption("🖥 PC control is off — run the desktop app or `run.bat` to enable it.")

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
        if st.session_state.pc_control:
            st.caption("🖥 PC control: armed")
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

    st.session_state.wake_word = st.toggle(
        "Hands-free wake word",
        value=st.session_state.wake_word,
        help='Say "Hey JARVIS" then your command. Uses browser speech recognition (Chrome/Edge).',
    )

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

    pc_line = (
        "\n\n**PC control:** apps · websites · WhatsApp · files & folders"
        if (PC_CONTROL_AVAILABLE and st.session_state.pc_control) else ""
    )
    st.caption(
        "**Tools:** web search · Wikipedia · calculator · date/time · voice" + pc_line + "\n\n"
        "Type or speak a task: research, calculate, summarise, plan, write, explain."
    )

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

# Stable-position wake-word listener (rendered above chat history so adding
# messages below never remounts it and interrupts the live microphone).
if st.session_state.wake_word:
    render_wake_word()

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

prompt = text_prompt or st.session_state.pending_voice
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
