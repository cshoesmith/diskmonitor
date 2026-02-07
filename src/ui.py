import threading
import tkinter as tk
import customtkinter as ctk
import time
from PIL import Image, ImageDraw
import pystray
import sys
import json
import os
from history import DiskHistory

# Matplotlib for professional charts
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.figure

class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event=None):
        if self.tooltip_window or not self.text:
            return
        x, y, cx, cy = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25
        
        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")
        self.tooltip_window.attributes("-topmost", True)
        
        label = tk.Label(self.tooltip_window, text=self.text, justify='left',
                         background="#ffffe0", relief='solid', borderwidth=1,
                         font=("tahoma", "8", "normal"))
        label.pack(ipadx=1)

    def hide_tooltip(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None

class DiskMonitorApp:
    def __init__(self, monitor):
        self.monitor = monitor
        self.history = DiskHistory()
        self.icon = None
        self.root = None
        self.running = True
        self.disks_data = {}
        self.lock = threading.Lock()
        
        # UI State
        self.show_hidden_drives = False
        self.ui_setup_done = False
        self.table_frame = None
        
        # Progress Tracking
        self.scan_progress = 0.0
        self.scan_status_text = "Initializing..."
        self.progress_bar = None
        self.progress_label = None
        self.is_scanning = False

        # Cache
        self.cache_file = "disk_cache.json"
        self._load_cache()

    def _load_cache(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r') as f:
                    self.disks_data = json.load(f)
                print(f"Loaded cached data for {len(self.disks_data)} devices.")
            except Exception as e:
                print(f"Failed to load cache: {e}")

    def _save_cache(self, data):
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
             print(f"Failed to save cache: {e}")

    def run(self):
        print("Starting Disk Monitor...")
        # Start monitor thread first
        t = threading.Thread(target=self._monitor_loop, daemon=True)
        t.start()

        # Initialize Tkinter (Must be main thread)
        self._init_ui()
        
        # Start Tray in a separate thread
        tray_thread = threading.Thread(target=self._run_tray, daemon=True)
        tray_thread.start()
        
        # Run Tk mainloop
        self.root.mainloop()

    def _init_ui(self):
        ctk.set_appearance_mode("System")
        self.root = ctk.CTk()
        self.root.title("Disk Health Monitor")
        self.root.geometry("1000x600")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_window)
        # We start withdrawn (hidden) so only tray is visible
        self.root.withdraw()

    def _on_close_window(self):
        # Instead of closing, we hide
        self.root.withdraw()

    def _run_tray(self):
        image = self._create_icon("green")
        menu = pystray.Menu(
            pystray.MenuItem("Disk Health Monitor", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Dashboard", self.show_dashboard, default=True),
            pystray.MenuItem("Exit", self.exit_app)
        )
        self.icon = pystray.Icon("DiskMonitor", image, "Disk Health: OK", menu)
        # Block this thread
        self.icon.run()

    def show_dashboard(self, icon=None, item=None):
        # Schedule GUI update on main thread
        self.root.after(0, self._show_dashboard_main)

    def _show_dashboard_main(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self._refresh_dashboard()

    def toggle_hidden_drives(self):
        self.show_hidden_drives = not self.show_hidden_drives
        self._refresh_dashboard()

    def _setup_static_ui(self):
        # Title Frame (Header + Toggle)
        header_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        header_frame.pack(fill="x", padx=20, pady=(15, 10))

        header = ctk.CTkLabel(header_frame, text="Disk Health Dashboard", font=("Segoe UI", 20, "bold"))
        header.pack(side="left")

        # Toggle Switch for Hidden Drives
        toggle_val = ctk.BooleanVar(value=self.show_hidden_drives)
        switch = ctk.CTkSwitch(
            header_frame, 
            text="Show Hidden Drives", 
            command=self.toggle_hidden_drives,
            variable=toggle_val,
            onvalue=True,
            offvalue=False
        )
        switch.pack(side="right")
        
        # Main Table Container
        self.table_frame = ctk.CTkFrame(self.root)
        self.table_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Manual refresh button
        btn = ctk.CTkButton(self.root, text="Refresh Now", command=self._refresh_dashboard)
        btn.pack(pady=10)

        self.ui_setup_done = True

    def _update_loading_view(self):
        # Helper to update progress bar without rebuilding entire UI
        # Only creates widgets if they don't exist
        
        # Check if we already have the progress widgets
        if not self.progress_bar or not self.progress_bar.winfo_exists():
            # Clear table frame first
            for widget in self.table_frame.winfo_children():
                widget.destroy()
            
            # Container for centering logic
            container = ctk.CTkFrame(self.table_frame, fg_color="transparent")
            container.place(relx=0.5, rely=0.5, anchor="center")

            msg = ctk.CTkLabel(container, text=self.scan_status_text, font=("Segoe UI", 14))
            msg.pack(pady=(0, 10))
            self.progress_label = msg
            
            prog = ctk.CTkProgressBar(container, width=300)
            prog.pack(pady=(0, 0))
            prog.set(0)
            self.progress_bar = prog

        # Update values
        if self.progress_label:
            self.progress_label.configure(text=self.scan_status_text)
        if self.progress_bar:
            self.progress_bar.set(self.scan_progress)

    def _refresh_dashboard(self):
        # Ensure static UI structure exists
        if not self.ui_setup_done:
            self._setup_static_ui()
            
        with self.lock:
            current_data = self.disks_data.copy()

        # If we have no data yet (first scan), show progress
        if not current_data:
            self._update_loading_view()
            self.root.after(100, self._refresh_dashboard)
            return
        
        # If we have data, but we were showing progress bar previously, clear it
        if self.progress_bar and self.progress_bar.winfo_exists():
            for widget in self.table_frame.winfo_children():
                widget.destroy()
            self.progress_bar = None
            self.progress_label = None

        # Check if we need to rebuild the table (if it's empty)
        if not self.table_frame.winfo_children():
            # Configure grid columns
            self.table_frame.grid_columnconfigure(0, weight=2)
            self.table_frame.grid_columnconfigure(1, weight=1)
            self.table_frame.grid_columnconfigure(2, weight=1)
            self.table_frame.grid_columnconfigure(3, weight=1)
            self.table_frame.grid_columnconfigure(4, weight=1)
        self.table_frame.grid_columnconfigure(5, weight=1)
        self.table_frame.grid_columnconfigure(6, weight=1)
        self.table_frame.grid_columnconfigure(7, minsize=80)

        # Table Header
        headers = ["Device / Model", "Connection", "Status", "I/O Load", "Temp / Age", "Realloc", "Read Err", ""]
        for i, h in enumerate(headers):
            lbl = ctk.CTkLabel(self.table_frame, text=h, font=("Segoe UI", 12, "bold"), text_color="gray")
            lbl.grid(row=0, column=i, sticky="ew", pady=5, padx=5)
            
        # Separator
        sep = ctk.CTkProgressBar(self.table_frame, height=2)
        sep.grid(row=1, column=0, columnspan=8, sticky="ew", padx=5)
        
        # However, _refresh_dashboard is called recursively only in the loading state above. 
        # Once data is found, the recursion STOPS.
        # So we can safely clear and build here.
        
        # We need to clear rows safely without destroying headers? 
        # Actually simplest approach that fixes the "User Issue" is to just rebuild, 
        # because the user issue was specifically about the FLASHING DURING SCAN.
        # Since we stopped the recursion when data exists (see above return), this part is only called ONCE when scan finishes.
        
        # Ensure we clear old rows if any (but keep headers?)
        # Actually the "if not self.table_frame.winfo_children()" check above ensures headers are built.
        # If they ARE built, we should probably clear the data rows (index > 1).
        
        # Let's just do a clean rebuild of the table content for now to be safe and consistent.
        # If we want to optimize partial updates later we can.
        # BUT wait, if I cleared above, then I built headers.
        # If I didn't clear above, I have old rows.
        
        # Reset:
        if self.table_frame.winfo_children():
             for widget in self.table_frame.winfo_children():
                widget.destroy()

        # Rebuild headers (Copy paste from above or refactor. Copy for safety now)
        self.table_frame.grid_columnconfigure(0, weight=2)
        self.table_frame.grid_columnconfigure(1, weight=1)
        self.table_frame.grid_columnconfigure(2, weight=1)
        self.table_frame.grid_columnconfigure(3, weight=1)
        self.table_frame.grid_columnconfigure(4, weight=1)
        self.table_frame.grid_columnconfigure(5, weight=1)
        self.table_frame.grid_columnconfigure(6, weight=1)
        self.table_frame.grid_columnconfigure(7, minsize=80)

        headers = ["Device / Model", "Connection", "Status", "I/O Load", "Temp / Age", "Realloc", "Read Err", ""]
        for i, h in enumerate(headers):
            lbl = ctk.CTkLabel(self.table_frame, text=h, font=("Segoe UI", 12, "bold"), text_color="gray")
            lbl.grid(row=0, column=i, sticky="ew", pady=5, padx=5)
            
        sep = ctk.CTkProgressBar(self.table_frame, height=2)
        sep.grid(row=1, column=0, columnspan=8, sticky="ew", padx=5)
        sep.set(1)

        row_idx = 2
        
        # Filter duplicates by Serial Number
        seen_serials = set()
        
        for dev, data in current_data.items():
            # Get Serial
            device_info = data.get("device", {})
            serial = data.get("serial_number") or device_info.get("serial_number") or "Unknown"
            
            # 1. Deduplication Filter
            # Skip if we've seen this serial (and it's not "Unknown")
            if serial != "Unknown" and serial in seen_serials:
                continue
            seen_serials.add(serial)

            # 2. Hidden/Ghost Drive Filter
            if not self.show_hidden_drives:
                # Check 1: Zero Capacity
                cap_bytes = data.get("user_capacity", {}).get("bytes", 0)
                
                # Check 2: No Model/Generic + No Smart (Heuristic for empty card readers)
                model = data.get("model_name") or data.get("model_family") or device_info.get("model") or ""
                smart_passed = data.get("smart_status", {}).get("passed")
                
                is_ghost = False
                if cap_bytes == 0:
                    is_ghost = True
                elif "JIE LI" in model and cap_bytes == 0:
                    is_ghost = True
                elif smart_passed is None and cap_bytes == 0:
                     is_ghost = True

                if is_ghost:
                    continue
            
            self._create_disk_row_grid(self.table_frame, row_idx, dev, data)
            row_idx += 2 # Skip row for separator/warnings

        # Manual refresh button is now static in _setup_static_ui, so we remove it from here

    def _create_disk_row_grid(self, frame, row, dev, data):
        # Extract info
        device_info = data.get("device", {})
        model = data.get("model_name") or data.get("model_family") or device_info.get("model") or "Unknown Model"
        serial = data.get("serial_number") or device_info.get("serial_number") or "Unknown SN"
        
        temp_info = data.get("temperature", {})
        temp = temp_info.get("current", "N/A")
        power_hours = data.get("power_on_time", {}).get("hours", 0)
        
        stats = data.get("stats", {"rsc": "?", "read_err": "?"})
        analysis = data.get("analysis", {"status": "OK", "messages": []})

        # Determine Status
        status_text = "Healthy"
        status_color = "#2ecc71" # Green
        
        score = data.get("health_score", 100)
        
        if analysis["status"] == "CRITICAL" or score < 50:
            status_text = f"Critical - {score}%"
            status_color = "#e74c3c" # Red
        elif analysis["status"] == "WARNING" or score < 90:
            status_text = f"Warning - {score}%"
            status_color = "#f39c12" # Orange
        elif not data.get("smart_status", {}).get("passed", True):
             status_text = f"Failing - {score}%"
             status_color = "#c0392b"
        else:
             status_text = f"Healthy - {score}%"

        # 1. Device Info Column
        info_frame = ctk.CTkFrame(frame, fg_color="transparent")
        info_frame.grid(row=row, column=0, sticky="w", padx=10, pady=10)
        
        ctk.CTkLabel(info_frame, text=dev, font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ctk.CTkLabel(info_frame, text=model, font=("Segoe UI", 11), text_color="gray").pack(anchor="w")
        ctk.CTkLabel(info_frame, text=f"SN: {serial}", font=("Segoe UI", 11), text_color="gray").pack(anchor="w")

        # 2. Connection Type Column (NEW)
        protocol = device_info.get("protocol", "Unknown")
        conn_detail = data.get("connection_detail", {})
        
        conn_text = protocol
        conn_tooltip = ""
        
        if conn_detail:
             c_type = conn_detail.get("type", protocol)
             is_ext = conn_detail.get("is_external", False)
             loc = "Ext" if is_ext else "Int"
             conn_text = f"{c_type} ({loc})"
             conn_tooltip = conn_detail.get("speed_limit", "")
        
        conn_lbl = ctk.CTkLabel(frame, text=conn_text, font=("Segoe UI", 12))
        conn_lbl.grid(row=row, column=1)
        
        if conn_tooltip:
            ToolTip(conn_lbl, text=conn_tooltip)

        # 3. Status Column
        status_frame = ctk.CTkFrame(frame, fg_color="transparent")
        status_frame.grid(row=row, column=2, sticky="w", padx=10)
        
        status_btn = ctk.CTkButton(status_frame, text=status_text, fg_color=status_color, state="disabled", text_color_disabled="white", width=120, height=24)
        status_btn.pack()

        # Tooltip logic
        msgs = analysis.get("messages", [])
        tooltip_text = "All OK"
        if msgs:
            tooltip_text = "\n".join(msgs)
        elif score < 100:
             tooltip_text = f"Health Score: {score}%\nCheck details for standard attributes."
        
        ToolTip(status_btn, text=tooltip_text)

        # 4. I/O Load Column (NEW)
        # Look up load from monitor cache using device_id
        dev_id = conn_detail.get("device_id", None)
        io_load = 0.0
        if dev_id and dev_id in self.monitor.io_stats_cache:
            io_load = self.monitor.io_stats_cache[dev_id]
        
        io_fg = "gray"
        if io_load > 80: io_fg = "#e74c3c" # Red high load
        elif io_load > 10: io_fg = "#2ecc71" # Active green
        
        ctk.CTkLabel(frame, text=f"{io_load}%", font=("Segoe UI", 12)).grid(row=row, column=3)

        # 5. Temp / Age Column
        power_days = power_hours / 24.0
        temp_txt = f"{temp}°C\n{power_days:.1f}d"
        ctk.CTkLabel(frame, text=temp_txt, font=("Segoe UI", 12)).grid(row=row, column=4)

        # 6. Reallocated Sectors (Color coded)
        rsc = stats['rsc']
        rsc_fg = "gray"
        if isinstance(rsc, (int, float)):
             rsc_fg = "#e74c3c" if rsc > 0 else "#2ecc71" # Red if bad, Green if good
        ctk.CTkLabel(frame, text=str(rsc), font=("Segoe UI", 12, "bold"), text_color=rsc_fg).grid(row=row, column=5)

        # 7. Read Errors (Color coded)
        err = stats['read_err']
        err_fg = "gray"
        if isinstance(err, (int, float)):
             err_fg = "#e74c3c" if err > 0 else "#2ecc71"
        ctk.CTkLabel(frame, text=str(err), font=("Segoe UI", 12, "bold"), text_color=err_fg).grid(row=row, column=6)

        # 8. Details Button
        ctk.CTkButton(frame, text="Details", width=60, height=24, 
                      command=lambda d=data: self._show_details_window(d)).grid(row=row, column=7, padx=10)
        
        # Warnings Row (Below)
        if analysis["messages"]:
             warn_txt = "⚠ " + " | ".join(analysis["messages"])
             ctk.CTkLabel(frame, text=warn_txt, text_color=status_color, font=("Segoe UI", 11)).grid(row=row+1, column=0, columnspan=8, sticky="w", padx=20)
        
        # Add visual separator line
        # line = ctk.CTkFrame(frame, height=1, fg_color="gray30")
        # line.grid(row=row+1, column=0, columnspan=4, sticky="ew")

    def _show_details_window(self, data):
        DiskDetailsWindow(self.root, data, self.history)


    def _create_icon(self, color):
        width = 64
        height = 64
        # Create transparent image
        image = Image.new('RGBA', (width, height), (0,0,0,0))
        dc = ImageDraw.Draw(image)
        
        fill_color = (0, 255, 0, 255)
        if color == "red":
            fill_color = (255, 0, 0, 255)
        elif color == "yellow":
            fill_color = (255, 255, 0, 255)
        
        # Draw circle
        dc.ellipse((8, 8, 56, 56), fill=fill_color, outline=(0,0,0,255))
        return image

    def _monitor_loop(self):
        while self.running:
            try:
                self.is_scanning = True
                self.scan_progress = 0.0
                self.scan_status_text = "Scanning for devices..."
                
                # Check connection / scan
                devices = self.monitor.scan_disks()
                
                total_devices = len(devices)
                self.scan_progress = 0.1 # Scanned list
                
                # Fetch IO Stats Batch (Takes ~1 sec)
                self.scan_status_text = "Sampling I/O Load..."
                self.monitor.update_io_stats()
                
                overall_status = "green"
                new_data = {}
                
                for i, dev in enumerate(devices):
                    # Update Progress
                    self.scan_status_text = f"Analyzing {dev}..."
                    self.scan_progress = 0.1 + (0.9 * (i / total_devices))
                    
                    data = self.monitor.get_disk_health(dev)
                    
                    # Extract ID info
                    device_info = data.get("device", {})
                    serial = data.get("serial_number") or device_info.get("serial_number") or "Unknown"
                    
                    # Extract attributes
                    rsc, read_err, pending = 0, 0, 0
                    
                    # Try Parsing standard ATA attributes
                    table = data.get("ata_smart_attributes", {}).get("table", [])
                    for attr in table:
                        id_ = attr.get("id")
                        raw_val = attr.get("raw", {}).get("value", 0)
                        
                        if id_ == 5: rsc = raw_val
                        elif id_ == 1: read_err = raw_val
                        elif id_ == 197: pending = raw_val
                    
                    hours = data.get("power_on_time", {}).get("hours", 0)
                    
                    # Capture IO Load
                    conn_detail = data.get("connection_detail", {})
                    dev_id = conn_detail.get("device_id", None)
                    io_load = 0.0
                    if dev_id and dev_id in self.monitor.io_stats_cache:
                        io_load = self.monitor.io_stats_cache[dev_id]

                    # Log to history
                    if serial != "Unknown":
                        self.history.log_status(serial, rsc, read_err, hours, pending, io_load)
                        
                        # Analyze
                        analysis = self.history.analyze_trend(serial)
                        data["analysis"] = analysis
                        data["stats"] = {"rsc": rsc, "read_err": read_err, "pending": pending}
                        
                        if analysis["status"] != "OK":
                            overall_status = "yellow" # Warning state
                            passed = data.get("smart_status", {}).get("passed", True)
                            if not passed or analysis["status"] == "CRITICAL":
                                overall_status = "red"

                    new_data[dev] = data
                
                # Update shared state
                with self.lock:
                    self.disks_data = new_data
                
                # Save to cache
                self._save_cache(new_data)
                
                self.is_scanning = False
                self.scan_status_text = "Scan Complete"
                self.scan_progress = 1.0

                # Update Icon
                if self.icon:
                    new_image = self._create_icon(overall_status)
                    self.icon.icon = new_image
                    self.icon.title = f"Disk Health: {overall_status.upper()}"
                
                # Trigger UI refresh if visible
                if self.root:
                    self.root.after(0, self._safe_refresh)
            
            except Exception as e:
                print(f"Monitor loop error: {e}")
            
            time.sleep(60) # Scan every 60s for history tracking

    def _safe_refresh(self):
        try:
             # Refresh if window is open/visible
             if self.root.winfo_viewable():
                 self._refresh_dashboard()
        except:
             pass

    def exit_app(self, icon=None, item=None):
        self.running = False
        if self.icon:
            self.icon.stop()
        # Schedule exit on main thread
        self.root.after(0, self._exit_main)

    def _exit_main(self):
        self.root.quit()
        sys.exit()

class DiskDetailsWindow(ctk.CTkToplevel):
    def __init__(self, parent, data, history_manager=None):
        super().__init__(parent)
        self.attributes("-topmost", True) # Make window stay on top
        self.focus_force() # Force focus
        self.grab_set() # Make modal (block interaction with main window)
        self.history = history_manager or DiskHistory()
        # Create a temporary monitor instance to access helper, or just import it? 
        # Easier to just instantiate since it's light
        from monitor import DiskHealthMonitor
        self.monitor_logic = DiskHealthMonitor() 
        
        # Extract Data
        device_info = data.get("device", {})
        model = data.get("model_name") or data.get("model_family") or device_info.get("model") or "Unknown Model"
        serial = data.get("serial_number") or device_info.get("serial_number") or "Unknown"
        firmware = data.get("firmware_version", "Unknown")
        capacity = "Unknown"
        if "user_capacity" in data:
            cap_bytes = data["user_capacity"].get("bytes", 0)
            capacity = f"{cap_bytes / (1024**3):.1f} GB"

        smart_status = data.get("smart_status", {})
        passed = smart_status.get("passed", True)
        temp = data.get("temperature", {}).get("current", "N/A")
        score = data.get("health_score", 100)
        
        rot_rate = data.get("rotation_rate", "Solid State Device" if data.get("rotation_rate", 0) == 0 else str(data.get("rotation_rate")) + " RPM")

        power_hours = data.get("power_on_time", {}).get("hours", 0)
        power_count = data.get("power_cycle_count", 0)

        self.title(f"{model} - Disk Details")
        self.geometry("1100x800")
        
        # --- TOP HEADER (Model Name) ---
        header_frame = ctk.CTkFrame(self)
        header_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(header_frame, text=f"{model} : {capacity}", font=("Segoe UI", 24, "bold")).pack(side="left", padx=10)
        ctk.CTkLabel(header_frame, text="Disk Health Monitor", font=("Segoe UI", 12)).pack(side="right", padx=10)

        # --- INFO GRID (Firmware, Serial, etc) ---
        info_frame = ctk.CTkFrame(self)
        info_frame.pack(fill="x", padx=10, pady=5)
        
        # Left Side (Big Status buttons)
        status_frame = ctk.CTkFrame(info_frame, fg_color="transparent")
        status_frame.pack(side="left", padx=20, pady=10)
        
        status_color = "#2ecc71" if passed and score > 90 else "#e74c3c"
        if passed and score < 50: status_color = "#e74c3c"
        elif passed and score <= 90: status_color = "#f39c12"

        status_text = "Good" if passed else "Bad"
        
        # Health Button
        btn_health = ctk.CTkButton(status_frame, text=f"Health Status\n{status_text}\n{score}%", 
                                   fg_color=status_color, width=150, height=80, font=("Segoe UI", 16, "bold"))
        btn_health.pack(pady=5)
        
        # Temp Button
        btn_temp = ctk.CTkButton(status_frame, text=f"Temperature\n{temp} °C", 
                                 fg_color="#3498db" if temp != "N/A" else "gray", 
                                 width=150, height=80, font=("Segoe UI", 16, "bold"))
        btn_temp.pack(pady=5)

        # Right Side (Details Grid)
        details_grid = ctk.CTkFrame(info_frame, fg_color="transparent")
        details_grid.pack(side="left", fill="both", expand=True, padx=10)
        
        conn_detail = data.get("connection_detail", {})
        interface_val = data.get("interface", "Unknown")
        if conn_detail:
            interface_val = f"{conn_detail.get('type')} ({'External' if conn_detail.get('is_external') else 'Internal'})"

        rows = [
            ("Firmware", firmware), ("Serial Number", serial),
            ("Rotation Rate", str(rot_rate)), ("Power On Count", str(power_count)),
            ("Interface", interface_val), ("Power On Hours", f"{power_hours}h ({power_hours/24:.1f} days)"),
            ("Standard", "ACS-3 / ATA8-ACS"), ("Features", "S.M.A.R.T.")
        ]
        
        for i, (label, val) in enumerate(rows):
            r = i // 2
            c = (i % 2) * 2
            ctk.CTkLabel(details_grid, text=label, font=("Segoe UI", 12)).grid(row=r, column=c, sticky="e", padx=5, pady=2)
            ctk.CTkEntry(details_grid, placeholder_text=str(val)).grid(row=r, column=c+1, sticky="w", padx=5, pady=2)
            # Use disabled entry for "readonly" look found in CDI
            ent = ctk.CTkEntry(details_grid)
            ent.insert(0, str(val))
            ent.configure(state="readonly", width=180)
            ent.grid(row=r, column=c+1, sticky="w", padx=5, pady=2)

        # --- PARTITION CHART ---
        partitions = data.get("partitions", [])
        if partitions:
            # Container for Chart stuff logic
            part_container = ctk.CTkFrame(self, fg_color="transparent")
            part_container.pack(fill="x", padx=10, pady=10)
            
            ctk.CTkLabel(part_container, text="Partition Usage", font=("Segoe UI", 14, "bold")).pack(anchor="w")
            
            # Chart Area
            chart_area = ctk.CTkFrame(part_container, fg_color="transparent")
            chart_area.pack(fill="x", expand=True)

            colors = ["#0078D7", "#2B88D8", "#60A5FA", "#93C5FD", "#104a8e", "#005a9e"]
            
            sizes = [p["size_gb"] for p in partitions]
            labels = [f"{p['number']} ({p['size_gb']} GB)" for p in partitions]
            
            if not sizes or sum(sizes) == 0:
                 sizes = [1]
                 labels = ["Empty"]
                 colors = ["gray"]

            # Create Figure - Wider to fit legend
            fig = matplotlib.figure.Figure(figsize=(8, 3), dpi=100)
            fig.patch.set_facecolor('#dbdbdb') 
            
            ax = fig.add_subplot(111)
            wedges, texts = ax.pie(sizes, colors=colors, startangle=90, 
                                   wedgeprops={"edgecolor":"white", 'linewidth': 1, 'antialiased': True})
            ax.axis('equal') 
            
            # Legend inside the figure
            ax.legend(wedges, labels, title="Partitions", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1))
            fig.subplots_adjust(right=0.7) # Make room for legend

            # Canvas
            canvas = FigureCanvasTkAgg(fig, master=chart_area)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=True, padx=20)
        
        # --- IO LOAD CHART ---
        io_container = ctk.CTkFrame(self, fg_color="transparent")
        io_container.pack(fill="x", padx=10, pady=(0, 10))
        
        ctk.CTkLabel(io_container, text="I/O Load History (Last 60 samples)", font=("Segoe UI", 12, "bold")).pack(anchor="w")

        io_history = []
        if serial != "Unknown" and self.history:
              try:
                  io_history = self.history.get_io_history(serial, limit=60)
              except Exception as e:
                  print(f"Chart data error: {e}")
              
        if io_history and len(io_history) > 1:
             chart_frame = ctk.CTkFrame(io_container, fg_color="transparent")
             chart_frame.pack(fill="x", expand=True)
             
             y_vals = [x[1] for x in io_history]
             x_vals = range(len(y_vals))
             
             # Create Figure
             fig = matplotlib.figure.Figure(figsize=(8, 1.5), dpi=100)
             fig.patch.set_facecolor('#f0f0f0') # Matches default CTK light gray approx
             fig.subplots_adjust(left=0.05, right=0.98, top=0.9, bottom=0.15)
             
             ax = fig.add_subplot(111)
             # Set background of plot area
             ax.set_facecolor('#ffffff')
             
             # Plot Line
             ax.plot(x_vals, y_vals, color="#2980b9", linewidth=1.5)
             ax.fill_between(x_vals, y_vals, color="#3498db", alpha=0.2)
             
             # Y Axis formatted
             ax.set_ylim(0, 105)
             ax.set_yticks([0, 25, 50, 75, 100])
             ax.tick_params(labelsize=8)
             
             # Grid
             ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.7)
             
             # Hide X Axis labels (just show trend)
             ax.set_xticks([])

             canvas = FigureCanvasTkAgg(fig, master=chart_frame)
             canvas.draw()
             canvas.get_tk_widget().pack(fill="both", expand=True)
        else:
             info_frame = ctk.CTkFrame(io_container, fg_color="#e0e0e0", height=60, corner_radius=6)
             info_frame.pack(fill="x", pady=5)
             ctk.CTkLabel(info_frame, text="Computing I/O statistics... (Need > 1 sample)", text_color="#555555").place(relx=0.5, rely=0.5, anchor="center")

        # --- SMART TABLE ---
        table_container = ctk.CTkFrame(self)
        table_container.pack(fill="both", expand=True, padx=10, pady=10)
        
        table_scroll = ctk.CTkScrollableFrame(table_container, fg_color="transparent")
        table_scroll.pack(fill="both", expand=True)

        # Configure Grid in Scrollable Frame
        for i in range(7):
            table_scroll.grid_columnconfigure(i, weight=1)

        # HEADERS (Inside ScrollFrame for perfect alignment)
        cols = ["ID", "Status", "Attribute Name", "Current", "Worst", "Threshold", "Raw Values"]
        for i, c in enumerate(cols):
             lbl = ctk.CTkLabel(table_scroll, text=c, font=("Segoe UI", 12, "bold"), fg_color="transparent")
             lbl.grid(row=0, column=i, sticky="ew", padx=2, pady=5)
             
        # Add visual separator below header
        sep = ctk.CTkFrame(table_scroll, height=2, fg_color="gray50")
        sep.grid(row=1, column=0, columnspan=7, sticky="ew", pady=(0, 5))

        attributes = data.get("ata_smart_attributes", {}).get("table", [])
        
        # 1. ATA Support
        if not attributes:
            # Check for NVMe specific logs
            nvme_log = data.get("nvme_smart_health_information_log", {})
            if nvme_log:
                # Map NVMe keys to "Attribute-like" rows
                mapping = [
                     ("critical_warning", "Critical Warning", "N/A"),
                     ("temperature", "Temperature", "W"),
                     ("available_spare", "Available Spare", "%"),
                     ("available_spare_threshold", "Spare Threshold", "%"),
                     ("percentage_used", "Percentage Used", "%"),
                     ("data_units_read", "Data Units Read", "Count"),
                     ("data_units_written", "Data Units Written", "Count"),
                     ("host_read_commands", "Host Read Cmds", "Count"),
                     ("host_write_commands", "Host Write Cmds", "Count"),
                     ("controller_busy_time", "Busy Time", "Min"),
                     ("power_cycles", "Power Cycles", "Count"),
                     ("power_on_hours", "Power On Hours", "Hours"),
                     ("unsafe_shutdowns", "Unsafe Shutdowns", "Count"),
                     ("media_errors", "Media Errors", "Count"),
                     ("num_err_log_entries", "Error Log Entries", "Count"),
                ]
                
                for idx, (key, attr_name, unit) in enumerate(mapping):
                    val = nvme_log.get(key, 0)
                    row_dict = {
                        "id": idx + 1,
                        "name": attr_name,
                        "value": "---", # NVMe doesn't have normalized value
                        "worst": "---", 
                        "thresh": "---",
                        "raw": {"value": val, "string": f"{val}"}
                    }
                    if unit == "W": row_dict["raw"]["string"] = f"{val} ({val-273} °C)" if val > 273 else f"{val}"
                    attributes.append(row_dict)
        
        for idx, attr in enumerate(attributes):
            grid_row = idx + 2 # Offset by header + separator
            
            id_val = attr.get('id')
            id_hex = f"{id_val:02X}"
            name = attr.get("name", "Unknown").replace("_", " ")
            curr = attr.get("value", "---")
            worst = attr.get("worst", "---")
            thresh = attr.get("thresh", "---")
            raw_val = attr.get("raw", {}).get("value", 0)
            raw = attr.get("raw", {}).get("string", str(raw_val))
            
            # Analyze Status
            # Safely cast
            try:
                norm_int = int(curr)
                thresh_int = int(thresh)
            except:
                norm_int = 100
                thresh_int = 0
            
            # Rotation rate check for SSD logic
            is_ssd = (str(rot_rate) == "Solid State Device" or rot_rate == 0)
            rr = 0 if is_ssd else 7200
            
            status, note = self.monitor_logic.analyze_smart_attribute(id_val, raw_val, norm_int, thresh_int, rr)
            
            # Row Color based on status
            status_fg = "#2ecc71" # Green
            status_icon = "✔ OK"
            if status == "CRIT":
                status_fg = "#e74c3c" # Red
                status_icon = "✖ Fail"
            elif status == "WARN":
                status_fg = "#f39c12" # Orange
                status_icon = "⚠ Warn"
            
            # Check for NVMe critical warning special case
            if name == "Critical Warning" and raw_val > 0:
                 status_fg = "#e74c3c"
                 status_icon = "✖ Fail"

            # Alternate row colors
            row_bg = "transparent"
            if idx % 2 == 1:
                row_bg = ("#e5e5e5", "#333333") # Light/Dark mode gray
            
            row_frame = ctk.CTkFrame(table_scroll, fg_color=row_bg, corner_radius=0)
            row_frame.grid(row=grid_row, column=0, columnspan=7, sticky="ew")
            
            # Reconstruct grid relative to the row frame
            for i in range(7): row_frame.grid_columnconfigure(i, weight=1)

            widgets = [id_hex, status_icon, name, str(curr), str(worst), str(thresh), raw]
            for c_idx, val in enumerate(widgets):
                lbl = ctk.CTkLabel(row_frame, text=val, font=("Segoe UI", 12))
                
                if c_idx == 0: # ID
                     lbl.configure(font=("Segoe UI", 12, "bold"))
                elif c_idx == 1: # Status
                     lbl.configure(text=val, text_color=status_fg, font=("Segoe UI", 12, "bold"))
                elif c_idx == 2: # Name
                     pass # Normal
                
                lbl.grid(row=0, column=c_idx, sticky="ew", padx=2, pady=1)
                
                # Add tooltip for status if warning
                if c_idx == 1 and status != "OK":
                     ToolTip(lbl, note)

