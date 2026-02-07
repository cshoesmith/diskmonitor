@echo off
schtasks /query /tn "DiskMonitorAutoStart" >nul 2>&1
if %errorlevel% equ 0 (
    schtasks /run /tn "DiskMonitorAutoStart" >nul
) else (
    echo Auto-start task not found. Launching directly (UAC will appear)...
    echo tip: Run 'tools\setup_autostart_no_uac.ps1' as Admin to enable silent startup.
    start "" ".venv\Scripts\pythonw.exe" "src\main.py"
)
exit
