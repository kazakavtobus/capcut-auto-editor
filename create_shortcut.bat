@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create_shortcut.ps1"
if errorlevel 1 (
  echo Unable to create the shortcut.
  pause
) else (
  echo Desktop shortcut is ready.
  pause
)
