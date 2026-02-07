# Binaries

This folder allows you to bundle `smartctl` with the application so users don't need to install it globally.

## Windows
1. Download `smartmontools` installer from [SourceForge](https://sourceforge.net/projects/smartmontools/).
2. Extract `smartctl.exe` (you can use 7-Zip to extract files from the setup exe without installing).
3. Place `smartctl.exe` in this folder: `bin/smartctl.exe`.

## Linux
1. It is recommended to install via package manager: `sudo apt install smartmontools` or `sudo dnf install smartmontools`.
2. Alternatively, if you have a static binary, place it here: `bin/smartctl`.
3. Ensure the binary has execute permissions: `chmod +x bin/smartctl`.
