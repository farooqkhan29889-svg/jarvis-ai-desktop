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
| **Wake word** 🗣 | *"Hello JARVIS"* — offline Windows listener, works with the window closed |
| **Voice replies** 🔊 | JARVIS speaks its answers aloud — deep **JARVIS (Avengers)** voice by default, switches to Hindi automatically |
| **PC control** 🖥 | *Local desktop only* — open apps, websites, WhatsApp, and read/write files |
| **Follow-up reminders** ⏰ | Saved list of tasks with due times; alerts you when one is due |
| **Memory** 🧠 | Say *"save this"* and JARVIS keeps it forever — it also remembers important facts on its own |
| **Email check** ✉️ | *Read-only* inbox — newest messages and unread count over IMAP |

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

### Control the laptop from your phone 📱

The desktop app (`.exe` / `run_desktop.bat`) makes JARVIS reachable over your
home Wi-Fi:

1. Open **📱 Control from your phone** in the sidebar — it shows a link and a
   **QR code**.
2. Point your phone's camera at the QR (or type the link) — the full JARVIS
   chat opens on the phone.
3. Type a command like *"open Notepad"* or *"what's on my Desktop?"* — JARVIS
   runs on the laptop and **carries it out on the laptop**, and replies appear
   on the phone (and are spoken there).
4. For hands-free use on the phone, switch on **🎙 Always listen on this
   device** and allow the microphone when the phone asks. The phone then
   listens on its own: say **"Hello JARVIS"** (or "हेलो जार्विस") — it answers
   **"Yes, Sir?"** — then speak your command. No Record button, and the phone's
   screen stays on while it listens.

Notes:
- Phone and laptop must be on the **same Wi-Fi**.
- First launch, Windows may ask to allow JARVIS through the firewall — choose
  **Allow on private networks**, otherwise the phone cannot connect.
- **Anyone on your Wi-Fi can open the page**, so keep it on trusted networks.
- Typing works everywhere. Voice input and the always-on wake word on the phone
  use the phone browser's speech features — the status bar under the switch
  says clearly if that browser can't listen (then the laptop's own listener
  still hears you from the room, and the 🎙 Record button still works).

The interface is a glowing cyan HUD with an animated arc reactor.

### Follow-up reminders ⏰

Works in the desktop app *and* the hosted page — reminders are stored per user,
not on the website's server.

Say *"remind me to call Ali at 6"*, *"follow up with the supplier in 2 hours"*,
*"what's on my follow-up list?"*, *"close the Ali one"*. JARVIS parses the time
itself (`in 45 minutes`, `tomorrow 9am`, `at 6`, `next week`, `Mon`, or a full
`2026-09-30 14:00`) and calls:

`add_followup` · `list_followups` · `complete_followup` · `remove_followup`

A background watcher checks the list every 15 seconds. When something is due you
get a **native Windows popup** (desktop app), a line in the chat, and the reply
read aloud. The sidebar shows the queue with 🔴 for overdue and 🟡 for pending.

- Saved in `~/.jarvis/followups.json` (override the folder with env `JARVIS_HOME`).
- Turn the whole feature off with the **⏰ Follow-up reminders** sidebar toggle.

### Memory 🧠

JARVIS has a persistent memory that survives restarts, rebuilds and moving to
another PC (it lives in your `~/.jarvis` folder):

- **Tell it to save:** *"JARVIS, save this: my clinic is open 9 to 5 except
  Thursday"* — it writes the fact down in full detail and confirms.
- **It also saves on its own.** When you mention something durable — your name,
  job, preferences, plans, deadlines, people, places — JARVIS quietly stores the
  important bits without being asked, so no note-taking is needed.
- **It remembers across sessions.** Saved facts are loaded into JARVIS's mind at
  boot, so next week it still knows your clinic hours.
- **Ask it:** *"what do you remember about me?"* · *"forget the thing about the
  clinic"* — `save_memory` · `list_memories` · `forget_memory`.
- The sidebar lists recent memories; **🧠 Memory** popover lets you drop one or
  wipe all of them by hand.
- **Secrets are refused.** JARVIS is explicitly told never to store passwords,
  API keys, card numbers or anything sensitive in memory.

