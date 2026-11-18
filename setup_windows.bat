@echo off
setlocal
cd /d "%~dp0"
echo [1/4] Checking Python...
py -3.11 --version >nul 2>&1
if errorlevel 1 (
  echo Python 3.11 was not found. Install Python 3.11 x64 from https://www.python.org/downloads/ and enable "Add Python to PATH".
  pause
  exit /b 1
)
echo [2/4] Checking FFmpeg...
where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo FFmpeg was not found in PATH. Install FFmpeg, reopen this window, then run setup again.
  echo https://ffmpeg.org/download.html
  pause
  exit /b 1
)
echo [3/4] Creating virtual environment...
if not exist .venv py -3.11 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto failed
python -m pip install -r requirements.txt
if errorlevel 1 goto failed
if not exist .env copy .env.example .env >nul
echo [4/4] Setup finished. Edit .env and add your Anthropic API key, then run start_windows.bat.
pause
exit /b 0
:failed
echo Setup failed. Check the error above and try again.
pause
exit /b 1
