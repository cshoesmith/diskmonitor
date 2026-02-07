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
        # Title Frame (Header Only)
        header_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        header_frame.pack(fill="x", padx=20, pady=(15, 10))

        header = ctk.CTkLabel(header_frame, text="Disk Health Dashboard", font=("Segoe UI", 20, "bold"))
        header.pack(side="left")

        # Main Table Container
        self.table_frame = ctk.CTkFrame(self.root)
        self.table_frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Footer Frame (Refresh, Hidden Toggle, About)
        footer_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        footer_frame.pack(fill="x", padx=20, pady=(0, 20))

        # Toggle Switch for Hidden Drives (Left)
        toggle_val = ctk.BooleanVar(value=self.show_hidden_drives)
        switch = ctk.CTkSwitch(
            footer_frame, 
            text="Show Hidden Drives", 
            command=self.toggle_hidden_drives,
            variable=toggle_val,
            onvalue=True,
            offvalue=False
        )
        switch.pack(side="left")

        # Right side controls container
        right_controls = ctk.CTkFrame(footer_frame, fg_color="transparent")
        right_controls.pack(side="right")

        # Manual refresh button
        btn_refresh = ctk.CTkButton(right_controls, text="Refresh Now", command=self._refresh_dashboard)
        btn_refresh.pack(side="left", padx=(0, 10))

        # About Button
        btn_about = ctk.CTkButton(
            right_controls, 
            text="About", 
            fg_color="transparent", 
            border_width=1, 
            border_color=("gray70", "gray30"),
            text_color=("gray10", "gray90"), 
            width=60,
            command=lambda: AboutWindow(self.root)
        )
        btn_about.pack(side="left")

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
             tooltip_text = f"Health Score: {score}%\nCheck details for health indicators."
        
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
        
        # Color Palette (Flat UI colors)
        colors = {
            "green": (46, 204, 113, 255),  # Green
            "yellow": (243, 156, 18, 255), # Orange/Yellow
            "red": (231, 76, 60, 255)      # Red
        }
        
        # Default to green if unknown
        base_color = colors.get(color, colors["green"])
        outline_color = (50, 50, 50, 255)
        
        # Draw HDD Body (Main Rectangle)
        # x0, y0, x1, y1
        body_rect = [14, 10, 50, 54] 
        dc.rectangle(body_rect, fill=base_color, outline=outline_color, width=3)
        
        # Draw "Label" area (White sticker on the drive)
        label_rect = [19, 15, 45, 36]
        dc.rectangle(label_rect, fill=(245, 245, 245, 255), outline=None)
        
        # Draw Platter/Spindle circle hint inside label to make it recognizable
        # Circle center (32, 25) radius 6
        cx, cy, r = 32, 25, 6
        dc.ellipse([cx-r, cy-r, cx+r, cy+r], outline=(180, 180, 180, 255), width=2)
        dc.ellipse([cx-1, cy-1, cx+1, cy+1], fill=(100, 100, 100, 255))
        
        # Bottom "Pins" or PCB hint (Little dark blocks at bottom)
        # To give it some tech texture
        dc.rectangle([18, 42, 24, 46], fill=(40, 40, 40, 180))
        dc.rectangle([29, 42, 35, 46], fill=(40, 40, 40, 180))
        dc.rectangle([40, 42, 46, 46], fill=(40, 40, 40, 180))

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

class AboutWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("About Disk Health Monitor")
        self.geometry("400x320")
        self.resizable(False, False)
        
        # Make modal
        self.attributes("-topmost", True)
        self.grab_set()

        # Content Container
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=20, pady=20)

        # Title
        title_lbl = ctk.CTkLabel(container, text="Disk Health Monitor", font=("Segoe UI", 20, "bold"))
        title_lbl.pack(pady=(10, 5))

        # Version
        ver_lbl = ctk.CTkLabel(container, text="Version 1.0.0", font=("Segoe UI", 12))
        ver_lbl.pack(pady=(0, 20))

        # Info
        info_text = (
            "A comprehensive disk health monitoring tool.\n"
            "Provides real-time S.M.A.R.T data analysis\n"
            "and partition visualization.\n\n"
            "Author: Chris Shoesmith\n"
            "License: MIT License"
        )
        info_lbl = ctk.CTkLabel(container, text=info_text, font=("Segoe UI", 13), justify="center")
        info_lbl.pack(pady=10)

        # Close Button
        close_btn = ctk.CTkButton(container, text="Close", command=self.destroy, width=100)
        close_btn.pack(side="bottom", pady=10)


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
        
        # --- SCROLLABLE MAIN CONTAINER ---
        self.main_scroll = ctk.CTkScrollableFrame(self)
        self.main_scroll.pack(fill="both", expand=True)

        # --- TOP HEADER (Model Name) ---
        header_frame = ctk.CTkFrame(self.main_scroll)
        header_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(header_frame, text=f"{model} : {capacity}", font=("Segoe UI", 24, "bold")).pack(side="left", padx=10)
        ctk.CTkLabel(header_frame, text="Disk Health Monitor", font=("Segoe UI", 12)).pack(side="right", padx=10)

        # --- INFO GRID (Firmware, Serial, etc) ---
        info_frame = ctk.CTkFrame(self.main_scroll)
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

        # --- EXTRACT HEALTH METRICS ---
        attributes = data.get("ata_smart_attributes", {}).get("table", [])
        nvme_log = data.get("nvme_smart_health_information_log", {})
        
        # 1. Total Written (TB)
        # NVMe: 'data_units_written' is typically 512*1000 bytes OR 512 bytes reported in thou units?
        # Smartctl man page says: "value reported in thousands (i.e. 1 = 512,000 bytes)"
        # So raw_val * 512,000 = bytes.
        tbw_str = "Unknown"
        if nvme_log and "data_units_written" in nvme_log:
             units = nvme_log["data_units_written"]
             tb_val = (units * 512000) / (1024**4)
             tbw_str = f"{tb_val:.2f} TB"
        
        # 2. SSD Life
        ssd_life_str = "N/A"
        if nvme_log and "percentage_used" in nvme_log:
             ssd_life_str = f"{100 - nvme_log['percentage_used']}%"
        else:
             # Try determining from ATA
             for aid in [231, 233, 169, 177]: # Common Life Left IDs
                 for a in attributes:
                     if a.get("id") == aid:
                         val = a.get("value", 100)
                         if 0 < val <= 100: 
                             ssd_life_str = f"{val}%"
                             break
                 if ssd_life_str != "N/A": break

        rows = [
            ("Firmware", firmware), ("Serial Number", serial),
            ("Rotation Rate", str(rot_rate)), ("Power On Count", str(power_count)),
            ("Interface", interface_val), ("Power On Hours", f"{power_hours}h ({power_hours/24:.1f} days)"),
            ("Standard", "ACS-3 / ATA8-ACS"), ("Features", "S.M.A.R.T."),
            ("Total Writes", tbw_str), ("SSD Life Left", ssd_life_str)
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
            part_container = ctk.CTkFrame(self.main_scroll, fg_color="transparent")
            part_container.pack(fill="x", padx=10, pady=10)
            
            ctk.CTkLabel(part_container, text="Partition Map", font=("Segoe UI", 14, "bold")).pack(anchor="w")
            
            # Chart Area
            chart_area = ctk.CTkFrame(part_container, fg_color="transparent")
            chart_area.pack(fill="x", expand=True)

            colors = ["#005a9e", "#0078D7", "#2B88D8", "#60A5FA", "#93C5FD", "#104a8e"]
            
            sizes = [p["size_gb"] for p in partitions]
            
            # Visual Sizing Logic: Ensure minimum width for small partitions
            visual_sizes = []
            if not sizes or sum(sizes) == 0:
                 sizes = [1]
                 visual_sizes = [1]
                 labels = ["Empty"]
                 colors = ["gray"]
            else:
                 total_raw = sum(sizes)
                 min_share = 0.05 # Reserve at least 5% width for visibility
                 
                 # Calculate raw shares
                 raw_shares = [s / total_raw for s in sizes]
                 
                 # Apply minimum floor
                 adj_shares = [max(s, min_share) for s in raw_shares]
                 
                 # Re-normalize to sum to 1.0
                 total_adj = sum(adj_shares)
                 visual_sizes = [s / total_adj for s in adj_shares]
                 
                 # Prepare labels
                 labels = []
                 for p in partitions:
                     l_txt = f"Part {p['number']}\n{p['size_gb']} GB"
                     labels.append(l_txt)

            # Create Figure - Wide and short
            fig = matplotlib.figure.Figure(figsize=(8, 1.2), dpi=100)
            # Use 'transparent' or match the CTK theme background roughly
            # Since CTK theming is complex, we stick to a neutral gray or white.
            # However, for a "Disk Administrator" look, white or control-color is best.
            fig.patch.set_color('#f0f0f0') 
            
            # Remove margins
            fig.subplots_adjust(left=0.02, right=0.98, top=0.95, bottom=0.05)
            
            ax = fig.add_subplot(111)
            ax.set_facecolor('#f0f0f0') # Background
            
            # Draw Horizontal Stacked Bar
            y_pos = [0]
            left = 0
            
            bar_patches = []
            tooltip_texts = []
            text_labels = [] # To store text objects
            
            for i, v_size in enumerate(visual_sizes):
                c = colors[i % len(colors)]
                # Bar renders with VISUAL size
                bars = ax.barh(y_pos, v_size, left=left, height=0.8, color=c, edgecolor='white', linewidth=1)
                bar_patch = bars.patches[0]
                bar_patches.append(bar_patch)
                
                # Tooltip Text (Real Data, not visual size)
                p_num = "N/A"
                if i < len(partitions):
                    p_num = partitions[i]['number']
                
                real_size = 0
                if i < len(sizes): real_size = sizes[i]
                
                tt = f"Partition {p_num}\nSize: {real_size} GB"
                if labels[i] == "Empty": tt = "Empty / Unallocated"
                tooltip_texts.append(tt)

                # Label logic: Only if bar is wide enough to read
                # Since we enforce min width, we can check granularity
                mid_x = left + (v_size / 2)
                
                lbl_text = ""
                font_s = 9
                
                if v_size > 0.15:
                    lbl_text = labels[i] # Full label
                elif v_size > 0.04: # ALLOW SMALLER BARS
                    # Compact label
                    if labels[i] != "Empty":
                         if i < len(partitions):
                              lbl_text = f"P{partitions[i]['number']}"
                    else:
                        lbl_text = "Empty"
                    font_s = 7 # Small font for small bars
                
                if lbl_text:
                     t_obj = ax.text(mid_x, 0, lbl_text, ha='center', va='center', 
                                     color='white', fontweight='bold', fontsize=font_s)
                     # Determine which index this text belongs to
                     # Store as tuple (text_artist, index)
                     text_labels.append( (t_obj, i) )
                
                left += v_size

            # Clean up axes (Hide everything)
            ax.set_xlim(0, 1)
            ax.set_ylim(-0.5, 0.5)
            ax.axis('off')

            # Tooltip Annotation
            annot = ax.annotate("", xy=(0,0), xytext=(0,10), textcoords="offset points",
                                bbox=dict(boxstyle="round", fc="#333333", ec="none", alpha=0.9),
                                color="white", ha='center', fontsize=8)
            annot.set_visible(False)

            def update_annot(x, y, idx):
                annot.xy = (x, y)
                annot.set_text(tooltip_texts[idx])

            def hover(event):
                vis = annot.get_visible()
                if event.inaxes == ax:
                    # Check text labels first (they are on top)
                    for t_obj, idx in text_labels:
                        cont, _ = t_obj.contains(event)
                        if cont:
                             update_annot(event.xdata, event.ydata, idx)
                             annot.set_visible(True)
                             canvas.draw_idle()
                             return

                    # Check bars
                    for i, bar in enumerate(bar_patches):
                        cont, _ = bar.contains(event)
                        if cont:
                            # Center tooltip on bar center
                            x = bar.get_x() + bar.get_width() / 2
                            y = bar.get_y() + bar.get_height() / 2
                            update_annot(x, y, i)
                            annot.set_visible(True)
                            canvas.draw_idle()
                            return
                            
                if vis:
                    annot.set_visible(False)
                    canvas.draw_idle()

            # Canvas
            canvas = FigureCanvasTkAgg(fig, master=chart_area)
            canvas.draw()
            canvas.get_tk_widget().pack(fill="both", expand=True, padx=20)
            
            # Connect hover event
            canvas.mpl_connect("motion_notify_event", hover)

        # --- IO LOAD CHART ---
        io_container = ctk.CTkFrame(self.main_scroll, fg_color="transparent")
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
             
             try:
                 # Clean data: Handle None values from DB migration
                 y_vals = [(x[1] if x[1] is not None else 0.0) for x in io_history]
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
             except Exception as e:
                 print(f"Plotting error: {e}")
                 chart_frame.destroy()
                 # Fallback to info frame
                 info_frame = ctk.CTkFrame(io_container, fg_color="#e0e0e0", height=60, corner_radius=6)
                 info_frame.pack(fill="x", pady=5)
                 info_frame.pack_propagate(False) # Force height
                 ctk.CTkLabel(info_frame, text=f"Error display statistics", text_color="red").place(relx=0.5, rely=0.5, anchor="center")
        else:
             info_frame = ctk.CTkFrame(io_container, fg_color="#e0e0e0", height=60, corner_radius=6)
             info_frame.pack(fill="x", pady=5)
             info_frame.pack_propagate(False) # Force height
             ctk.CTkLabel(info_frame, text="Computing I/O statistics... (Gathering samples)", text_color="#333333").place(relx=0.5, rely=0.5, anchor="center")

        # --- SMART TABLE ---
        table_container = ctk.CTkFrame(self.main_scroll)
        table_container.pack(fill="both", expand=True, padx=10, pady=10)
        
        ctk.CTkLabel(table_container, text="Detailed S.M.A.R.T. Statistics (Advanced)", font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=5, pady=5)
        
        table_scroll = ctk.CTkScrollableFrame(table_container, fg_color="transparent")
        table_scroll.pack(fill="both", expand=True)

        # Configure Grid in Scrollable Frame
        for i in range(7):
            table_scroll.grid_columnconfigure(i, weight=1)

        # HEADERS (Inside ScrollFrame for perfect alignment)
        cols = ["ID", "Status", "Attribute Name", "Current", "Worst", "Threshold", "Raw Values"]
        for i, c in enumerate(cols):
             align = "w" if i in [1, 2, 6] else "center"
             lbl = ctk.CTkLabel(table_scroll, text=c, font=("Segoe UI", 12, "bold"), fg_color="transparent")
             lbl.configure(anchor=align)
             lbl.grid(row=0, column=i, sticky="ew", padx=2, pady=5)
             
        # Add visual separator below header
        sep = ctk.CTkFrame(table_scroll, height=2, fg_color="gray50")
        sep.grid(row=1, column=0, columnspan=7, sticky="ew", pady=(0, 5))

        # We already extracted these earlier for the header metrics
        # attributes = data.get("ata_smart_attributes", {}).get("table", [])
        
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
                status_icon = "✖ " + note
            elif status == "WARN":
                status_fg = "#f39c12" # Orange
                status_icon = "⚠ " + note
                
            # Check for NVMe critical warning special case
            if name == "Critical Warning" and raw_val > 0:
                 status_fg = "#e74c3c"
                 status_icon = "✖ Failure Predicted"
            
            widgets = [id_hex, status_icon, name, str(curr), str(worst), str(thresh), raw]
            for c_idx, val in enumerate(widgets):
                lbl = ctk.CTkLabel(table_scroll, text=val, font=("Segoe UI", 12))
                
                # Align columns: Left for Status, Name, Raw; Center for others
                align = "w" if c_idx in [1, 2, 6] else "center"
                lbl.configure(anchor=align)

                if c_idx == 0: # ID
                     lbl.configure(font=("Segoe UI", 12, "bold"))
                elif c_idx == 1: # Status
                     lbl.configure(text=val, text_color=status_fg, font=("Segoe UI", 12, "bold"))
                elif c_idx == 2: # Name
                     pass # Normal
                
                # Use grid_row instead of 0
                lbl.grid(row=grid_row, column=c_idx, sticky="ew", padx=2, pady=1)

                # Add tooltip for status if warning
                if c_idx == 1 and status != "OK":
                     ToolTip(lbl, note)

