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
| **Voice input** 🎙 | Record a command — transcribed by **Groq Whisper** (auto-detects Hindi/English) |
| **Wake word** 🗣 | *"Hello JARVIS"* — offline Windows listener, works with the window closed |
| **Voice replies** 🔊 | JARVIS speaks its answers aloud — natural neural voice (Groq Orpheus) by default, Hindi voice for Hindi replies |
| **PC control** 🖥 | *Local desktop only* — open apps, websites, WhatsApp, and read/write files |
| **Follow-up reminders** ⏰ | Saved list of tasks with due times; alerts you when one is due |
| **Memory** 🧠 | Say *"save this"* and JARVIS keeps it forever — it also remembers important facts on its own |
| **Email check** ✉️ | *Read-only* inbox — newest messages and unread count over IMAP |
| **Vision** 👁 | JARVIS looks at images you attach — and, on desktop, at your screen — using a free Gemini key |
| **Proactivity** 🌅 | A morning briefing, new-mail and new-WhatsApp alerts — JARVIS speaks up first |
| **WhatsApp** 💬 | *Local desktop only* — read chats and send messages to any contact **by name**, through your own WhatsApp |

### PC control (local `.exe` / `run.bat` / `run_desktop.bat` only)

Say things like *"open WhatsApp and message Ali"*, *"search YouTube for lo-fi"*,
*"what's on my Desktop?"*, *"make a note of this in Documents"*. JARVIS calls real
Windows tools for it:

`open_website` · `search_in_browser` · `open_application`
· `whatsapp_unread` · `whatsapp_read_chat` · `send_whatsapp_message`
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
- **Replies:** toggle **Speak replies aloud** and pick a voice.
- **Natural neural voice (default):** **Natural neural voice (Groq)** uses
  Groq's Orpheus model — a high-quality AI voice like Siri/GPT/Gemini use,
  spoken from your existing Groq key. Pick the voice under **Neural voice**
  (*Daniel* is the deep British male, closest to the movie JARVIS; *Troy* and
  *Austin* are male, *Hannah*, *Autumn*, *Diana* female). One-time setup: open
  <https://console.groq.com/playground?model=canopylabs/orpheus-v1-english>
  in your Groq account and accept the model terms — until then JARVIS
  automatically falls back to the system voice (and tells you why).
- **System voice (fallback):** the **Voice** list below the neural switch uses
  your OS/browser's voices — the *JARVIS (Avengers)* preset is a deep, slowed
  British voice. This is also what Hindi replies and the phone's "Yes, Sir?"
  wake-up use.
- **Talk in Hindi:** JARVIS answers in Hindi (Devanagari) whenever you speak or
  write in Hindi, and the reply is read out in a Hindi voice automatically,
  whatever voice preset is selected. If auto-detection guesses wrong, set
  **Speech language** in the sidebar to force Hindi or English.
- If a browser blocks auto-play audio, press **🔊 Replay last reply**.
- **It talks while it writes (flowing voice).** The answer streams into the chat
  as it is written, and JARVIS speaks each finished sentence the moment it is
  ready — he starts talking a second or two in, not after the whole answer is
  done. While he is answering, a **⏹ Stop** button appears; press it and he
  stops mid-answer — what he already said and wrote is kept.
- **The desktop app comes online by itself.** When the packaged app starts with
  your key saved in `.env`, JARVIS initializes on its own — no click needed. (On
  the hosted web version you press **INITIALIZE JARVIS** once.)

### Vision — JARVIS sees 👁
JARVIS can look at pictures — and, on the desktop app, at your screen — using a
**free Google Gemini key** (separate from your Groq key, which stays text-only).

1. Get a free key at <https://aistudio.google.com/apikey> (sign in with any
   Google account, *Create API key*, copy it). The free tier is plenty — images
   cost nothing at normal use.
2. In the sidebar open **👁 Give JARVIS vision (Gemini)** and paste the key.
   On the desktop app it is saved to `.env` so it survives restarts; on the
   hosted version put `GEMINI_API_KEY` in Streamlit Secrets instead. The key is
   never shown back — the sidebar only says *Vision on*.
