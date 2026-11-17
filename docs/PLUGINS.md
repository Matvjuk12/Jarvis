# Writing plugins

Every `*.py` file in `plugins/` is loaded at startup (files starting with `_` are skipped). A function decorated with
`@command` becomes:

1. a **tool** the LLM can call (its docstring is the description, its type hints become the JSON schema), and
2. optionally an **instant voice shortcut** (regular expressions, no model needed).

Edit a plugin, then say *"reload commands"* (or use the tray menu / Settings button) — no restart needed.

## Minimal example

```python
# plugins/my_commands.py
import webbrowser
from jarvis_core import command

@command(phrases=[r"play my music", r"включи музыку"])
def play_my_music():
    """Open my favourite playlist in the browser."""
    webbrowser.open("https://www.youtube.com/results?search_query=lofi+hip+hop")
    return "Playing music"          # whatever you return is spoken and shown in the chat
```

## `@command` options

| Option | Meaning |
|---|---|
| `phrases=[...]` | Regexes matched against the **whole** recognized phrase (case-insensitive). Named groups `(?P<name>...)` are passed as arguments. |
| `name="..."` | Tool name (default: function name). |
| `priority=0` | Higher runs first. Use negative values for greedy catch-alls like `open (?P<name>.+)`. |
| `group="core"` | Tool group. `core` is always sent to the model; other groups are sent when relevant (see below). |

**Arguments.** Supported types: `str`, `int`, `float`, `bool`, `list[str]`, and `X | None`. Parameters without a default
are required. Regex groups arrive as strings — convert if needed (`int(level)`).

**Return value.** Return a short string; it is spoken. Returning `None` yields "Done." Raised exceptions are caught and
reported as errors, so you can let them propagate.

## Helpers from `jarvis_core`

| Helper | Use |
|---|---|
| `say(text)` | Speak something proactively (timers, alarms). |
| `confirm(question) -> bool` | Ask yes/no by voice, button or chat. **Use it before anything destructive.** |
| `resolve_path(text)` | Turns "desktop/report.txt", "documents", `~\x`, `%TEMP%` into a real `Path`. |
| `known_folder(name)` | Windows known folders: `desktop`, `documents`, `downloads`, `pictures`, `music`, `videos`. |
| `is_protected(path)` | True for Windows/Program Files/ProgramData. |
| `run_ps(script, timeout=60)` | Run PowerShell and get UTF-8 output. |
| `register_group(name, description, keywords)` | Declare a tool group (see below). |

## Tool groups (saving free-tier tokens)

Sending 80+ tool schemas on every request would burn through free quotas, so tools live in groups. A group is sent to
the model when one of its **keywords** appears in the user's phrase; the model can also unlock a group itself through the
built-in `more_tools(group)` tool.

```python
from jarvis_core import command, register_group

register_group("spotify", "Control Spotify playback", ["spotify", "playlist", "плейлист"])

@command(group="spotify")
def spotify_next():
    """Skip to the next Spotify track."""
    ...
```

## Tips

* Keep docstrings short and concrete — they are the model's only documentation of your tool.
* Add Russian *and* English `phrases` if you want instant shortcuts in both languages.
* Prefer returning information over raising errors, and keep side effects obvious.
* For anything irreversible: `if not confirm("Really delete X?"): return "Cancelled"`.
* Test regexes against the lowercase, punctuation-free text Whisper produces (`open telegram`, not `Open Telegram!`).
