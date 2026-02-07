import subprocess
import json
import shutil
import random
import sys

class DiskHealthMonitor:
    def __init__(self):
        self.disks = []
        import os
        
        # Check local bin folder first (bundling support)
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if sys.platform == 'win32':
            bundled_smartctl = os.path.join(base_dir, 'bin', 'smartctl.exe')
        else:
            bundled_smartctl = os.path.join(base_dir, 'bin', 'smartctl')

        if os.path.exists(bundled_smartctl):
             self.smartctl_path = bundled_smartctl
        else:
             self.smartctl_path = shutil.which("smartctl")
        
        if sys.platform == 'win32' and not self.smartctl_path:
             # Common default install location for Windows
             possible_path = r"C:\Program Files\smartmontools\bin\smartctl.exe"
             if os.path.exists(possible_path):
                 self.smartctl_path = possible_path

        self.use_mock = False
        
        if not self.smartctl_path:
            # Final fallback for Linux if not in PATH
            if sys.platform.startswith('linux'):
                common_linux_paths = ["/usr/sbin/smartctl", "/usr/bin/smartctl", "/sbin/smartctl"]
                for p in common_linux_paths:
                    if os.path.exists(p):
                        self.smartctl_path = p
                        break
        
        if not self.smartctl_path:
            print("smartctl not found in PATH or bin folder. Using mock data.")
            self.use_mock = True

        self.check_permissions()
        self.io_stats_cache = {}

    def check_permissions(self):
        if sys.platform != 'win32' and not self.use_mock:
            import os
            if os.geteuid() != 0:
                print("\n" + "!"*60)
                print("WARNING: Disk Monitor usually requires ROOT privileges on Linux")
                print("to access raw disk devices. Please run with sudo.")
                print("!"*60 + "\n")

    def update_io_stats(self):
        """
        Fetches 'Percent Disk Time' for all physical disks on Windows.
        Blocks for 1 second to sample data.
        """
        if self.use_mock:
            self._update_mock_io_stats()
            return

        if sys.platform != 'win32':
            return

        try:
            # We use PowerShell to get counters reliably
            # InstanceName will be like "0 C:", "1 E:", "2", or "_total"
            cmd = [
                "powershell", "-Command", 
                "Get-Counter '\\PhysicalDisk(*)\% Disk Time' -SampleInterval 1 | Select-Object -ExpandProperty CounterSamples | Select-Object InstanceName, CookedValue | ConvertTo-Json"
            ]
            # Use a timeout because Get-Counter can sometimes hang? Usually safe with SampleInterval.
            result = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            
            if result.returncode == 0 and result.stdout.strip():
                try:
                    data = json.loads(result.stdout)
                    if isinstance(data, dict): data = [data]
                    
                    new_stats = {}
                    for item in data:
                        instance = item.get("InstanceName", "")
                        val = item.get("CookedValue", 0)
                        
                        # Parse disk index from InstanceName (e.g., "0 C:", "1")
                        # Usually starts with the number
                        parts = instance.split(' ')
                        if parts and parts[0].isdigit():
                            disk_idx = parts[0]
                            new_stats[disk_idx] = round(val, 1)
                            
                    self.io_stats_cache = new_stats
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            print(f"Error fetching IO stats: {e}")

    def _update_mock_io_stats(self):
        # Generate random load
        for i in range(5):
            # 80% chance of low load, 20% spike
            load = random.uniform(0, 5) if random.random() > 0.2 else random.uniform(10, 100)
            self.io_stats_cache[str(i)] = round(load, 1)

    def scan_disks(self):
        """Returns a list of device names/paths."""
        if self.use_mock:
            self.disks = self._get_mock_disks()
            return self.disks
        
        try:
            # --scan-open works on many platforms to find devices
            cmd = [self.smartctl_path, "--scan-open", "--json"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                devices = data.get("devices", [])
                # Extract device names. On windows might be /dev/sdX mapped or pdN
                self.disks = [d["name"] for d in devices]
                return self.disks
        except Exception as e:
            print(f"Error scanning disks: {e}")
        
        return []

    def get_disk_health(self, device):
        """Returns parsed JSON dictionary from smartctl -a"""
        data = {}
        if self.use_mock:
            data = self._get_mock_health(device)
        else:
            try:
                cmd = [self.smartctl_path, "-a", device, "--json"]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.stdout:
                    data = json.loads(result.stdout)
            except Exception as e:
                print(f"Error getting health for {device}: {e}")
        
        # Calculate score if data exists
        if data:
            data['health_score'] = self._calculate_health_score(data)
            
            # Fetch partitions and platform specific info
            # Attempt to extract serial from SMART data
            serial = data.get("serial_number") or data.get("device", {}).get("serial_number")

            if self.use_mock:
                data['partitions'] = self._get_mock_partitions(device)
                data['connection_detail'] = self._get_mock_connection_info(device)
            elif sys.platform == 'win32':
                data['partitions'] = self._get_windows_partitions(device)
                data['connection_detail'] = self._get_windows_connection_info(device, serial)
            else:
                # Linux / Unix
                data['partitions'] = self._get_linux_partitions(device)
                data['connection_detail'] = self._get_linux_connection_info(device)
        
        return data

    def _get_linux_connection_info(self, device):
        info = {
            "type": "Unknown",
            "is_external": False,
            "speed_limit": "Unknown"
        }
        try:
             # Use lsblk to get transport type
             # device is usually /dev/sda
             cmd = ["lsblk", "-d", "-o", "TRAN,ROTA", "-J", device]
             result = subprocess.run(cmd, capture_output=True, text=True)
             if result.returncode == 0:
                 output = json.loads(result.stdout)
                 devs = output.get("blockdevices", [])
                 if devs:
                     tran = devs[0].get("tran", "unknown").upper()
                     info["type"] = tran
                     
                     if tran == "USB":
                         info["is_external"] = True
                         info["speed_limit"] = "Max 480Mbps - 10Gbps"
                     elif tran == "SATA":
                         info["speed_limit"] = "Max 6 Gbps"
                     elif tran == "NVME":
                         info["speed_limit"] = "Max 32-64 Gbps"
                         
        except Exception as e:
            print(f"Linux connection info error: {e}")
            
        return info

    def _get_linux_partitions(self, device):
        partitions = []
        try:
            # lsblk to get partitions
            cmd = ["lsblk", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT", "-J", device]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                output = json.loads(result.stdout)
                devs = output.get("blockdevices", [])
                
                # Recursive function to find partitions
                def extract_parts(items):
                    for item in items:
                        if item.get("type") == "part":
                            # Parse size 
                            size_str = item.get("size", "0")
                            # lsblk gives human readable usually unless bytes requested.
                            # For simplicity we might just pass the string or try to convert.
                            # But detailed view expects float GB.
                            # Let's request bytes in future? For now just use raw string or parse.
                            # lsblk -b gives bytes.
                            pass

                # Re-run with bytes
                cmd = ["lsblk", "-b", "-o", "NAME,SIZE,TYPE,FSTYPE", "-J", device]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    output = json.loads(result.stdout)
                    root = output.get("blockdevices", [])
                    
                    # Flatten children
                    def collect_parts(node_list):
                        for node in node_list:
                            if node.get("type") == "part":
                                sz = float(node.get("size", 0))
                                partitions.append({
                                    "number": node.get("name"), # Use name like sda1
                                    "type": node.get("fstype") or "Linux",
                                    "size_gb": round(sz / (1024**3), 2)
                                })
                            if "children" in node:
                                collect_parts(node["children"])
                    
                    collect_parts(root)
                    
        except Exception as e:
            print(f"Linux partition error: {e}")
            
        return partitions

    def _get_windows_connection_info(self, device, serial=None):
        info = {
            "type": "Unknown",
            "is_external": False,
            "speed_limit": "Unknown"
        }
        
        # We need a Serial Number to match reliable
        if not serial: 
             return info

        if sys.platform == 'win32':
            try:
                # Get ALL physical disks to match serial
                cmd = ["powershell", "-Command", "Get-PhysicalDisk | Select-Object SerialNumber, BusType, MediaType, DeviceId, FriendlyName | ConvertTo-Json"]
                result = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                
                if result.returncode == 0 and result.stdout.strip():
                    disks_raw = json.loads(result.stdout)
                    if isinstance(disks_raw, dict): disks_raw = [disks_raw]
                    
                    matched_disk = None
                    target_serial = serial.replace("-", "").replace(" ", "").lower() if serial else ""
                    
                    # 1. Try Serial Number Match
                    if target_serial:
                        for d in disks_raw:
                            ps_serial = d.get("SerialNumber", "").replace("-", "").replace(" ", "").lower()
                            # Fuzzy match or exact match
                            if target_serial in ps_serial or ps_serial in target_serial:
                                matched_disk = d
                                break
                    
                    # 2. Fallback to Device Index (sda -> 0) if no serial match
                    if not matched_disk and device.startswith('/dev/sd'):
                         try:
                             letter = device[-1]
                             disk_index = ord(letter) - ord('a')
                             # Find disk with matching DeviceId
                             for d in disks_raw:
                                 # DeviceId is usually integer string
                                 if str(d.get("DeviceId")) == str(disk_index):
                                     matched_disk = d
                                     break
                         except:
                             pass

                    # 3. Fallback to FriendlyName fuzzy match (last resort)
                    if not matched_disk:
                        # Try matching Model name from smartctl
                        pass
                    
                    if matched_disk:
                        bus = matched_disk.get("BusType", "Unknown")
                        media = matched_disk.get("MediaType", "Unknown")
                        
                        info["type"] = bus
                        
                        # Heuristics
                        if bus == "USB":
                             info["is_external"] = True
                             info["speed_limit"] = "Max 5-10 Gbps (USB 3.x)"
                        elif bus == "NVMe":
                             info["is_external"] = False
                             info["speed_limit"] = "Max 32-64 Gbps (PCIe)"
                        elif bus == "SATA":
                             info["is_external"] = False
                             info["speed_limit"] = "Max 6 Gbps (SATA III)"
                        elif bus == "SAS":
                             info["speed_limit"] = "Max 12-24 Gbps"
                        
                        if media != "Unspecified":
                            info["media"] = media
                            
                        # Store DeviceId for IO stat mapping
                        if "DeviceId" in matched_disk:
                            info["device_id"] = str(matched_disk["DeviceId"])

            except Exception as e:
                print(f"Error fetching connection info: {e}")
                
        return info

    def _get_mock_connection_info(self, device):
        random.seed(device)
        bus = random.choice(["SATA", "NVMe", "USB"])
        info = {"type": bus, "is_external": bus == "USB", "speed_limit": "Unknown"}
        if bus == "SATA": info["speed_limit"] = "6 Gbps"
        elif bus == "NVMe": info["speed_limit"] = "32 Gbps"
        elif bus == "USB": info["speed_limit"] = "5 Gbps"
        return info

    def _get_windows_partitions(self, device):
        # Heuristic for Windows /dev/sdX -> Disk N mapping
        if sys.platform == 'win32' and device.startswith('/dev/sd'):
            try:
                # Map sda->0, sdb->1...
                letter = device[-1]
                disk_index = ord(letter) - ord('a')
                
                cmd = ["powershell", "-Command", f"Get-Partition -DiskNumber {disk_index} | Select-Object PartitionNumber, Type, Size | ConvertTo-Json"]
                result = subprocess.run(cmd, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                
                if result.returncode == 0 and result.stdout.strip():
                    parts_raw = json.loads(result.stdout)
                    # ConvertTo-Json returns dict if single item, list if multiple
                    if isinstance(parts_raw, dict):
                        parts_raw = [parts_raw]
                    
                    partitions = []
                    for p in parts_raw:
                        partitions.append({
                            "number": p.get("PartitionNumber", "?"),
                            "type": p.get("Type", "Unknown"),
                            "size_gb": round(p.get("Size", 0) / (1024**3), 2)
                        })
                    return partitions
            except Exception as e:
                print(f"Error fetching partitions: {e}")
        return []

    def _get_mock_partitions(self, device):
        # Deterministic mock partitions
        random.seed(device)
        total_gb = random.randint(250, 2000)
        p_count = random.randint(1, 4)
        
        parts = []
        remaining = total_gb
        for i in range(1, p_count + 1):
            if i == p_count:
                size = remaining
            else:
                size = random.randint(10, int(remaining * 0.8))
                
            remaining -= size
            parts.append({
                "number": i,
                "type": random.choice(["Basic Data", "System", "Recovery", "Reserved"]),
                "size_gb": size
            })
        return parts

    def _calculate_health_score(self, data):
        score = 100
        
        # 1. Check Global Smart Status
        passed = data.get("smart_status", {}).get("passed", True)
        if not passed:
            return 0
            
        # 2. Check NVMe Percentage Used
        nvme_log = data.get("nvme_smart_health_information_log", {})
        if "percentage_used" in nvme_log:
            used = nvme_log["percentage_used"]
            # NVMe life is 0 (new) to 100 (dead) usually.
            return max(0, 100 - used)

        # 3. Check ATA Attributes
        table = data.get("ata_smart_attributes", {}).get("table", [])
        
        # Critical IDs
        # 5: Reallocated Sectors
        # 187: Reported Uncorrectable
        # 197: Current Pending Sector
        # 198: Offline Uncorrectable
        
        crit_stats = {5: 0, 187: 0, 197: 0, 198: 0}
        
        for attr in table:
            id_ = attr.get("id")
            raw = attr.get("raw", {}).get("value", 0)
            
            if id_ == 5 and raw > 0:
                score -= (10 + min(raw, 40)) # Big penalty for first, then linear
            elif id_ == 197 and raw > 0:
                score -= (5 + min(raw, 20))
            elif id_ == 198 and raw > 0:
                score -= (5 + min(raw, 20))
            elif id_ == 187 and raw > 0:
                score -= min(raw, 50)
                
            # SSD Life Left (often 169, 173, 202, 230, 231, 233)
            # Some drives use ID 177 Wear Leveling Count
            if id_ == 231 or id_ == 233: # SSD Life Remaining often
                # If these are normalized values like "98", we might use them
                norm = attr.get("value", 100)
                if norm < 100 and norm > 0:
                    # If this is really life remaining, we could average it in
                    pass 

        return max(0, score)

    def analyze_smart_attribute(self, id_, raw, normalized, threshold, rotation_rate=0):
        """
        Returns (status, interpretation)
        status: "OK", "WARN", "CRIT"
        """
        status = "OK"
        note = "Good"
        
        # 1. Check Threshold Failure (Standard)
        if threshold and normalized and isinstance(threshold, (int, float)) and isinstance(normalized, (int, float)):
            if threshold > 0 and normalized <= threshold:
                return "CRIT", "Failed Threshold"

        # 2. Critical Attributes (Raw Value Analysis)
        if id_ == 5: # Reallocated Sectors
            if raw > 10: return "CRIT", f"{raw} bad sectors"
            if raw > 0: return "WARN", f"{raw} bad sectors"
        
        elif id_ == 197: # Current Pending
            if raw > 0: return "WARN", f"{raw} unstable sectors"
            
        elif id_ == 198: # Offline Uncorrectable
            if raw > 0: return "CRIT", f"{raw} uncorrectable"
            
        elif id_ == 187: # Reported Uncorrectable
            if raw > 0: return "CRIT", f"{raw} uncorrectable"
            
        elif id_ == 199: # UDMA CRC (Cable)
            if raw > 0: return "WARN", "Check Cable"
            
        elif id_ in [169, 173, 230, 231, 232, 233]: # SSD Life related
             # Only relevant if SSD (rot_rate == 0 usually implies SSD in our logic)
             if rotation_rate == 0:
                 if normalized and normalized < 10: return "CRIT", "Wearing Out"
                 # if normalized < 90: return "OK", "Normal Wear" 

        return status, note

    def _get_mock_disks(self):
        return ["/dev/sda", "/dev/sdb", "/dev/sdc", "/dev/sdd", "/dev/sde"]

    def _get_mock_health(self, device):
        # Generate some fake SMART data consistent for the device name seed
        random.seed(device)
        
        passed = random.random() > 0.1 # 10% chance of failure in mock
        status = "PASSED" if passed else "FAILED"
        
        # Critical attributes simulation
        reallocated = 0 if passed else random.randint(10, 1000)
        pending = 0 if passed else random.randint(1, 50)
        
        hours = random.randint(1000, 60000) # Up to ~7 years
        
        return {
            "device": {"name": device, "model": "Mock-Disk-2000", "serial_number": f"SN-{hash(device)}"},
            "smart_status": {"passed": passed},
            "power_on_time": {"hours": hours},
            "temperature": {"current": random.randint(30, 55)},
            "ata_smart_attributes": {
                "table": [
                    {"id": 5, "name": "Reallocated_Sector_Ct", "raw": {"value": reallocated}, "thresh": 10, "value": 100},
                    {"id": 9, "name": "Power_On_Hours", "raw": {"value": hours}, "thresh": 0, "value": 90},
                    {"id": 194, "name": "Temperature_Celsius", "raw": {"value": random.randint(30, 55)}, "thresh": 0, "value": 60},
                    {"id": 197, "name": "Current_Pending_Sector", "raw": {"value": pending}, "thresh": 0, "value": 100},
                ]
            }
        }
