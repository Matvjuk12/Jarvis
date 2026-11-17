# Configuration

Jarvis reads settings from environment variables. The easiest way to set them is the app's **Settings** tab
(it edits `.env` for you and restarts the engine), or edit `.env` by hand. Copy `.env.example` to `.env` first.

* Empty values are ignored (the default is used).
* Changes need an engine restart (Settings → *Save and restart*, or tray → Quit and start again).
* Real environment variables take precedence over `.env`.

## LLM providers

Providers are tried from strongest to weakest. If one hits a rate limit or errors, Jarvis automatically moves to the
next key/provider and keeps the conversation context.

| Variable | Provider | Default model |
|---|---|---|
| `GROQ_API_KEY` | Groq | `openai/gpt-oss-120b` |
| `GEMINI_API_KEY` | Google Gemini | `gemini-2.5-flash` |
| `OPENROUTER_API_KEY` | OpenRouter | a `:free` model |
| `CEREBRAS_API_KEY` | Cerebras | `llama-3.3-70b` |
| `MODELSCOPE_API_KEY` | ModelScope | Qwen family |
| `SILICONFLOW_API_KEY` | SiliconFlow | `Qwen/Qwen2.5-7B-Instruct` |
| `ZHIPU_API_KEY` | Zhipu / GLM | `glm-4-flash` |
| `OLLAMA_ENABLED=1` | Local Ollama | `OLLAMA_MODEL` (default `qwen2.5:7b`) |

**Multiple keys.** Put several keys in one variable separated by commas (`GROQ_API_KEY=key1,key2`) or use numbered
variables (`GROQ_API_KEY_1`, `GROQ_API_KEY_2`, …). Jarvis rotates between them.

**Overriding models.** Providers rename or retire models. Set `<PROVIDER>_MODEL`, e.g. `GROQ_MODEL=openai/gpt-oss-20b`.
If a model returns "not found", Jarvis tries to pick a working one from the provider's model list automatically.

## Speech recognition

| Variable | Default | Description |
|---|---|---|
| `LANGUAGES` | `ru,en` | Languages Whisper may detect. One value (`ru` or `en`) forces that language. |
| `WHISPER` | `1` | `0` disables Whisper (Vosk-only, lower accuracy). |
| `WHISPER_MODEL` | `small` | `tiny`, `base`, `small`, `medium`, `large-v3-turbo`. Bigger = more accurate and slower. `tiny` often garbles the wake word; prefer `base` or `small`. |
| `WHISPER_DEVICE` | `cpu` | `cpu` or `cuda`. |
| `WHISPER_COMPUTE` | `int8` | Compute type (e.g. `int8`, `float16` on GPU). |
| `VOSK_MODEL` | `./model` | Path to an unpacked Vosk model (optional; only used for live text while speaking). |
| `MIC_DEVICE` | system default | Input device number or name; list devices with `python jarvis.py --mic-test`. |
| `MIC_THRESHOLD` | `250` | Minimum loudness (RMS) treated as speech. Lower for quiet mics, raise in noisy rooms. |
| `END_SILENCE` | `0.9` | Seconds of silence that end a phrase. |

## Activation and the edit window

| Variable | Default | Description |
|---|---|---|
| `WAKE_MODE` | `open` | `open`: react to any phrase. `hybrid`: wake word for everything, but known quick commands work without it. `strict`: only after the wake word. |
| `WAKE_WORDS` | `джарвис,жарвис,чарвис,джервис,джарви,jarvis` | Comma-separated. Matching is **phonetic and script-independent**, so `jarvis` also matches "Джарвис". |
| `AUTO_SEND_SECONDS` | `3` | Countdown before the recognized text runs. Clicking the text or dragging the window stops it. |
| `EDIT_WINDOW` | `1` | `0` removes the edit window: commands run instantly. With `1` and `AUTO_SEND_SECONDS=0`, a 3-second countdown is used. |
| `POPUP_POS` | `right-bottom` | `right/left` + `top/middle/bottom`. Overridden once you drag the window (position saved in `~/.jarvis/popup_pos.json`; delete it to reset). |
| `POPUP_WIDTH` | `440` | Window width in pixels. |

## Voice (text-to-speech)

| Variable | Default | Description |
|---|---|---|
| `TTS_ENGINE` | `edge` | `edge` = Microsoft Edge neural voices (online); `pyttsx3` = Windows built-in voices (offline). |
| `EDGE_VOICE_RU` | `ru-RU-DmitryNeural` | Voice for Russian replies. |
| `EDGE_VOICE_EN` | `en-GB-RyanNeural` | Voice for English replies (the "Iron Man" British male). |
| `EDGE_VOICE` | – | Legacy single voice; used only when its language matches the reply (a British voice cannot read Russian). |
| `TTS_RATE_EDGE` | `-5%` | Speaking rate, e.g. `-10%` calmer, `+10%` faster. |
| `TTS_PITCH` | `-2Hz` | Pitch offset. |
| `TTS_RATE` | `165` | Speed for `pyttsx3`. |
| `TTS_FALLBACK` | `1` | `0` = if Edge fails, stay silent instead of using the offline voice. |

List available Edge voices with `edge-tts --list-voices`.

## Misc

| Variable | Default | Description |
|---|---|---|
| `JARVIS_PORT` | `47615` | Local port used by the GUI to talk to the engine (127.0.0.1 only). |

## Files Jarvis creates

| Path | Purpose |
|---|---|
| `%USERPROFILE%\.jarvis\jarvis.log` | Engine log (open from the app's *Log* tab or tray). |
| `%USERPROFILE%\.jarvis\engine-launch.log` | Output captured when the app launches the engine. |
| `%USERPROFILE%\.jarvis\token` | Secret token the GUI needs to talk to the engine. Never share it. |
| `%USERPROFILE%\.jarvis\popup_pos.json` | Saved position of the edit window. |
| `Pictures\Jarvis\` | Screenshots. |
| `Documents\Jarvis\notes.txt` | Notes added by voice. |
