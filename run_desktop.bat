@echo off
REM  J.A.R.V.I.S. desktop app launcher (Windows) - opens in its own window.
REM  Works on any Windows PC that has Python 3.10+ and the WebView2 runtime.
cd /d "%~dp0"
setlocal

set "VPY=.venv\Scripts\python.exe"
REM  Local PC: JARVIS may open apps, websites and files for you.
set "JARVIS_SYSTEM_CONTROL=1"

if not exist "%VPY%" (
    echo [JARVIS] Setting up for the first time on this PC...
    set "PY="
    py -3 --version >nul 2>&1 && set "PY=py -3"
    if not defined PY ( python --version >nul 2>&1 && set "PY=python" )
    if not defined PY ( python3 --version >nul 2>&1 && set "PY=python3" )
    if not defined PY (
        echo [JARVIS] Python not found. Install Python 3.10+ from https://www.python.org/downloads/
        echo [JARVIS] Tick "Add python.exe to PATH" during install, then re-run.
        pause & exit /b 1
    )
    %PY% -m venv .venv || ( echo [JARVIS] venv creation failed & pause & exit /b 1 )
)

echo [JARVIS] Installing / refreshing dependencies...
"%VPY%" -m pip install --upgrade pip -q
"%VPY%" -m pip install -r requirements.txt || ( echo [JARVIS] Install failed & pause & exit /b 1 )

echo [JARVIS] Launching desktop window...
"%VPY%" desktop.py

endlocal
pause
