@echo off
cd /d "%~dp0"
echo === Jarvis setup ===
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Some packages failed to install. Jarvis may still work; if faster-whisper failed,
  echo install Python 3.12 or 3.13, or set WHISPER=0 in .env.
)
if not exist .env copy .env.example .env >nul
python jarvis_gui.py --install-shortcut
echo.
echo Done. Open "Jarvis" from the Desktop or Start menu, then add API keys on the Settings tab.
pause