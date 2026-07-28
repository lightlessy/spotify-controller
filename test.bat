@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Once install.bat dosyasini calistir.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" spotify_snap.py --check
".venv\Scripts\python.exe" feedback_handler.py --check
pause
