# Commands reference

Jarvis understands natural language: the LLM picks tools for you. Many common phrases also have **instant offline
shortcuts** (marked ⚡) that don't call any model. Everything below works in Russian too.

Tools are organised in **groups**. Only the relevant groups are sent to the model (saves free-tier tokens); the model
can also unlock a group itself via the built-in `more_tools` tool.

## Core (always available)

| Tool | Examples |
|---|---|
| `open_app` ⚡ | "open Telegram", "launch Discord", "открой хром". Fuzzy-matches installed apps from the Start menu (including Store apps) and understands Russian names. |
| `close_app` ⚡ | "close Chrome" |
| `set_volume` ⚡ | "volume 30", "louder", "quieter", "mute", "unmute" |
| media keys ⚡ | "pause", "play", "next song", "previous track" |
| `take_screenshot` ⚡ | "take a screenshot" → `Pictures\Jarvis` |
| `focus_window` ⚡ | "switch to Chrome" |
| `current_time` ⚡ | "what time is it" |
| `web_search` ⚡ / `open_url` ⚡ | "search for cat videos", "open website github dot com" |
| `set_timer` ⚡ | "timer for 60 seconds" |
| `lock_pc` ⚡ | "lock the computer" |
| `clipboard`, `type_text`, `hotkey` | "type hello world", "press Ctrl+Shift+Esc" |
| `system_info` ⚡ | CPU, RAM, disk, battery |
| `power` | shutdown / restart / sleep — **asks to confirm** |
| `run_powershell` | Anything else — **asks to confirm**; catastrophic commands are blocked |

## `files` — files and folders
`list_dir`, `read_file`, `write_file` (confirms before overwriting), `make_folder`, `copy_path`, `move_path`,
`delete_path` (**always confirms**, moves to Recycle Bin), `find_files`, `open_path`, `reveal_in_explorer`,
`file_info`, `zip_path`, `unzip_file`. Understands "desktop", "documents", "downloads", "pictures", "music", "videos"
(OneDrive-aware) and full paths. Changes inside system folders ask for confirmation.

## `windows` — windows, mouse, keyboard, app UI
`list_windows`, `window_action` (minimize/maximize/restore/close), `show_desktop` ⚡, `mouse_click`, `scroll`,
`press_key`, `screen_size`, and **UI Automation**: `ui_list_controls`, `ui_click`, `ui_type` — click buttons and fill
fields inside other apps by their labels.

## `vision`
`describe_screen` — "what's on my screen?". Sends a screenshot to Google Gemini (needs `GEMINI_API_KEY`).

## `web`
`web_lookup` (search and read results), `fetch_url` (read a page), `weather` ⚡ ("weather in Paris").

## `system` — administration (sensitive actions confirm)
`list_processes`, `top_processes`, `kill_process` (confirms; critical Windows processes are protected),
`service_control`, `registry_get`, `registry_set` (confirms), `installed_programs`, `winget_search`,
`winget_install` (confirms), `winget_upgrade_all` (confirms), `set_brightness`, `dark_mode` ⚡ / `light_mode` ⚡,
`set_wallpaper`, `open_settings` ("open Bluetooth settings"), `empty_recycle_bin` (confirms), `restart_explorer`
(confirms), `network_info`, `ping_host`, `uptime`.

## `notes`
`note_add` ⚡ ("note: buy milk"), `note_read`, `set_alarm` ("alarm at 07:30" — works while Jarvis is running).

## Control commands
* "reload commands" ⚡ — reload `plugins/` after editing.
* "stop jarvis" / "отбой" — shut the engine down.

## Confirmations
Dangerous tools call `confirm()`. You can answer **by voice** ("yes"/"no", "да"/"нет"), with the **buttons** in the
small window, or in the **app** dialog. No answer within ~25 s counts as "no".
