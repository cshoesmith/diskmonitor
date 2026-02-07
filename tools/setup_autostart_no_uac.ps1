try {
    $ErrorActionPreference = "Stop"
    
    $ScriptRoot = $PSScriptRoot
    if (-not $ScriptRoot) { $ScriptRoot = $pwd.Path }
    
    # Calculate absolute paths
    $Root = (Resolve-Path "$ScriptRoot\..").Path
    $MainPy = Join-Path $Root "src\main.py"
    $PythonW = Join-Path $Root ".venv\Scripts\pythonw.exe"

    if (-not (Test-Path $MainPy)) { throw "Could not find src\main.py at $MainPy" }
    if (-not (Test-Path $PythonW)) { throw "Could not find pythonw.exe at $PythonW" }

    Write-Host "Registering task for user: $env:USERNAME"
    Write-Host "Python: $PythonW"
    Write-Host "Script: $MainPy"

    # Create action
    $Action = New-ScheduledTaskAction -Execute $PythonW -Argument "`"$MainPy`""

    # Create trigger (At Log On)
    $Trigger = New-ScheduledTaskTrigger -AtLogOn

    # Principal (Run as current user, with Highest Privileges)
    $Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

    # Settings
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 0)

    # Register
    Register-ScheduledTask -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -TaskName "DiskMonitorAutoStart" -Description "Starts DiskMonitor with Admin rights at login." -Force

    Write-Host "SUCCESS: Task 'DiskMonitorAutoStart' created."
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
}

Write-Host "Press Enter to close..."
Read-Host
