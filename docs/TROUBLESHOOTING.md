# Troubleshooting

Always start with the log: `%USERPROFILE%\.jarvis\jarvis.log` (app → *Log* tab, or tray → *Open log*). In a console,
`chcp 65001` first so Cyrillic shows correctly, then `type %USERPROFILE%\.jarvis\jarvis.log`. Lines starting with
`HEARD:` show exactly what recognition produced.

Quick microphone / recognition check: `python jarvis.py --mic-test`.

## Jarvis doesn't react to my voice

1. **Wake word mismatch.** With `WAKE_MODE=strict` Jarvis only reacts after the wake word. Check the log for `HEARD:`
   lines. The match is phonetic (`jarvis` ≈ "Джарвис"), but the `tiny` Whisper model often garbles it — use
   `WHISPER_MODEL=base` or `small`, or switch to `WAKE_MODE=open`.
2. **Wrong microphone.** Run `python jarvis.py --mic-test`, note the device number, set `MIC_DEVICE=<n>`.
3. **Threshold.** The test prints noise and speech levels. If speech peaks below ~300 lower `MIC_THRESHOLD` (e.g. `120`);
   in a noisy room raise it.
4. **Windows privacy.** Settings → Privacy & security → Microphone → allow microphone access and *desktop apps*.
5. **Engine not running.** The app shows *Stopped*? Press **Start**. Check `~/.jarvis/engine-launch.log`.

## The edit window doesn't appear

* `EDIT_WINDOW=0` disables it. Remove that line (or set `1`).
* The window may be off-screen after a monitor change: delete `%USERPROFILE%\.jarvis\popup_pos.json`.
* In `strict` mode it only appears after the wake word.

## Jarvis answers in the "old" robotic voice

That is the offline fallback. Check the log for `Edge-TTS` lines:

| Log message | Fix |
|---|---|
| `NoAudioReceived` | The voice can't read that language (e.g. a British voice with Russian text). Remove `EDGE_VOICE` or use `EDGE_VOICE_RU` / `EDGE_VOICE_EN`. |
| connection / timeout errors | No internet or the service is busy; Jarvis retries once, then falls back. |
| persistent failures | `python -m pip install -U edge-tts` (Microsoft changes its endpoint occasionally). |
| `MCI …` errors | Audio device problem; try another default output device. |

Set `TTS_FALLBACK=0` to stay silent instead of switching voices, or `TTS_ENGINE=pyttsx3` for fully offline speech.

## "The AI is unavailable" / LLM errors

* No key configured → add one in Settings.
* `404 … model not found` → set `<PROVIDER>_MODEL` (e.g. `GROQ_MODEL`) to a current model from your provider's dashboard.
  Jarvis also tries to auto-select a working model.
* `429` / quota → free tiers are limited. Add more keys (`KEY=a,b`) or more providers; Jarvis fails over automatically.
* Region blocks → try another provider (Groq, Cerebras, ModelScope, SiliconFlow, Zhipu) or local Ollama.
* Quick commands (open app, volume, screenshot, time…) keep working without any model.

## Installation problems

* **`faster-whisper` / `ctranslate2` won't install** — usually a Python version without prebuilt wheels. Install Python
  3.11–3.13, or set `WHISPER=0` (lower accuracy; add a Vosk model).
* **`pywinauto` / `pycaw` errors** — upgrade pip first: `python -m pip install -U pip`, then reinstall requirements.
* **`Failed to create a model` (Vosk)** — `model/` must directly contain `am`, `conf`, `graph`, …, not a nested folder.
  Or point `VOSK_MODEL` at the inner folder. Vosk is optional.
* **First start is slow** — Whisper downloads its model once (`small` ≈ 0.5 GB).
* **Files saved with spaces in names** (`jarvis gui.py`) — rename to `jarvis_gui.py`, `jarvis_core.py`, etc.

## The app can't connect to the engine

* Make sure the engine is running (tray icon). Start it from the app or `python jarvis.py`.
* Another program may use port 47615 — set `JARVIS_PORT` to something else (restart both).
* If `%USERPROFILE%\.jarvis\token` was deleted, restart the engine to regenerate it.

## An app didn't open / wrong app opened

`open_app` fuzzy-matches names from the Start menu. Try the exact name ("Visual Studio Code"), or add an alias in
`plugins/computer_control.py` (`RU_NAMES` / `DIRECT`). Classic installers that don't create Start-menu entries may need the
full path (`open C:\Tools\app.exe`).

## Confirmation dialogs

Dangerous actions wait ~25 s for "yes/no" (voice), the buttons in the small window, or the app dialog. Silence = "no".

## Still stuck?

Open an issue with: Windows version, Python version (`python --version`), the last ~50 lines of `jarvis.log`
(**remove anything private**), and what you said vs. what was heard. Never paste API keys.
