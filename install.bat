@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher was not found. Please install Python 3.11 first.
  pause
  exit /b 1
)
py -3.11 --version >nul 2>nul
if errorlevel 1 (
  echo Python 3.11 was not found. Install it from python.org.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" py -3.11 -m venv .venv
if not exist ".venv\Scripts\python.exe" (
  echo Could not create virtual environment.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Could not install Python dependencies.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 (
  echo Could not install Chromium for automated search.
  pause
  exit /b 1
)
where ffprobe >nul 2>nul
if errorlevel 1 echo Warning: ffprobe not found. Install FFmpeg and add to PATH.
echo Installation completed.
pause
