@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run install.bat / Сначала запусти install.bat
  pause
  exit /b 1
)
echo WhisperX downloads large ML dependencies and Russian alignment models.
echo Optional: only for Python build; installed EXE may use normal word timestamps.
.venv\Scripts\python.exe -m pip install "whisperx>=3.4,<4"
pause
