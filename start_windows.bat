@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)
if not exist .env (
  echo .env is missing. Copy .env.example to .env and configure your API key.
  pause
  exit /b 1
)
start "Xuong phim mau" http://127.0.0.1:8000
.venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv()" >nul 2>&1
set PYTHONPATH=%CD%
.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
pause
