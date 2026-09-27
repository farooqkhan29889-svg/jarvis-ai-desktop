# J.A.R.V.I.S. — AI Desktop Assistant

A JARVIS-style AI agent you talk to like Tony Stark's assistant. Give it a task —
research, calculations, summaries, planning, writing, explanations — and it uses
tools to get it done.

Built with **Python · Streamlit · LangChain · Groq**.

---

## What it can do

JARVIS is a tool-calling agent. It decides on its own when to use:

| Tool | Purpose |
|------|---------|
| **Web search** (DuckDuckGo) | Current facts, news, prices, docs |
| **Wikipedia** | Summaries of people, places, concepts |
| **Calculator** | Safe math (sqrt, trig, logs, powers…) |
| **Date / time** | Current local date, weekday, time |
| **Voice input** 🎙 | Record a command — transcribed by **Groq Whisper** |
| **Voice replies** 🔊 | JARVIS speaks its answers (British accent) via your browser |
| **PC control** 🖥 | *Local desktop only* — open apps, websites, WhatsApp, and read/write files |

### PC control (local `.exe` / `run.bat` / `run_desktop.bat` only)

Say things like *"open WhatsApp and message Ali"*, *"search YouTube for lo-fi"*,
*"what's on my Desktop?"*, *"make a note of this in Documents"*. JARVIS calls real
Windows tools for it:

`open_website` · `search_in_browser` · `open_application` · `send_whatsapp_message`
· `open_item` · `list_folder` · `read_text_file` · `create_text_file`
· `append_to_file` · `create_folder` · `system_status`

Guarantees baked in:

- **No arbitrary commands.** Only apps from a fixed name list can be launched.
- **Sandboxed files.** Access is limited to your Desktop, Documents, Downloads,
  Pictures, Music, Videos and home folder; `AppData`, `.ssh`, `.aws`, Windows and
  Program Files are refused.
- **Nothing is destroyed.** It cannot delete files or overwrite an existing one —
  it creates new files or appends, and tells you when you must do the rest yourself.
- **Off on the web.** A hosted Streamlit page cannot touch your PC, so the tools
  are only armed when `JARVIS_SYSTEM_CONTROL=1` (set by the local launchers) or in
  the packaged `.exe`. Toggle **🖥 Control this PC** in the sidebar to disable it.

The interface is a glowing cyan HUD with an animated arc reactor.

### Voice
- **Input:** in the sidebar, press **🎙 Record**, speak, then **⏹ Stop**. Your
  words are transcribed (Whisper) and sent to JARVIS automatically.
- **Replies:** toggle **Speak replies aloud** and pick a voice. "British (JARVIS)"
  uses an en-GB voice; available voices depend on your OS/browser.
- If a browser blocks auto-play audio, press **🔊 Replay last reply**.

### Hands-free wake word ("Hey JARVIS")
Turn on **Hands-free wake word** in the sidebar. JARVIS then listens continuously:
1. Say **"Hey JARVIS"** → it chimes *"Yes, Sir?"* (status dot turns green).
2. Speak your command → it's injected into the chat and answered + spoken aloud.

> Requires **Chrome or Edge** (browser Speech Recognition). It is rendered above
> the chat so it keeps listening across replies. The mic recorder + Whisper path
> still works in any browser if the wake word is unavailable.

---

## 2b. Run it as a desktop app (its own window)

Instead of a browser tab, launch JARVIS in a native window:

- **Windows:** double-click **`run_desktop.bat`**
- **Manual:** `.venv\Scripts\python.exe desktop.py`

It starts the local server, waits until it's ready, then opens a 1280×880
PyWebView window (WebView2 on Windows). Closing the window shuts the server down.

> **Desktop requirements:** Python 3.10+ and the **WebView2 Runtime** (preinstalled
> on Windows 11 and most Windows 10 PCs; otherwise get it from Microsoft).
> **Voice input note:** the mic/wake word need microphone permission inside the
> window (`private_mode=False` is already set). If your WebView2 build blocks the
> mic, run in Chrome/Edge instead — everything else works identically.

---

## 1. Get a free Groq API key

1. Go to <https://console.groq.com/keys>
2. Sign in (free) and click **Create API Key**
3. Copy the key (starts with `gsk_...`)

You paste this key into the app's sidebar. It stays in your browser session and
is never uploaded anywhere except directly to Groq.

---

## 2. Run it

### Easiest (Windows)
Double-click **`run.bat`**. It creates the virtual environment, installs
dependencies, and launches JARVIS in your browser.

### Manual
```bash
# from this folder
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py
```

The app opens at `http://localhost:8501`.

---

## 3. Use it

1. Open **🔑 Unlock JARVIS** in the left sidebar and paste your **Groq API key**
   (it is hidden afterwards — the key never reappears on screen).
2. Pick a model — the list is read live from your Groq account, so only models
   your key can actually use are offered.
3. On the desktop app, leave **🖥 Control this PC** on if you want it to open apps and files.
4. Press **⏻ INITIALIZE JARVIS** — status turns **● ONLINE**.
5. Type (or speak) a task in the box at the bottom.

