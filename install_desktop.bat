@echo off
rem J.A.R.V.I.S. desktop installer - creates Desktop and Start Menu shortcuts.
rem No admin rights needed. JARVIS stays in this folder; the shortcuts point to it.
rem Run build_exe.bat first if dist\JARVIS does not exist yet.

set "HERE=%~dp0"
set "EXE=%HERE%dist\JARVIS\JARVIS.exe"
set "ICON=%HERE%assets\jarvis.ico"
set "WORKDIR=%HERE%dist\JARVIS"

if not exist "%EXE%" (
    echo [JARVIS] %EXE% was not found.
    echo         Run build_exe.bat first to create the desktop app, then try again.
    pause
    exit /b 1
)

echo [JARVIS] Installing shortcuts to %EXE% ...

powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -Command "$ws = New-Object -ComObject WScript.Shell; $target = '%EXE%'; $icon = '%ICON%'; $workdir = '%WORKDIR%'; $desktop = [Environment]::GetFolderPath('Desktop'); $startmenu = [Environment]::GetFolderPath('Programs'); $paths = @(($desktop + '\J.A.R.V.I.S..lnk'), ($startmenu + '\JARVIS\JARVIS.lnk')); foreach ($p in $paths) { New-Item -ItemType Directory -Force -Path (Split-Path $p) | Out-Null; $sc = $ws.CreateShortcut($p); $sc.TargetPath = $target; $sc.WorkingDirectory = $workdir; $sc.IconLocation = $icon; $sc.Description = 'J.A.R.V.I.S. - AI desktop assistant'; $sc.Save() }"

if errorlevel 1 (
    echo [JARVIS] Shortcut creation failed.
    pause
    exit /b 1
)

echo [JARVIS] Done. Double-click "J.A.R.V.I.S." on your Desktop to start it.
pause
