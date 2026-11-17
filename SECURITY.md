# Security policy

Jarvis can launch programs, press keys, read and write files, run PowerShell and install software on your PC.
Treat it like any powerful automation tool and read this page before using it on a machine you care about.

## What protects you

* **Confirmations.** Destructive or sensitive tools ask first (by voice, on-screen buttons, or in the app): deleting files,
  overwriting files, power actions, killing processes, services, registry writes, winget installs/upgrades, emptying the
  Recycle Bin, restarting Explorer and **all PowerShell commands**. No answer within ~25 s means "no".
* **Protected locations.** Writes/moves/copies inside `Windows`, `Program Files` and `ProgramData` require confirmation.
  Critical Windows processes can't be killed.
* **Blocked commands.** PowerShell input containing catastrophic patterns (`format-volume`, `clear-disk`,
  `remove-partition`, `diskpart`, `bcdedit`, `vssadmin delete`, `cipher /w`, …) is refused. This is a safety net, not a
  sandbox — a determined user or model can still do harm with the other tools.
* **Recycle Bin.** `delete_path` moves items to the Recycle Bin rather than deleting permanently.
* **Local-only control channel.** The engine listens on `127.0.0.1` and requires a random secret
  (`%USERPROFILE%\.jarvis\token`) from every client. Other programs and web pages can't send it commands without that
  token. Don't share that file.

## What leaves your computer

| Data | Sent to | When |
|---|---|---|
| Microphone audio | **nowhere** (Whisper/Vosk run locally) | never |
| Text of your commands + tool results | the LLM provider(s) you configured | when a request needs the model |
| Reply text | Microsoft (Edge TTS) | when `TTS_ENGINE=edge` (use `pyttsx3` for offline) |
| Screenshot | Google Gemini | only when you ask "what's on my screen" |
| Web lookups | DuckDuckGo / the sites you ask for / wttr.in | when you use those tools |

Free API tiers may log or use prompts according to the provider's terms. Don't dictate passwords, tokens or personal data.

## Protecting your API keys

1. Keys live only in `.env` on your machine. `.env` is listed in `.gitignore` — **never commit it**.
2. Commit only `.env.example` (blank values).
3. Enable the leak guard: `git config core.hooksPath .githooks`. It runs `scripts/check_secrets.py` before every commit
   and blocks commits that contain key-like strings or a `.env` file. You can also run
   `python scripts/check_secrets.py --all` at any time.
4. Optionally restrict the file to your Windows account:
   `icacls .env /inheritance:r /grant:r "%USERNAME%:F"`
5. Use separate keys for this project, and rotate (delete + recreate) any key that was ever pasted into a chat, issue,
   screenshot, log or commit.
6. **If a key reached GitHub:** revoke it at the provider **first**, then remove it from history
   (`git filter-repo`/BFG) or delete and recreate the repository. Deleting the file in a later commit does *not* remove it.

## Good practice

* Review plugins before installing them: they run with your user's full rights.
* Keep Jarvis out of shared or untrusted environments; anyone who can speak near the microphone can issue commands
  (consider `WAKE_MODE=strict`).
* Keep Python packages updated (`python -m pip install -U -r requirements.txt`).

## Reporting a vulnerability

Please use GitHub's **private vulnerability reporting** (repository → *Security* → *Report a vulnerability*) rather than a
public issue. Include steps to reproduce and the affected version. Do not include real keys or personal data.
