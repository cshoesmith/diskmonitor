# Disk Health Monitor

A cross-platform (Linux/Windows) disk health monitoring tool. It resides in the system tray and monitors S.M.A.R.T. data from connected local disks.

## Features
- **System Tray Integration**: "Macro Status" indicator (Green/Orange/Red) lives in your taskbar.
- **Real-time Dashboard**: View Model, Serial, Temperature, Power-on Hours, and Interface Type (SATA/NVMe/USB).
- **Health Scoring**: Custom 0-100% health score based on critical SMART attributes.
- **Predictive History**: Tracks error rates over time to identify degrading drives before they fail.
- **Smart Deduplication**: Automatically filters duplicate entries for the same physical drive.
- **Auto-Elevation**: Automatically requests necessary Admin permissions on startup.

## Prerequisites

### 1. Smartmontools
This application relies on `smartctl` to read disk data. You can either install it system-wide or bundle it with the app.

**Option A: System Wide Install (Recommended for Linux)**
*   **Ubuntu/Debian:** `sudo apt-get install smartmontools`
*   **RHEL/CentOS:** `sudo yum install smartmontools`
*   **SUSE:** `sudo zypper install smartmontools`
*   **Windows:** Download installer from [SourceForge](https://sourceforge.net/projects/smartmontools/).

**Option B: Bundled (Portable)**
*   Place `smartctl` (Linux) or `smartctl.exe` (Windows) in the `bin/` directory of this project.
*   See `bin/README.md` for details.

sudo apt-get install smartmontools
```

**Windows:**
1. Download and install [smartmontools](https://www.smartmontools.org/wiki/Download#InstalltheWindowspackage).
2. Ensure the "Add to PATH" option is selected during installation.

### 2. Python Dependencies
Install the required python libraries:

```bash
pip install -r requirements.txt
```

## Running the Application

**Windows:**
Simply run the script. It will automatically prompt for UAC Admin access if needed.
```bash
python src/main.py
```

**Linux:**
```bash
sudo python3 src/main.py
```

## Development / Testing
If `smartctl` is not found, the application runs in **Mock Mode**, generating fake disk data for testing the UI.
