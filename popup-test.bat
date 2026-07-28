@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Once install.bat dosyasini calistir.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" overlay_notification.py --event-id 00000000000000000000000000000000 --action next --snap-count 1
if errorlevel 1 pause