3. Use it three ways:
   - **Attach a picture:** in the sidebar *📷 Show JARVIS an image* → choose a
     file → ask e.g. *"what is written in this chart?"*.
   - **Ask about your screen** (desktop app): *"look at my screen — read the
     error"* or *"what's on my screen?"* — JARVIS takes the screenshot himself.
   - **By path:** *"look at C:\Users\me\Desktop\receipt.png and tell me the
     total"* — he reads files in your own folders only.

- **Your image goes straight to Google, nowhere else.** Only the answer text
  comes back through Groq. Images are sent with your own Gemini key and are not
  stored by JARVIS.
- GIF and BMP files are converted to PNG automatically; files over 8 MB are
  refused with a friendly message.
- Until a key is set, JARVIS answers image questions "blind" and says so.

### Proactivity — briefing & alerts 🌅

JARVIS doesn't only answer — he speaks up on his own. Open **🌅 Proactivity —
briefing & alerts** in the sidebar:

- **🌅 Morning briefing.** Once a day, after the hour you choose (05:00–11:00),
  JARVIS greets you with the date, your open follow-ups ("2 things today — call
  Ali at 18:00…"), your unread mail count and your unread WhatsApp chats. It
  arrives as a chat message, a native popup and — with voice on — as speech. It
  fires once per day; if the app was closed at the set hour, you get it at the
  next start.
- **📬 New-mail alerts.** Needs email connected (above). JARVIS quietly checks
  the inbox every couple of minutes (*read-only*, like all email) and tells you
  the moment something new arrives: *"📬 New mail from Ali — subject"*. The
  first check never alerts on existing mail — only what arrives **after** you
  switch it on.
- **💬 New WhatsApp-message alerts.** Needs WhatsApp linked (above). While the
  app is open, JARVIS peeks at the WhatsApp sidebar every minute or so and
  speaks up the moment a chat's unread count grows: *"💬 New WhatsApp from
  Ali — meeting moved to 6"*. Pure sidebar peek — **nothing is ever marked as
  read**. The first check never alerts on existing unread; messages that
  arrived while the app was closed are announced once it runs again.
- All settings live in `~/.jarvis/proactive.json` and survive restarts. The
  briefing and both watchers run inside the JARVIS app, so the app must be
  running (the wake-word listener alone will not deliver them).

### WhatsApp — read & send by name 💬 (local desktop only)

JARVIS drives **your own WhatsApp** through WhatsApp Web, in a small separate
Edge window — your normal browser and your phone stay untouched:

- **One-time link.** Open **💬 Link WhatsApp (one-time QR)** in the sidebar →
  **Open WhatsApp login** → scan the QR with your phone (WhatsApp → Settings →
  **Linked devices** → **Link a device**). The link lasts for weeks; JARVIS
  reuses the same window whenever you ask.
- **See your messages.** *"check my whatsapp"* (unread chats) · *"what did Ali
  say?"* · *"read my last messages with Ali"*.
- **Send by name — no number needed.** *"send whatsapp to Ali saying I will
  reach the clinic by 10"* — JARVIS searches the name in WhatsApp, opens the
  right chat (and tells you exactly which contact it picked), types the message
  and delivers it. It re-reads the chat afterwards to confirm the message went
  out, and says so.
- **Deliberate by design.** It sends only when you ask, to the contact you
  named; it reports the resolved contact name so a near-match never goes to the
  wrong person.
- If the link drops or the window was closed, JARVIS says how to relink instead
  of guessing. Session state lives in `~/.jarvis/` (`wa-edge` profile +
  `wa_cdp.json`); the sidebar shows *💬 WhatsApp linked* while connected.

### WhatsApp Cloud API — a business number that answers itself 🟢

The official **Meta WhatsApp Cloud API** channel, for a WhatsApp *Business*
number. No browser window, no QR code — JARVIS talks to Meta's Graph API
directly, so it also works when nobody is sitting at the PC.

| | WhatsApp Web (above) | Cloud API (this) |
|---|---|---|
| Account | your personal WhatsApp | a Business number you own |
| Reach | any of your contacts | numbers that are saved, or that messaged you |
| Reads your chats | yes | no — only what arrives at the business number |
| Works headless | needs the Edge window | yes |

**What it does**

- **Send by name or number.** *"whatsapp Ali on the business number that the
  report is ready"* → `whatsapp_business_send`. Save people once with
  *"save Ali's whatsapp number as 919876543210"* and names work from then on.
- **Templates.** *"send the appointment_reminder template to Ali with his name
  and the time"* → `whatsapp_business_template`. A template is the **only** way
  to open a conversation with someone who has not messaged the business in the
  last 24 hours — Meta enforces that, and JARVIS explains it rather than
  failing silently.
- **Broadcast.** *"tell everyone on whatsapp the clinic is closed tomorrow"* →
  `whatsapp_business_broadcast` (whole contact book or a named list). JARVIS
  confirms before sending to more than two people.
- **Replies on its own.** Turn on **🤖 JARVIS answers incoming messages** and
  every message that lands on the business number gets an automatic answer.
  That responder runs **with no tools at all** — a stranger on WhatsApp can
  never reach your files, apps, mailbox or browser.
- **Reads them back to you.** *"who messaged us on whatsapp"* →
  `whatsapp_business_inbox`, and each arrival also appears in the chat window
  and is spoken aloud.
- **Pushes your alerts to your phone.** In 🌅 Proactivity, switch on *send the
  briefing / follow-up reminders to my WhatsApp*.

**One-time setup (about 10 minutes, on Meta's site)**

1. <https://developers.facebook.com> → **Create app** → type **Business** →
   add the **WhatsApp** product.
2. **WhatsApp → API Setup** gives you a *temp* token, a **Phone number ID** and
   a **WhatsApp Business Account ID**. The test number can only message **5
   recipient numbers you verify** there.
3. Make the token **permanent** (temp ones expire in ~24 h): Business Settings
   → **Users → System Users** → create a user with *Admin* → **Generate new
   token** → pick your app → add the `whatsapp_business_messaging` and
   `business_management` permissions → **no expiry**. Copy it.
4. In JARVIS: sidebar → **🟢 Meta WhatsApp Cloud API** → paste the token, the
   Phone Number ID and the Business Account ID → **Connect & test**. JARVIS
   asks Meta to confirm and shows your verified business name. Tick
   **Remember on this PC** to keep it in `~/.jarvis` (never in the project
   folder), or put it in `.env` instead.
5. **To receive messages** Meta needs a public HTTPS address, and the honest
   options are not equal:

   - **Hosted (recommended).** Deploy this same `app.py` somewhere public
     (Streamlit Cloud works — it is already in this repo) and put the
     `JARVIS_WA_*` values in that host's secrets. A hosted copy has **no PC
     control at all** by design, so a business number answering strangers is
     exactly what it is safe to expose. Register Meta's webhook against that
     address.
   - **Tunnel from this laptop.** Tick **⚠ Allow public access** and press
     **Start public tunnel** — JARVIS fetches Cloudflare's free `cloudflared`,
     opens the tunnel and prints the callback URL. **Read the warning first:**
     a quick tunnel publishes every route on this port to the internet, not
     just the webhook, and on the desktop build that port serves the assistant
     *with* your file, app and PC tools. Anyone who reaches that address can
     use JARVIS on your laptop. So the tunnel also refuses to start until the
     **App secret** field is filled in — without it Meta's deliveries cannot be
     signature-checked and anyone finding the address could feed JARVIS forged
     messages from any number.

   Paste the callback URL into **WhatsApp → Configuration → Webhook** with the
   verify token shown next to it, then subscribe to the **messages** field.
   (Skip this step if you only want to send.)

**Files it writes** (all in `~/.jarvis/`, nothing secret unless you tick
*Remember*): `wa_cloud_prefs.json`, `wa_cloud_contacts.json`,
`wa_cloud_inbox.json`, `wa_cloud_outbox.json` (a trail of everything JARVIS
sent: number, truncated text, status, Meta's message id or refusal reason),
optionally `wa_cloud.json`.

**Cost.** Meta charges per message category: user-initiated *service*
conversations inside the 24-hour window are free, business-initiated
*marketing/utility/authentication* templates are billed. Check Meta's current
rates before a large broadcast.

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
- **Dictated commands are never missed.** A hidden heartbeat in the page checks
  for your command every few seconds, so even if a long answer has stalled the
  app's own update loop, a command you dictate is picked up and answered within
  a few seconds.
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
- 🖥 "Open Notepad." / "Open WhatsApp and message Ali saying I'll be late."
- 🖥 "Search YouTube for stomach exercises and show me." / "What files are on my Desktop?"
- 🖥 "Save these notes to Documents/clinic-notes.md."
- ⏰ "Remind me to follow up with the lab tomorrow at 10." / "What follow-ups are open?"
- ⏰ "Mark the lab one done." / "Remind me to check the register in 30 minutes."
- 🧠 "Save this: Dr. Sharma prefers evening appointments." / "What do you remember about me?"
- ✉️ "Any new emails?" / "How many unread messages do I have?" / "Check for mail from Ali."
- 💬 "Check my whatsapp." / "What did Ali say?" / "Send whatsapp to Dr. Sharma saying the meeting moved to 5."
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
├── system_control.py # sandboxed PC tools (apps, websites, files)
├── whatsapp_control.py # WhatsApp Web via Edge CDP — read chats & send by contact name
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
- **JARVIS can't see?** Vision needs a (free) Gemini key — open
  **👁 Give JARVIS vision (Gemini)** in the sidebar and paste one from
  <https://aistudio.google.com/apikey>. Until then it answers image questions
  "blind" and says so. A rejected key is reported right in its reply.
- **No briefing / no mail alerts?** The briefing waits until the clock passes the
  hour you picked (sidebar → **🌅 Proactivity**) and fires once a day — closed app
  means it arrives at the next launch. Mail alerts need email connected *and* the
  toggle on; the first run never announces existing mail, only what arrives from
  then on. Both need one page load after switching on, and the app must stay open.
- **WhatsApp not linked?** Open **💬 Link WhatsApp (one-time QR)** in the sidebar
  and scan once (WhatsApp → Settings → Linked devices → Link a device). The
  separate Edge window must stay logged in — if the sidebar says *Waiting for
  the scan*, refresh the QR window. Sending/reading needs the app running on
  the desktop; the hosted web version has no WhatsApp.
- **Nothing wakes after a reboot?** Sign-in starts the listener, but a PC that is
  powered off or hibernated cannot hear you — while listening, JARVIS only asks
  Windows not to *sleep* (the display still switches off as usual).
- **Where is my wake-word state kept?** `~/.jarvis/` — `wake_config.json` (your
  wish + where JARVIS lives), `wake_status.json` (live listener status),
  `wake_command.json` (the last dictated command), `wake_listener.log`. Memories
  live in `memory.json`, follow-ups in `followups.json` and the briefing /
  mail-alert settings in `proactive.json` in the same folder.
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
4. In **Settings → Secrets**, add one line per value, named exactly as in
   `.env`:
   ```toml
   GROQ_API_KEY    = "gsk_your_key_here"
   GEMINI_API_KEY  = "your_gemini_key"
   JARVIS_WA_TOKEN = "your_permanent_meta_token"
   JARVIS_WA_PHONE_ID = "123456789012345"
   JARVIS_WA_WABA_ID  = "987654321098765"
   JARVIS_WA_APP_SECRET = "your_app_secret"
   ```
   Never put a real key in the repo. The app reads `st.secrets` *and* `.env`
   because Community Cloud does **not** expose Secrets as environment variables
   - a `JARVIS_WA_*` value reachable only through `os.environ` would be
   invisible to the hosted copy, and WhatsApp would look unconfigured there.
5. Your JARVIS is live at `https://<app>.streamlit.app`.

> Voice input (mic) and the wake word work in the deployed web version too, in
> Chrome/Edge. The packaged `.exe` remains the offline/desktop option.
