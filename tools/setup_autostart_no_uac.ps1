$ErrorActionPreference = "Stop"

$ActionName = "DiskMonitor"
$ScriptPath = Resolve-Path "$PSScriptRoot\..\src\main.py"
$PythonWPath = Resolve-Path "$PSScriptRoot\..\.venv\Scripts\pythonw.exe"

# Create action
$Action = New-ScheduledTaskAction -Execute $PythonWPath -Argument "`"$ScriptPath`""

# Create trigger (At Log On)
$Trigger = New-ScheduledTaskTrigger -AtLogOn

# Principal (Run as current user, with Highest Privileges)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

# Settings (Hidden, Highest Privileges to bypass UAC)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 0)

# Register with Highest Privileges
Register-ScheduledTask -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -TaskName "DiskMonitorAutoStart" -Description "Starts DiskMonitor with Admin rights at login." -Force

Write-Host "Task 'DiskMonitorAutoStart' created successfully."
Write-Host "The application will now start automatically at login WITHOUT a UAC prompt."
Write-Host "You can also run it manually from Task Scheduler."