### Email check ✉️ (strictly read-only)

Open **✉️ Connect email (read-only)** in the sidebar, enter your address and an
**app password** (Gmail/Outlook/Yahoo need this — a normal password is refused).
The IMAP host is auto-detected from the domain, or set it yourself.

`check_email` (newest messages, unread-only, or "containing <word>") ·
`count_unread_email`

Guarantees:

- **It cannot send, delete, move or mark mail.** The inbox is opened read-only and
  messages are fetched with `BODY.PEEK`, so nothing changes and unread stays unread.
- **Your password never appears on screen again** and stays in your own session —
  it is not written to disk by the app and is not shared with other viewers of a
  hosted deployment.
- Prefer `.env` on your own machine: `JARVIS_EMAIL_USER`, `JARVIS_EMAIL_PASSWORD`,
  optional `JARVIS_EMAIL_HOST` / `JARVIS_EMAIL_PORT`.
- **Gmail:** turn on 2-Step Verification, then create an
  [App Password](https://myaccount.google.com/apppasswords).

### Voice
- **Input:** press **🎙 Record**, speak, then **⏹ Stop**. Whisper transcribes it —
  it auto-detects the language, so Hindi works too — and JARVIS answers.
- **Replies:** toggle **Speak replies aloud** and pick a voice. The default is
  **JARVIS (Avengers)** — a deep, slowed British voice. Available voices depend
  on your OS/browser.
- **Talk in Hindi:** JARVIS answers in Hindi (Devanagari) whenever you speak or
  write in Hindi, and the reply is read out in a Hindi voice automatically,
  whatever voice preset is selected. If auto-detection guesses wrong, set
  **Speech language** in the sidebar to force Hindi or English.
- If a browser blocks auto-play audio, press **🔊 Replay last reply**.

### Always-on wake word — say "Hello JARVIS", any time

Switch on **Always listen: "Hello JARVIS"** in the sidebar (under 🎙 VOICE). The
wake word is then handled by **Windows itself**, in a small background process —
not by the browser — so it works whether or not the JARVIS window is open:

1. Say **"Hello JARVIS"** (or "Hey JARVIS").
2. JARVIS answers *"Yes, Sir?"* and raises its window — starting it if it was closed.
3. Speak your command ("what is the date today", "open Notepad"…). It arrives in
   the chat, gets answered, and is read aloud like anything you type.
   You can also say the command straight after the name in one breath.

- **No internet, no API cost for listening.** Detection uses the *offline*
  Windows desktop speech engine (`System.Speech`); only the answer goes to Groq.
- **It survives a reboot.** Switching it on also drops a plain **JARVIS shortcut**
  into your Startup folder, so the listener is back after sign-in. Remove the
  shortcut (or the switch) and it is gone — nothing else is installed, no admin
  rights needed.
- **It keeps the PC awake while it listens** (sleep would deafen it). The display
  still switches off normally.
- **Opt-in:** the microphone is only in use while that switch is on. Flip it off
  and the listener stops, the Startup shortcut is deleted, and the wish is unset.
- Needs the Windows Speech Recognition engine for your display language (en-US by
  default). If it is missing the sidebar tells you, and push-to-talk still works.

---

## 2b. Run it as a desktop app (its own window)

Instead of a browser tab, launch JARVIS in a native window:

- **Windows:** double-click **`run_desktop.bat`**
- **Manual:** `.venv\Scripts\python.exe desktop.py`

It starts the local server, waits until it's ready, then opens a 1280×880
PyWebView window (WebView2 on Windows). Closing the window shuts the server down.

> **Desktop requirements:** Python 3.10+ and the **WebView2 Runtime** (preinstalled
> on Windows 11 and most Windows 10 PCs; otherwise get it from Microsoft).
> **Voice input note:** push-to-talk needs microphone permission inside the window
> (`private_mode=False` is already set). The wake word does **not** rely on the
> window at all — it runs natively, because the packaged window's engine cannot
> reach a web speech service.

> **Want it up before you ask?** Switch on **Always listen: "Hello JARVIS"** once
> and JARVIS adds its own Startup shortcut, so it is running and listening every
> time you sign in.

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
   Switch **⏰ Follow-up reminders** and **✉️ Connect email** to taste — the agent is
   re-armed automatically when you change either one.
4. Press **⏻ INITIALIZE JARVIS** — status turns **● ONLINE**.
5. Type (or speak) a task in the box at the bottom.
6. On your own PC, switch on **Always listen: "Hello JARVIS"** — that is what makes
   JARVIS reachable at any moment, window open or not (see the wake word section).

**Examples to try**
- "What's the latest news on India's space program? Summarize in 3 bullets."
- "Calculate a 15% tip on a ₹4,850 bill and split it 4 ways."
- "Who is Nikola Tesla? Give me a short profile."
- "Plan my day: I have a clinic at 9, a call at 2, and gym at 6."
- "Write a polite email rescheduling an appointment to next Tuesday."
- 🖥 "Open Notepad." / "Open WhatsApp and message +9198765xxxxx saying I'll be late."
- 🖥 "Search YouTube for stomach exercises and show me." / "What files are on my Desktop?"
- 🖥 "Save these notes to Documents/clinic-notes.md."
- ⏰ "Remind me to follow up with the lab tomorrow at 10." / "What follow-ups are open?"
- ⏰ "Mark the lab one done." / "Remind me to check the register in 30 minutes."
- 🧠 "Save this: Dr. Sharma prefers evening appointments." / "What do you remember about me?"
- ✉️ "Any new emails?" / "How many unread messages do I have?" / "Check for mail from Ali."
- 🗣 With **Always listen** on: say **"Hello JARVIS"**, then *"what is the date today?"* —
  from the desktop, the kitchen, or with JARVIS's window never opened.

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
├── followups.py      # reminder store, due-time parser and background watcher
├── memory.py         # persistent memory: facts JARVIS saves (asked or on its own)
├── email_control.py  # read-only IMAP inbox tools
├── wakeword.py       # starts/stops the native "Hello JARVIS" listener + Startup entry
├── wake_listener.ps1 # offline Windows speech listener (wake word -> command file)
├── desktop.py        # PyWebView wrapper -> native desktop window
├── requirements.txt
├── .env.example
├── run.bat           # launch in browser
├── run_desktop.bat   # launch as desktop app window
├── install_desktop.bat  # Desktop + Start Menu shortcuts for the packaged app
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
- **Model errors (404 "model does not exist")?** Groq's available models differ per
  account. The sidebar reads your key's real list from the API, so pick from that —
  `openai/gpt-oss-120b`, `gpt-oss-20b` or `llama-3.3-70b-versatile` all handle
  tool-calling; small `allam-2-7b` style models often do not.
- **No reminder popup?** The native popup needs the desktop app on Windows; in a
  browser the due reminder appears in the chat and is spoken aloud. The watcher only
  starts after the page has loaded once, and delivers on the next interaction.
- **"Mail server refused the sign-in"?** Use an **app password** (Gmail needs
  2-Step Verification turned on first), not your normal password.
- **Wake word hears nothing?** The sidebar dot should be 🟢 *Listening*. It uses
  Windows' built-in speech engine and your default microphone, so check
  Settings → Time & language → Speech is installed for your language, and that no
  other app holds the mic exclusively. `~/.jarvis/wake_listener.log` records every
  phrase it understood.
- **Nothing wakes after a reboot?** Sign-in starts the listener, but a PC that is
  powered off or hibernated cannot hear you — while listening, JARVIS only asks
  Windows not to *sleep* (the display still switches off as usual).
- **Where is my wake-word state kept?** `~/.jarvis/` — `wake_config.json` (your
  wish + where JARVIS lives), `wake_status.json` (live listener status),
  `wake_command.json` (the last dictated command), `wake_listener.log`. Memories
  live in `memory.json` and follow-ups in `followups.json` in the same folder.
  Delete the folder to reset; the Startup shortcut is
  `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\JARVIS.lnk`.
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

### Install it like a normal app

After the build finishes, double-click **`install_desktop.bat`**. It drops a
**J.A.R.V.I.S.** shortcut on your Desktop and in the Start Menu — both with the
arc-reactor icon — pointing at `dist\JARVIS\JARVIS.exe`. No admin rights needed.
JARVIS stays inside this folder, so keep the folder wherever you installed it.

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
