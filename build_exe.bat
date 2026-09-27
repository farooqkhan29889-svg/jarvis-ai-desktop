@echo off
REM  Build the single-file JARVIS.exe (Windows).
REM  Produces dist\JARVIS.exe that runs on PCs WITHOUT Python installed.
cd /d "%~dp0"
setlocal

set "VPY=.venv\Scripts\python.exe"
if not exist "%VPY%" (
    echo [BUILD] .venv not found. Run run.bat once first to create it.
    pause & exit /b 1
)

echo [BUILD] Ensuring PyInstaller is present...
"%VPY%" -m pip install -q pyinstaller

echo [BUILD] Building single-file executable (this takes several minutes)...
"%VPY%" -m PyInstaller jarvis.spec --noconfirm --clean
if errorlevel 1 (
    echo [BUILD] Build FAILED. See build.log / console output.
    pause & exit /b 1
)

echo [BUILD] Done. Output: dist\JARVIS\JARVIS.exe
echo [BUILD] Ship the WHOLE dist\JARVIS folder; run JARVIS.exe from inside it.
echo [BUILD] One-dir build = fast startup (no self-extraction).
endlocal
pause
