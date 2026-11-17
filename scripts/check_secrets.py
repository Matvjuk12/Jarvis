#!/usr/bin/env python3
"""Leak guard: refuses commits that contain API keys or a real .env file.

Usage
    python scripts/check_secrets.py          # scan files staged for commit (used by the git hook)
    python scripts/check_secrets.py --all    # scan every tracked file

Enable the hook once per clone:
    git config core.hooksPath .githooks
"""
import re
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "Groq key": re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    "OpenRouter key": re.compile(r"sk-or-(?:v1-)?[A-Za-z0-9]{20,}"),
    "Google API key": re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_\-]{32,}"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"),
    "Private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    # ENV-style assignment with a long literal value, e.g. GROQ_API_KEY=abc... (upper-case names only,
    # so ordinary code such as `token = token_file.read()` is not flagged)
    "Key assignment": re.compile(
        r"(?m)^\s*[A-Z][A-Z0-9_]*(?:API_KEY|SECRET|TOKEN)[A-Z0-9_]*\s*=\s*['\"]?[A-Za-z0-9_\-./+]{20,}"),
}
FORBIDDEN_NAMES = {".env", "token"}          # real secrets files must never be committed
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".mp3", ".pdf", ".bin"}
SELF = Path(__file__).resolve()


def git(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line.strip()]


def main() -> int:
    scan_all = "--all" in sys.argv
    try:
        files = git("ls-files") if scan_all else git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"check_secrets: cannot run git ({e})")
        return 0
    problems = []
    for name in files:
        p = Path(name)
        if p.name in FORBIDDEN_NAMES:
            problems.append(f"{name}: secrets file must not be committed")
            continue
        if p.suffix.lower() in SKIP_SUFFIXES or not p.is_file() or p.resolve() == SELF:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, pat in PATTERNS.items():
            m = pat.search(text)
            if m:
                line_no = text.count("\n", 0, m.start()) + 1
                shown = m.group(0).strip()[:12] + "…"
                problems.append(f"{name}:{line_no}: looks like a {label} ({shown})")
    if problems:
        print("✗ Possible secrets found — commit blocked:\n")
        print("\n".join("  " + x for x in problems))
        print("\nRemove them (keep keys only in .env, which is git-ignored), then commit again."
              "\nIf a key was already exposed anywhere, revoke it at the provider and create a new one.")
        return 1
    print("✓ check_secrets: no secrets found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
