import json
import os
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
        self.storage_path = Path(storage_path)
        self.alarms = []  # List of dicts: {"type": "alarm/timer", "time": "ISO timestamp", "label": "label"}
        self.running = False
        self.thread = None
        self.callback = None
        # The monitor thread and the command thread both touch self.alarms.
        self._lock = threading.RLock()
        self.load_alarms()

    def set_callback(self, callback):
        """Set the function to be called when an alarm/timer triggers."""
        self.callback = callback

    def load_alarms(self):
        """Load alarms from persistent storage, dropping expired or malformed entries."""
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Error loading alarms: {e}")
            return

        now = datetime.datetime.now()
        valid = []
        for entry in data if isinstance(data, list) else []:
            try:
                # One bad entry must not discard every other saved alarm.
                if datetime.datetime.fromisoformat(entry["time"]) > now:
                    valid.append(entry)
            except (KeyError, TypeError, ValueError):
                logger.warning(f"Skipping malformed alarm entry: {entry!r}")
        with self._lock:
            self.alarms = valid

    def save_alarms(self):
        """Save active alarms to persistent storage (atomic write)."""
        with self._lock:
            snapshot = list(self.alarms)
        try:
            tmp_path = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=4)
            os.replace(tmp_path, self.storage_path)
        except Exception as e:
            logger.error(f"Error saving alarms: {e}")

    def add_alarm(self, alarm_time: datetime.datetime, label: str = "Alarm"):
        """Add a new alarm."""
        with self._lock:
            self.alarms.append({
                "type": "alarm",
                "time": alarm_time.isoformat(),
                "label": label,
            })
        self.save_alarms()
        logger.info(f"Alarm set for {alarm_time.strftime('%H:%M:%S')}")

    def add_timer(self, seconds: int, label: str = "Timer"):
        """Add a new timer."""
        expiry = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
        with self._lock:
            self.alarms.append({
                "type": "timer",
                "time": expiry.isoformat(),
                "label": label,
            })
        self.save_alarms()
        logger.info(f"Timer set for {seconds} seconds (ends at {expiry.strftime('%H:%M:%S')})")

    def clear_all(self):
        """Cancel all active alarms and timers."""
        with self._lock:
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

    def _collect_expired(self) -> list:
        """Remove and return every alarm/timer whose time has come."""
        now = datetime.datetime.now()
        triggered = []
        with self._lock:
            for alarm in self.alarms[:]:
                try:
                    expired = now >= datetime.datetime.fromisoformat(alarm["time"])
                except (KeyError, TypeError, ValueError):
                    logger.warning(f"Dropping malformed alarm entry: {alarm!r}")
                    self.alarms.remove(alarm)
                    continue
                if expired:
                    triggered.append(alarm)
                    self.alarms.remove(alarm)
        return triggered

    def _fire(self, item: dict):
        """Invoke the callback, never letting its failure kill the monitor."""
        if not self.callback:
            return
        try:
            self.callback(item["type"], item["label"])
        except Exception:
            logger.exception("Alarm callback failed")

    def _monitor_loop(self):
        """Continuous loop checking for expired alarms/timers."""
        while self.running:
            try:
                triggered = self._collect_expired()
                if triggered:
                    self.save_alarms()
                    for item in triggered:
                        # Run on its own thread: the callback beeps and speaks, which
                        # takes seconds and would otherwise delay every other alarm.
                        threading.Thread(target=self._fire, args=(item,), daemon=True).start()
            except Exception:
                logger.exception("Alarm monitor error")
            time.sleep(1)  # Check every second

    def get_status_summary(self) -> str:
        """Return a string summary of active alarms/timers."""
        with self._lock:
            alarms = list(self.alarms)
        if not alarms:
            return "No active alarms or timers."

        summary = []
        now = datetime.datetime.now()
        for a in sorted(alarms, key=lambda item: item.get("time", "")):
            try:
                expiry = datetime.datetime.fromisoformat(a["time"])
            except (KeyError, TypeError, ValueError):
                continue
            total = max(0, int((expiry - now).total_seconds()))
            hours, rem = divmod(total, 3600)
            mins, secs = divmod(rem, 60)
            if hours:
                remaining = f"{hours}h {mins}m {secs}s"
            else:
                remaining = f"{mins}m {secs}s"
            summary.append(f"{a['type'].title()} '{a['label']}' in {remaining}")

        return " | ".join(summary) if summary else "No active alarms or timers."
