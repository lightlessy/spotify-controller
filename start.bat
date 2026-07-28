@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Once install.bat dosyasini calistir.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" calibrated_detector.py
if errorlevel 1 pause
