import sys
import os
import threading
import traceback
import subprocess

def is_admin():
    try:
        if hasattr(os, 'getuid'):
             return os.getuid() == 0
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def setup_logging():
    """Redirect stdout/stderr to log file if running without console (pythonw)"""
    # Check if we are in a no-console environment (sys.stdout might be None)
    if sys.stdout is None or sys.stderr is None:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "diskmonitor.log")
        try:
            # Open in append mode with buffering=1 (line buffered)
            sys.stdout = open(log_path, "a", buffering=1, encoding="utf-8")
            sys.stderr = sys.stdout
            
            import datetime
            print(f"\n--- Session Start: {datetime.datetime.now()} ---")
        except Exception:
            pass # If we can't write logs, we silent fail

def main():
    setup_logging()
    
    try:
        from ui import DiskMonitorApp
        from monitor import DiskHealthMonitor
    except Exception as e:
        with open("crash_import.log", "w") as f:
            f.write(traceback.format_exc())
        return

    if not is_admin():
        if sys.platform == 'win32':
            # 1. OPTION A: Try to hand off to Silent Scheduled Task (No UAC)
            try:
                # Check if the "Bypass UAC" task exists
                devnull = open(os.devnull, 'w')
                if subprocess.call('schtasks /query /tn "DiskMonitorAutoStart"', shell=True, stdout=devnull, stderr=devnull) == 0:
                     # Task exists! Trigger it and exit.
                     # This launches the app via Task Scheduler with Highest Privileges silently.
                     subprocess.call('schtasks /run /tn "DiskMonitorAutoStart"', shell=True, stdout=devnull, stderr=devnull)
                     sys.exit(0) 
            except Exception:
                pass

            # 2. OPTION B: Attempt to automatically elevate privileges (Triggers UAC)
            try:
                import ctypes
                script = os.path.abspath(sys.argv[0])
                params = " ".join([f'"{arg}"' for arg in sys.argv[1:]])
                
                # Determine executable (prefer pythonw.exe for GUI experience)
                executable = sys.executable
                if executable.endswith("python.exe"):
                    w_exe = executable.replace("python.exe", "pythonw.exe")
                    if os.path.exists(w_exe):
                        executable = w_exe
                
                cmd_args = f'"{script}" {params}'
                
                # ShellExecuteW returns > 32 on success. 
                # nShowCmd=0 (SW_HIDE) - helpful if checking from task scheduler, 
                # but runas usually forces prompt.
                ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, cmd_args, None, 1)
                if ret > 32:
                    sys.exit(0) # Exit this non-admin instance
            except Exception as e:
                print(f"Failed to request elevation: {e}")

        # If on Linux or elevation failed/refused
        print("Warning: This application typically requires Administrator/Root privileges to access SMART data directly.")
        print("Some functionality may be limited.")
    
    # Initialize monitor
    monitor = DiskHealthMonitor()
    
    # Start UI
    app = DiskMonitorApp(monitor)
    app.run()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        with open("crash_main.log", "w") as f:
            f.write(f"ERROR: {e}\n")
            f.write(traceback.format_exc())
        # Try to show message box
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f"Crashed: {e}", "Disk Monitor Error", 0x10)
        except:
            pass

