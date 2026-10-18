@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run Setup.ps1 first.
  pause
  exit /b 1
)
start "" /b ".venv\Scripts\pythonw.exe" -m forge3d viewer
