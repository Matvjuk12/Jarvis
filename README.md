<div align="center">

<img src="assets/jarvis.jpg" alt="Jarvis" width="360">

# Jarvis for Windows

**A free, bilingual (Russian / English) voice assistant and desktop agent that actually controls your PC.**

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D4)
![License](https://img.shields.io/badge/license-MIT-green)
![Cost](https://img.shields.io/badge/API%20cost-free%20tiers-brightgreen)

</div>

Say *"Jarvis, open Telegram"*, *"volume 30"*, *"find my invoice PDFs on the desktop and zip them"* or
*"install VS Code"* — in Russian or English. Jarvis listens in the background, shows what it heard in a small
**editable window** (fix a misheard word before it runs), and then executes the command using fast offline
shortcuts or a free LLM that chains tools together.

> **Disclaimer.** Inspired by the fictional J.A.R.V.I.S. This is an independent hobby project and is not
> affiliated with Marvel or Disney.

---

## Features

| | |
|---|---|
| 🎙️ **Always-on, bilingual listening** | Voice-activity detection + offline **Whisper** (faster-whisper) for accurate Russian *and* English; optional **Vosk** for live text while you speak. |
| ✏️ **Editable recognition window** | Your words appear in a small draggable window. Click to correct, <kbd>Enter</kbd> to run now, <kbd>Esc</kbd> to cancel — or let the countdown run. The window remembers where you put it. |
| 🧠 **Free LLM agent** | Works with free API tiers (Groq, Gemini, OpenRouter, Cerebras, ModelScope, SiliconFlow, Zhipu) or fully local Ollama. Multiple keys per provider, automatic failover on rate limits. |
| ⚡ **Instant offline commands** | Common phrases ("open notepad", "mute", "screenshot", "what time is it") run immediately without calling any model. |
| 🖥️ **Deep Windows control** | Apps, windows, mouse & keyboard, UI Automation (click buttons inside apps), files and folders, processes, services, registry, winget installs, brightness, dark mode, wallpaper, network, notes, alarms, PowerShell. |
| 🔊 **Natural voice** | Microsoft Edge neural voices (Iron-Man-style British male / Russian male) with automatic offline fallback. |
| 🛡️ **Safety rails** | Destructive actions (delete, shutdown, registry, installs, PowerShell…) ask for confirmation by voice, button, or chat. Protected system folders and catastrophic commands are guarded. |
| 🧩 **Easy to extend** | Drop a Python file into `plugins/`, decorate a function with `@command` — it becomes both a voice shortcut and an LLM tool. |
| 🪟 **Background engine + GUI** | The engine runs silently in the tray; a separate app gives you chat, settings, logs and start/stop. Closing the app doesn't stop Jarvis. |

## How it works

```
 microphone ─► VAD ─► Vosk (live text) ┐
                  └─► Whisper (final) ─┴─► activation filter ─► edit window ─► handle()
                                                                                  │
                                       fast offline phrase match ◄────────────────┤
                                       LLM agent + tools (free providers) ◄───────┘
                                                      │
 GUI app ◄── local socket (127.0.0.1, token) ──► engine ──► Edge TTS / pyttsx3 ──► speakers
```

More detail in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start

**Requirements:** Windows 10/11, Python 3.10+ (3.11–3.13 recommended), a microphone, and internet for the LLM,
Edge voice and the first Whisper model download.

1. **Get the code**
   ```bat
   git clone https://github.com/<your-user>/<your-repo>.git
   cd <your-repo>
   ```
2. **Install** — double-click `install.bat` (installs packages, creates a desktop/Start-menu shortcut), or run:
   ```bat
   python -m pip install -r requirements.txt
   python jarvis_gui.py --install-shortcut
   ```
3. **Create your config**
   ```bat
   copy .env.example .env
   ```
   Open `.env` (or the app's **Settings** tab) and paste at least one free API key — see
   [Getting free API keys](#getting-free-api-keys).
4. *(Optional)* **Live text while speaking:** download `vosk-model-small-ru-0.22` from
   <https://alphacephei.com/vosk/models> and unpack it into a folder named `model` next to `jarvis.py`.
5. **Run** — open the **Jarvis** shortcut. The app starts the background engine automatically
   (tray icon near the clock). On the first start Whisper downloads its model (`small` ≈ 0.5 GB) — this takes a
   minute or two, once.
6. **Try it:** say *"Jarvis, what time is it?"* A small window shows your words, then Jarvis answers.

Tick **Run with Windows** in the app to start the engine at login.

### Getting free API keys

You need **one** key; more keys = more headroom. Free tiers and their limits change — check each dashboard.

| Provider | Where to get a key | Notes |
|---|---|---|
| Groq | <https://console.groq.com/keys> | Very fast; strong tool calling |
| Google Gemini | <https://aistudio.google.com/apikey> | Also enables screen "vision" |
| OpenRouter | <https://openrouter.ai/keys> | Models tagged `:free` |
| Cerebras | <https://cloud.cerebras.ai> | Fast, generous free tier |
| ModelScope / SiliconFlow / Zhipu | provider sites | Often reachable without a VPN in some regions |
| Ollama (local) | <https://ollama.com> | No key, no limits — set `OLLAMA_ENABLED=1` |

> 🔐 **Never commit your `.env`.** It is git-ignored; see [SECURITY.md](SECURITY.md) for how keys are protected
> and what to do if one leaks.

## Using Jarvis

**Voice.** Speak naturally. By default Jarvis reacts to any phrase (`WAKE_MODE=open`). Prefer a wake word?
Set `WAKE_MODE=strict` and `WAKE_WORDS=jarvis,джарвис` — matching is phonetic, so "Jarvis" / "Джарвис" / "Жарвис"
all work.

| Say | Result |
|---|---|
| "Open Telegram" / "Открой телеграм" | Launches any installed app (fuzzy-matches the Start menu, Russian names too) |
| "Volume 40", "mute", "louder" | System volume |
| "Take a screenshot" | Saves to `Pictures\Jarvis` |
| "Switch to Chrome", "show desktop" | Window control |
| "What's the weather in Berlin?" | Live weather |
| "Find PDFs in Documents" | File search |
| "Delete old-report.docx from the desktop" | Asks for confirmation, moves to Recycle Bin |
| "Install Telegram" | winget search + install (asks first) |
| "Note: buy milk" | Appends to `Documents\Jarvis\notes.txt` |

Full list: [docs/COMMANDS.md](docs/COMMANDS.md).

**The edit window.** After you speak, your text appears in a small window (bottom-right by default). Drag it by the
top bar anywhere on screen — the position is remembered. Click the text to fix it; <kbd>Enter</kbd> runs it,
<kbd>Esc</kbd> cancels. Otherwise it runs automatically after `AUTO_SEND_SECONDS` (default 3).

**The app.** *Chat* (voice and typed history, tool calls, live text), *Settings* (keys, languages, Whisper model,
voice, popup position), *Log*. Tray menu: open window, type a command, reload commands, open log, quit.

## Configuration

Everything is configured through environment variables in `.env` (or the Settings tab). The essentials:

```ini
GROQ_API_KEY=            # one or more keys, comma-separated
WAKE_MODE=open           # open | hybrid | strict
WAKE_WORDS=jarvis,джарвис
LANGUAGES=ru,en
WHISPER_MODEL=small      # tiny | base | small | medium | large-v3-turbo
TTS_ENGINE=edge          # edge | pyttsx3
```

All options: [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Extending Jarvis

```python
# plugins/my_commands.py
from jarvis_core import command, confirm

@command(phrases=[r"open my project (?P<name>.+)", r"открой проект (?P<name>.+)"])
def open_project(name: str):
    """Open a project folder in VS Code by name."""
    ...
    return f"Opening {name}"
```

Say *"reload commands"* and it works — as a voice shortcut **and** as a tool the LLM can call. Guide:
[docs/PLUGINS.md](docs/PLUGINS.md).

## Project structure

```
jarvis.py          background engine (listening, recognition, agent, voice, popup, tray)
jarvis_gui.py      control panel: chat, settings, log, start/stop, shortcuts
jarvis_core.py     command registry, tool groups, helpers for plugins
plugins/           built-in commands + your own (my_commands.py)
docs/              documentation
scripts/           check_secrets.py (leak guard)
.env.example       configuration template (safe to commit)
install.bat        one-click setup
```

## Privacy & safety

* Speech recognition runs **locally** (Whisper/Vosk); audio never leaves your PC.
* Your command *text* is sent to the LLM provider you configured; reply text is sent to Microsoft for Edge TTS
  (use `TTS_ENGINE=pyttsx3` to stay offline). `describe_screen` sends a screenshot to Google Gemini — only when you
  ask for it.
* Jarvis can control your computer. Read [SECURITY.md](SECURITY.md) before enabling it on a machine you care about.

## Troubleshooting

No reaction, wrong voice, missing window, install errors → [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).
Quick check of your mic and recognition: `python jarvis.py --mic-test`.

## Contributing

Issues and pull requests are welcome. Please run `python -m py_compile jarvis.py jarvis_gui.py jarvis_core.py plugins/*.py`
before submitting, and never include real keys or logs with personal data. Enable the leak guard once:
`git config core.hooksPath .githooks`.

## License

[MIT](LICENSE).
