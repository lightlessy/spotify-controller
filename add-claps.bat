@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Once install.bat dosyasini calistir.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" add_claps.py
pause
