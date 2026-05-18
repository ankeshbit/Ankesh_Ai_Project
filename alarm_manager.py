import json
import time
import threading
import datetime
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class AlarmManager:
    """
    Manages active alarms and timers for Nova.
    Handles background monitoring and persistence.
    """
    def __init__(self, storage_path: Path = None):
        if storage_path is None:
            storage_path = Path.home() / "nova_alarms.json"
        self.storage_path = storage_path
        self.alarms = [] # List of dicts: {"type": "alarm/timer", "time": "ISO timestamp", "label": "label"}
        self.running = False
        self.callback = None
        self.load_alarms()

    def set_callback(self, callback):
        """Set the function to be called when an alarm/timer triggers."""
        self.callback = callback

    def load_alarms(self):
        """Load alarms from persistent storage."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r") as f:
                    data = json.load(f)
                    # Filter out expired timers on load
                    now = datetime.datetime.now()
                    self.alarms = [
                        a for a in data 
                        if datetime.datetime.fromisoformat(a["time"]) > now
                    ]
            except Exception as e:
                logger.error(f"Error loading alarms: {e}")
                self.alarms = []

    def save_alarms(self):
        """Save active alarms to persistent storage."""
        try:
            with open(self.storage_path, "w") as f:
                json.dump(self.alarms, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving alarms: {e}")

    def add_alarm(self, alarm_time: datetime.datetime, label: str = "Alarm"):
        """Add a new alarm."""
        self.alarms.append({
            "type": "alarm",
            "time": alarm_time.isoformat(),
            "label": label
        })
        self.save_alarms()
        logger.info(f"Alarm set for {alarm_time.strftime('%H:%M:%S')}")

    def add_timer(self, seconds: int, label: str = "Timer"):
        """Add a new timer."""
        expiry = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
        self.alarms.append({
            "type": "timer",
            "time": expiry.isoformat(),
            "label": label
        })
        self.save_alarms()
        logger.info(f"Timer set for {seconds} seconds (ends at {expiry.strftime('%H:%M:%S')})")

    def clear_all(self):
        """Cancel all active alarms and timers."""
        self.alarms = []
        self.save_alarms()
        logger.info("All alarms and timers cleared.")

    def start(self):
        """Start the background monitoring thread."""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.thread.start()
            logger.info("Alarm monitoring service started.")

    def stop(self):
        """Stop the background monitoring thread."""
        self.running = False

    def _monitor_loop(self):
        """Continuous loop checking for expired alarms/timers."""
        while self.running:
            now = datetime.datetime.now()
            triggered = []
            
            # Check for expired items
            for alarm in self.alarms[:]:
                expiry = datetime.datetime.fromisoformat(alarm["time"])
                if now >= expiry:
                    triggered.append(alarm)
                    self.alarms.remove(alarm)
            
            if triggered:
                self.save_alarms()
                for item in triggered:
                    if self.callback:
                        self.callback(item["type"], item["label"])
            
            time.sleep(1) # Check every second

    def get_status_summary(self) -> str:
        """Return a string summary of active alarms/timers."""
        if not self.alarms:
            return "No active alarms or timers."
        
        summary = []
        for a in self.alarms:
            expiry = datetime.datetime.fromisoformat(a["time"])
            diff = expiry - datetime.datetime.now()
            mins, secs = divmod(int(diff.total_seconds()), 60)
            summary.append(f"{a['type'].title()} '{a['label']}' in {mins}m {secs}s")
        
        return " | ".join(summary)
