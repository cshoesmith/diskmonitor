@echo off
:check_task
schtasks /query /tn "DiskMonitorAutoStart" >nul 2>&1
if %errorlevel% equ 0 (
    echo Starting Disk Monitor silently...
    schtasks /run /tn "DiskMonitorAutoStart" >nul
    exit
)

echo.
echo ========================================================
echo  First Run Configuration
echo ========================================================
echo  To run Disk Monitor without UAC prompts every time,
echo  we need to create a special Windows Scheduled Task.
echo.
echo  1. A UAC prompt will appear in a moment.
echo  2. Please click "Yes" to create the startup task.
echo  3. This is a one-time setup.
echo ========================================================
echo.

powershell -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File tools\setup_autostart_no_uac.ps1'"

echo Waiting for setup to complete...
timeout /t 5 >nul
goto check_task
