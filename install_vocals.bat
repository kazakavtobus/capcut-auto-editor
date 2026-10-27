@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run install.bat first.
  pause
  exit /b 1
)
echo Installing optional vocal separator Demucs. Requires a large download and free disk space.
".venv\Scripts\python.exe" -m pip install demucs
if errorlevel 1 (
  echo Demucs install failed. You can still use the editor without Demucs.
  pause
  exit /b 1
)
echo Optional vocal separator installed. Check "Separate vocals" in settings.
pause
