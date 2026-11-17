# Architecture

Jarvis is two processes that talk over a local socket.

```
┌───────────────────────── engine: jarvis.py (background, tray icon) ─────────────────────────┐
│                                                                                              │
│  sounddevice ─► Listener ──► voice-activity detection (loudness, adaptive noise floor)       │
│                   │              ├─► Vosk  ── live partial text (optional, Russian)           │
│                   │              └─► Whisper ─ final text, ru/en auto-detected                │
│                   ▼                                                                          │
│            activation filter (WAKE_MODE / WAKE_WORDS, phonetic match)                        │
│                   ▼                                                                          │
│            edit window (Tk): live text → editable → countdown / Enter / Esc                  │
│                   ▼                                                                          │
│            handle(text) ──► 1) fast path: regex phrases from plugins (offline)               │
│                         └─► 2) agent: LLM + tools, multi-step, provider failover             │
│                                         │                                                    │
│            plugins/*.py ◄───────────────┘  (jarvis_core registry, tool groups, confirm())    │
│                   ▼                                                                          │
│            speak(): Edge neural TTS (retry) → pyttsx3 fallback                               │
│                                                                                              │
│  IPC server 127.0.0.1:47615 (token auth) ◄──────────────────────────────────┐                │
└──────────────────────────────────────────────────────────────────────────────┼───────────────┘
                                                                               │ JSON lines
┌───────────────────────── app: jarvis_gui.py (Tk) ───────────────────────────┴────────────────┐
│  chat · settings (.env editor) · log viewer · start/stop/restart · confirm dialog · shortcuts │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Components

* **`jarvis.py` — engine.** Owns the microphone, recognition, the agent loop, speech output, the edit window and the
  tray icon. Single instance (named mutex). Runs hidden; the GUI launches it with output captured to
  `~/.jarvis/engine-launch.log`.
* **`jarvis_gui.py` — app.** A pure client: it never touches the microphone or runs commands itself. Closing it leaves
  the engine running.
* **`jarvis_core.py` — registry.** `@command` registration, JSON-schema generation from type hints, tool groups,
  regex fast-path matching, plugin loader, and shared helpers (`confirm`, `say`, `resolve_path`, `run_ps`).
* **`plugins/` — capabilities.** Plain Python files; reloadable at runtime.

## Recognition pipeline

1. The microphone is read in 100 ms blocks. A phrase starts after two consecutive blocks above
   `max(MIC_THRESHOLD, 3 × noise floor)` and ends after `END_SILENCE` seconds of quiet (measured in audio time, so slow
   processing never cuts a phrase short).
2. While you speak, Vosk (if a model is present) streams live text to the edit window and the app.
3. At the end of the phrase Whisper transcribes the audio. With `LANGUAGES=ru,en` it auto-detects the language; if it
   picks something else it re-runs with the first configured language. A prompt with typical commands and hallucination
   filters keep silence/noise from becoming text.
4. The activation filter decides whether the phrase is for Jarvis.

## Agent loop

`agent()` sends the conversation plus the relevant tool groups to the first healthy provider. Tool calls are executed
and results fed back (up to 10 steps). A provider/key that errors goes into a short cooldown and the next one is used;
retired models are replaced automatically from the provider's model list. History is windowed so a tool call is never
separated from its result.

## IPC protocol (engine ⇄ app)

Newline-delimited JSON over `127.0.0.1:JARVIS_PORT`. The client must send `{"token": "<~/.jarvis/token>"}` first;
connections without the correct token are dropped.

| Direction | Message |
|---|---|
| app → engine | `{"t":"chat","text":"…","speak":false}`, `{"t":"confirm_answer","v":true}`, `{"t":"reload"}`, `{"t":"quit"}` |
| engine → app | `hello`, `state` (`loading`/`idle`/`busy`), `live` (partial text), `user`, `reply`, `tool`, `info`, `confirm`, `confirm_done` |

New clients receive the recent chat history on connect.

## Threading

Tk must own its thread, so the engine's main thread runs the edit window; recognition and command execution live in a
worker thread that talks to the window through a job queue. IPC runs in its own threads.
