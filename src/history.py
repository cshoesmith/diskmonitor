import sqlite3
import datetime
import os

class DiskHistory:
    def __init__(self, db_path="disk_history.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS disk_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                serial_number TEXT,
                timestamp DATETIME,
                reallocated_sectors INTEGER,
                read_errors INTEGER,
                power_on_hours INTEGER,
                pending_sectors INTEGER
            )
        """)
        
        # Migration: Add io_load if missing
        try:
            c.execute("ALTER TABLE disk_stats ADD COLUMN io_load REAL")
        except sqlite3.OperationalError:
            pass # Already exists

        # Migration: Add write_errors if missing
        try:
            c.execute("ALTER TABLE disk_stats ADD COLUMN write_errors INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass # Already exists

        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_serial_time 
            ON disk_stats (serial_number, timestamp)
        """)
        conn.commit()
        conn.close()

    def log_status(self, serial, rsc, read_err, hours, pending, io_load=0.0, write_err=0):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            INSERT INTO disk_stats 
            (serial_number, timestamp, reallocated_sectors, read_errors, power_on_hours, pending_sectors, io_load, write_errors)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (serial, datetime.datetime.now(), rsc, read_err, hours, pending, io_load, write_err))
        conn.commit()
        conn.close()
        
    def get_io_history(self, serial, limit=60):
        """Returns list of (timestamp, io_load) tuples."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            SELECT timestamp, io_load
            FROM disk_stats
            WHERE serial_number = ?
            ORDER BY timestamp ASC
            LIMIT ?
        """, (serial, limit))
        rows = c.fetchall()
        conn.close()
        return rows

    def get_latest_stats(self, serial):
        """Returns the most recent stats record."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            SELECT reallocated_sectors, read_errors, power_on_hours, pending_sectors, timestamp
            FROM disk_stats
            WHERE serial_number = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (serial,))
        row = c.fetchone()
        conn.close()
        return row

    def analyze_trend(self, serial):
        """
        Analyzes history for the given disk.
        Returns a dict with 'status', 'message', 'rsc_change', etc.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Get last 2 records to compare immediate change
        c.execute("""
            SELECT * FROM disk_stats 
            WHERE serial_number = ? 
            ORDER BY timestamp DESC LIMIT 2
        """, (serial,))
        rows = c.fetchall()
        
        # Get oldest record for long term comparison
        c.execute("""
            SELECT * FROM disk_stats 
            WHERE serial_number = ? 
            ORDER BY timestamp ASC LIMIT 1
        """, (serial,))
        oldest = c.fetchone()
        
        conn.close()

        result = {
            "status": "OK",
            "messages": [],
            "rsc_trend": 0,
            "read_err_trend": 0
        }

        if not rows:
            return result

        current = rows[0]
        
        # Check against oldest known state
        if oldest:
            rsc_growth = current['reallocated_sectors'] - oldest['reallocated_sectors']
            if rsc_growth > 0:
                result["status"] = "WARNING"
                result["messages"].append(f"Reallocated Sectors increased by {rsc_growth} since first scan.")
                result['rsc_trend'] = rsc_growth

        # Check immediate rapid change (if we have previous scan)
        if len(rows) > 1:
            prev = rows[1]
            rsc_diff = current['reallocated_sectors'] - prev['reallocated_sectors']
            read_diff = current['read_errors'] - prev['read_errors']
            
            # Check for write errors if column exists
            write_diff = 0
            if 'write_errors' in current.keys() and 'write_errors' in prev.keys():
                 # Handle None
                 cur_w = current['write_errors'] or 0
                 prev_w = prev['write_errors'] or 0
                 write_diff = cur_w - prev_w

            if rsc_diff > 0:
                result["status"] = "CRITICAL"
                result["messages"].append(f"New Reallocated Sectors detected! (+{rsc_diff})")
            
            if read_diff > 0:
                 result["messages"].append(f"New Read Errors detected! (+{read_diff})")

            if write_diff > 0:
                 result["messages"].append(f"New Write Errors detected! (+{write_diff})")

        # Absolute thresholds
        if current['reallocated_sectors'] > 0:
             if result["status"] == "OK":
                 result["status"] = "WARNING" # Promote to warning just for having them
                 if 'reallocated_sectors' not in str(result['messages']):
                     result["messages"].append(f"Has {current['reallocated_sectors']} Reallocated Sectors.")

        return result
