@echo off
rem Double-click to start Couch TV Setup from this folder on Windows (needs Python 3.9 or newer,
rem from python.org or the Microsoft Store). It makes a private Python folder for itself the first
rem time, then opens the setup in your browser.
cd /d "%~dp0"
set "VENV=%APPDATA%\Couch TV Setup\venv"
if not exist "%VENV%\Scripts\python.exe" (
  echo Getting ready (only the first time, about a minute^)...
  py -3 -m venv "%VENV%" 2>nul || python -m venv "%VENV%"
  if errorlevel 1 (
    echo Python is needed: install it from https://www.python.org/downloads/ and try again.
    pause
    exit /b 1
  )
  "%VENV%\Scripts\python.exe" -m pip install -q --disable-pip-version-check --require-hashes --no-deps -r requirements.txt
)
"%VENV%\Scripts\python.exe" -m couchtv_setup
