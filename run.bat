@echo off
REM  J.A.R.V.I.S. launcher (Windows) - double-click to run.
REM  Works on any Windows PC that has Python 3.10+ installed.
cd /d "%~dp0"
setlocal

set "VPY=.venv\Scripts\python.exe"
REM  Local PC: JARVIS may open apps, websites and files for you.
set "JARVIS_SYSTEM_CONTROL=1"

REM --- Locate a Python interpreter if we don't already have a venv ---------
if not exist "%VPY%" (
    echo [JARVIS] Setting up for the first time on this PC...

    set "PY="
    py -3 --version >nul 2>&1 && set "PY=py -3"
    if not defined PY ( python --version >nul 2>&1 && set "PY=python" )
    if not defined PY ( python3 --version >nul 2>&1 && set "PY=python3" )

    if not defined PY (
        echo [JARVIS] Python was not found on this system.
        echo [JARVIS] Please install Python 3.10 or newer from https://www.python.org/downloads/
        echo [JARVIS] IMPORTANT: tick "Add python.exe to PATH" during install, then re-run this file.
        pause
        exit /b 1
    )

    echo [JARVIS] Creating virtual environment with: %PY%
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [JARVIS] Could not create the virtual environment.
        pause
        exit /b 1
    )
)

echo [JARVIS] Installing / refreshing dependencies...
"%VPY%" -m pip install --upgrade pip -q
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [JARVIS] Dependency installation failed. Check your internet connection.
    pause
    exit /b 1
)

echo [JARVIS] Starting interface... (a browser tab will open at http://localhost:8501)
"%VPY%" -m streamlit run app.py

endlocal
pause
