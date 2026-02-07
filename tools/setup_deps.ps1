# PowerShell script to download smartmontools installer
$url = "https://sourceforge.net/projects/smartmontools/files/smartmontools/7.4/smartmontools-7.4-1.win32-setup.exe/download"
$output = "$PSScriptRoot\..\smartmontools-setup.exe"
$binPath = "$PSScriptRoot\..\bin"

Write-Host "Downloading smartmontools installer..."
Invoke-WebRequest -Uri $url -OutFile $output -UserAgent "Mozilla/5.0"

Write-Host "Download complete: $output"
Write-Host "To extract smartctl.exe without installing, you typically need 7-Zip."
Write-Host "If 7-Zip is installed (c:\Program Files\7-Zip\7z.exe), we can try to extract."

$7z = "C:\Program Files\7-Zip\7z.exe"
if (Test-Path $7z) {
    Write-Host "7-Zip found. Extracting..."
    & $7z e $output -o"$binPath" smartctl.exe -r
    if (Test-Path "$binPath\smartctl.exe") {
        Write-Host "Success! smartctl.exe placed in bin/."
    } else {
        Write-Host "Extraction failed or file not found in archive."
    }
} else {
    Write-Host "7-Zip not found. Please manually extract 'smartctl.exe' from the downloaded installer and place it in the 'bin' folder."
}