**Examples to try**
- "What's the latest news on India's space program? Summarize in 3 bullets."
- "Calculate a 15% tip on a ₹4,850 bill and split it 4 ways."
- "Who is Nikola Tesla? Give me a short profile."
- "Plan my day: I have a clinic at 9, a call at 2, and gym at 6."
- "Write a polite email rescheduling an appointment to next Tuesday."
- 🖥 "Open Notepad." / "Open WhatsApp and message +9198765xxxxx saying I'll be late."
- 🖥 "Search YouTube for stomach exercises and show me." / "What files are on my Desktop?"
- 🖥 "Save these notes to Documents/clinic-notes.md."

---

## Optional: store the key in a file

Instead of pasting it every time:
```bash
copy .env.example .env
```
Then edit `.env` and set `GROQ_API_KEY=gsk_...`. The app loads it automatically.

---

## Project layout

```
jarvice-ai-dekstop/
├── app.py            # Streamlit JARVIS interface (HUD, chat, voice, wake word)
├── agent.py          # LangChain + Groq agent, tools, and Whisper transcription
├── system_control.py # sandboxed PC tools (apps, websites, WhatsApp, files)
├── desktop.py        # PyWebView wrapper -> native desktop window
├── requirements.txt
├── .env.example
├── run.bat           # launch in browser
├── run_desktop.bat   # launch as desktop app window
├── run.sh            # launcher for macOS/Linux (browser)
└── .venv/            # virtual environment (created on first run)
```

---

## Notes & troubleshooting

- **Runs on any Windows PC.** `run.bat` auto-detects Python (via the `py`
  launcher, then `python`/`python3`) and builds a fresh `.venv` on the target
  machine. The only prerequisite is **Python 3.10+** with "Add to PATH" ticked.
  The `.venv` is never shipped — each PC creates its own, so there are no
  hardcoded paths.
- **Distributing to others:** copy this whole folder *without* `.venv`, or share
  it via git (`.venv` is git-ignored). The recipient just double-clicks `run.bat`
  and pastes their own Groq key.
- **Web search empty?** DuckDuckGo occasionally rate-limits; retry in a moment.
- **Model errors?** Some Groq models don't support tool-calling. Use
  `llama-3.3-70b-versatile` or `llama-3.1-8b-instant`.
- **Want a true installable desktop app (window, icon)?** Next step is wrapping
  this in PyWebView or porting the UI to Electron/Tauri — say the word.


## Custom Jarvis icon

The app now ships a generated arc-reactor icon used for the browser tab favicon and the sidebar logo.

Files:
- `assets/jarvis.ico` — multi-size Windows icon (16–256px)
- `assets/jarvis_icon.png` — full-size master
- `assets/jarvis_icon_256.png` — 256px version used by the app

To use the icon for a packaged desktop build, pass `--icon=assets/jarvis.ico` to PyInstaller.

---

## Package as a single-file .exe (runs without Python)

Produce a portable `JARVIS.exe` that runs on any Windows PC with **no Python
installed**:

- **Windows:** double-click **`build_exe.bat`**
- **Manual:** `.venv\Scripts\python.exe -m PyInstaller jarvis.spec --noconfirm --clean`

Output: **`dist\JARVIS\JARVIS.exe`** (one-dir build, includes the JARVIS icon).
Ship the **whole `dist\JARVIS` folder**; run `JARVIS.exe` from inside it. On
launch it boots the local server and opens the native window (falls back to
your default browser if a window can't start). One-dir starts much faster than
a single-file build because nothing is unpacked at launch.

Notes:
- Startup is fast (a few seconds); the folder is large (a few hundred MB).
- The build embeds Streamlit + LangChain.
- `jarvis.spec` already bundles the conda runtime DLLs (`ffi`, `libssl`, `sqlite`)
  and the mic-recorder frontend that PyInstaller otherwise misses — this is what
  makes the frozen exe boot instead of dying on `import _ctypes`.
- Architecture: PyWebView's GUI loop runs on the main thread while the Streamlit
  server runs on a worker thread (Streamlit's `bootstrap.run` can't be used in a
  frozen app because it installs signal handlers).
- For a silent build with no console window, set `console=False` in `jarvis.spec`.
- Set env `JARVIS_NO_GUI=1` to force browser mode (useful for debugging).

---

## Deploy to the web (Streamlit Community Cloud)

The repo is Cloud-ready (`requirements.txt` + `app.py` at root, dark JARVIS theme
in `.streamlit/config.toml`).

1. Push this folder to a GitHub repo (see commands in your terminal / below).
2. Go to <https://share.streamlit.io> → sign in with GitHub → **New app**.
3. Pick the repo, branch `main`, main file path `app.py` → **Deploy**.
4. In the Cloud dashboard: **Settings → Secrets** → add:
   ```toml
   GROQ_API_KEY = "gsk_your_key_here"
   ```
   (The app reads `st.secrets["GROQ_API_KEY"]`; never commit a real key.)
5. Your JARVIS is live at `https://<app>.streamlit.app`.

> Voice input (mic) and the wake word work in the deployed web version too, in
> Chrome/Edge. The packaged `.exe` remains the offline/desktop option.
