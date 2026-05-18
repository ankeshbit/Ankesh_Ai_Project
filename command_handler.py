"""
command_handler.py
------------------
Parses user intent and routes commands to the correct action handler.
Covers: app launching, web search, time/date, music playback,
        system controls, and engineering mode triggers.
"""

import os
import re
import json
import datetime
import importlib.util
import webbrowser
import subprocess
import random
import logging
import platform
from pathlib import Path

logger = logging.getLogger(__name__)


class CommandHandler:
    """
    Detects and executes system-level and utility commands spoken by the user.
    Returns a (response_text, handled) tuple so main.py knows whether to
    also query the AI brain.
    """

    # ─── App Name → Executable Mapping ───────────────────────────────────────
    APP_MAP = {
        "chrome":       ["chrome", "google-chrome", "chromium-browser"],
        "firefox":      ["firefox"],
        "edge":         ["msedge", "microsoft-edge"],
        "microsoft edge": ["msedge"],
        "brave":        ["brave"],
        "notepad":      ["notepad"],
        "vs code":      ["code"],
        "vscode":       ["code"],
        "visual studio code": ["code"],
        "calculator":   ["calc"],
        "paint":        ["mspaint"],
        "command prompt": ["cmd"],
        "terminal":     ["cmd", "bash", "zsh"],
        "word":         ["winword"],
        "excel":        ["excel"],
        "powerpoint":   ["powerpnt"],
        "spotify":      ["spotify"],
        "vlc":          ["vlc"],
        "file explorer": ["explorer"],
        "task manager": ["taskmgr"],
    }

    # ─── Website Mapping ─────────────────────────────────────────────────────
    WEB_MAP = {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "gmail": "https://mail.google.com",
        "github": "https://github.com",
        "chatgpt": "https://chatgpt.com",
        "netflix": "https://www.netflix.com"
    }


    def __init__(self, config: dict, alarm_manager=None):
        self.config = config
        self.alarm_manager = alarm_manager
        self.name = config.get("user_name", "Sir")
        self.music_folder = config.get("music_folder", str(Path.home() / "Music"))
        self.todo_file = Path.home() / "nova_todo.json"
        self.notes_file = Path.home() / "nova_notes.txt"
        self.plugin_triggers = []
        self._load_plugins()

    def handle(self, text: str) -> tuple[str, bool]:
        """
        Main dispatcher. Checks text against known command patterns.

        Args:
            text (str): Lowercased user input.

        Returns:
            tuple[str, bool]: (Response text, True if handled by commands)
        """
        text = text.lower().strip()

        # ── Time & Date ──────────────────────────────────────────────────────
        if self._match(text, ["what time", "current time", "tell me the time", "what's the time"]):
            return self._get_time(), True

        if self._match(text, ["what date", "today's date", "current date", "what day is"]):
            return self._get_date(), True

        if self._match(text, ["what day", "day today"]):
            return self._get_day(), True

        # ── Open Applications ────────────────────────────────────────────────
        if self._match(text, ["open ", "launch ", "start "]):
            return self._open_app(text), True

        # ── Google Search ────────────────────────────────────────────────────
        if self._match(text, ["search", "google", "search for", "look up"]):
            return self._search_google(text), True

        # ── YouTube ──────────────────────────────────────────────────────────
        if self._match(text, ["play on youtube", "youtube", "watch"]):
            return self._search_youtube(text), True

        # ── Music Playback ───────────────────────────────────────────────────
        if self._match(text, ["play music", "play a song", "play some music", "shuffle music"]):
            return self._play_music(), True

        # ── System Controls ──────────────────────────────────────────────────
        if self._match(text, ["shutdown", "shut down the computer"]):
            return self._shutdown(), True

        if self._match(text, ["restart", "reboot"]):
            return self._restart(), True

        if self._match(text, ["sleep", "hibernate"]):
            return self._sleep(), True

        if self._match(text, ["increase volume", "volume up", "louder"]):
            return self._volume("up"), True

        if self._match(text, ["decrease volume", "volume down", "quieter", "lower volume"]):
            return self._volume("down"), True

        if self._match(text, ["mute", "unmute"]):
            return self._volume("mute"), True

        # ── Clear Memory ─────────────────────────────────────────────────────
        if self._match(text, ["clear memory", "forget everything", "reset conversation"]):
            return f"Memory cleared, {self.name}. Starting fresh.", True

        # ── Screenshot ───────────────────────────────────────────────────────
        if self._match(text, ["take screenshot", "capture screen"]):
            return self._screenshot(), True

        # ── System Stats ─────────────────────────────────────────────────────
        if self._match(text, ["system status", "battery level", "cpu usage", "memory usage", "system stats"]):
            return self._system_stats(), True

        # ── Weather ──────────────────────────────────────────────────────────
        if self._match(text, ["weather", "temperature outside", "is it raining"]):
            return self._weather(), True

        # ── Plugins ────────────────────────────────────────────────────────
        plugin_response = self._handle_plugin_triggers(text)
        if plugin_response:
            return plugin_response, True
            
        # ── Productivity ─────────────────────────────────────────────────────
        if "to do list" in text or "to-do list" in text:
            if any(w in text for w in ["add", "put"]):
                return self._add_todo(text), True
            elif any(w in text for w in ["clear", "empty"]):
                return self._clear_todo(), True
            elif any(w in text for w in ["read", "what is", "what's"]):
                return self._read_todo(), True
                
        if "remind me to" in text:
            return self._add_todo(text), True

        if self._match(text, ["take a note", "write down", "note this"]):
            return self._take_note(text), True

        if self._match(text, ["read my notes", "what are my notes", "what did i note"]):
            return self._read_notes(), True
            
        # ── Fun / Utils ──────────────────────────────────────────────────────
        if self._match(text, ["flip a coin", "toss a coin"]):
            return f"It landed on {random.choice(['Heads', 'Tails'])}, {self.name}.", True
            
        if self._match(text, ["roll a dice", "roll a die"]):
            return f"You rolled a {random.randint(1, 6)}, {self.name}.", True

        # ── Alarms & Timers ──────────────────────────────────────────────────
        if "timer" in text or "alarm" in text:
            if any(w in text for w in ["set", "start", "create"]):
                return self._set_alarm_timer(text), True
            if any(w in text for w in ["list", "show", "what are my"]):
                return self._list_alarms(), True
            if any(w in text for w in ["cancel", "clear", "stop", "delete"]):
                return self._clear_alarms(), True

        # ── Close / Exit ─────────────────────────────────────────────────────
        if self._match(text, ["goodbye", "bye", "exit", "quit", "shut yourself down", "sleep mode", "close yourself", "close nova", "turn off", "terminate"]):
            return f"Goodbye, {self.name}. Nova signing off. Stay extraordinary.", False

        return "", False  # Not handled — pass to AI brain

    def _load_plugins(self) -> None:
        """Discover plugin modules under `plugins/` and register their triggers."""
        plugins_dir = Path(__file__).resolve().parent / "plugins"
        if not plugins_dir.exists():
            logger.info("Plugins directory not found: %s", plugins_dir)
            return

        loaded = []
        for plugin_path in sorted(plugins_dir.glob("*.py")):
            if plugin_path.name.startswith("_"):
                continue

            module_name = f"plugins.{plugin_path.stem}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, plugin_path)
                if not spec or not spec.loader:
                    continue

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                triggers = getattr(module, "TRIGGERS", [])
                execute = getattr(module, "execute", None)
                if not callable(execute):
                    logger.warning("Plugin '%s' does not expose a callable execute()", plugin_path.name)
                    continue

                for trigger in triggers:
                    phrases = [phrase.lower() for phrase in trigger.get("phrases", []) if phrase]
                    if not phrases:
                        continue
                    loaded.append({
                        "name": trigger.get("name", plugin_path.stem),
                        "phrases": phrases,
                        "trigger": trigger,
                        "execute": execute,
                        "module": module,
                    })
                logger.info("Loaded plugin: %s", plugin_path.name)
            except Exception as exc:
                logger.exception("Failed to load plugin '%s': %s", plugin_path.name, exc)

        self.plugin_triggers = loaded

    def _handle_plugin_triggers(self, text: str) -> str:
        """Route recognized plugin phrases to their execute() handlers."""
        for plugin in self.plugin_triggers:
            if not self._match(text, plugin["phrases"]):
                continue

            try:
                result = plugin["execute"](
                    text=text,
                    config=self.config,
                    trigger=plugin["trigger"],
                    alarm_manager=self.alarm_manager,
                    handler=self,
                )
            except TypeError:
                result = plugin["execute"](text)

            if isinstance(result, tuple):
                response_text = result[0]
            else:
                response_text = result

            if response_text:
                return response_text

        return ""

    # ─── Handler Methods ──────────────────────────────────────────────────────

    def _get_time(self) -> str:
        now = datetime.datetime.now()
        time_str = now.strftime("%I:%M %p")
        return f"The current time is {time_str}, {self.name}."

    def _get_date(self) -> str:
        today = datetime.date.today()
        date_str = today.strftime("%B %d, %Y")
        return f"Today is {date_str}, {self.name}."

    def _get_day(self) -> str:
        day = datetime.datetime.now().strftime("%A")
        return f"Today is {day}, {self.name}."

    def _open_app(self, text: str) -> str:
        """Parse app name from text and attempt to open it."""
        # 1. Check for websites
        for site_name, url in self.WEB_MAP.items():
            if site_name in text:
                webbrowser.open(url)
                logger.info(f"Opened website: {site_name}")
                return f"Opening {site_name.title()} for you, {self.name}."

        # 2. Check for local apps
        for app_name, executables in self.APP_MAP.items():
            if app_name in text:
                for exe in executables:
                    try:
                        if platform.system() == "Windows":
                            # Use 'start' command to properly launch Windows registered apps (aliases)
                            result = os.system(f"start {exe}")
                            if result != 0:
                                continue # try next executable
                        else:
                            subprocess.Popen([exe])
                        
                        logger.info(f"Opened application: {app_name}")
                        return f"Opening {app_name.title()} for you, {self.name}."
                    except Exception:
                        continue
                return f"I couldn't find {app_name.title()} on your system, {self.name}."

        return f"I'm not sure which application you'd like to open, {self.name}. Could you be more specific?"

    def _search_google(self, text: str) -> str:
        """Extract search query and open browser."""
        query = ""
        for trigger in ["search for", "search", "google", "look up"]:
            if trigger in text:
                query = text.split(trigger, 1)[-1].strip()
                break
        if not query:
            query = text
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        webbrowser.open(url)
        return f"Searching Google for '{query}', {self.name}."

    def _search_youtube(self, text: str) -> str:
        """Search YouTube for a video."""
        for trigger in ["play on youtube", "youtube", "watch"]:
            if trigger in text:
                query = text.split(trigger, 1)[-1].strip()
                break
        else:
            query = text
        url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
        webbrowser.open(url)
        return f"Looking up '{query}' on YouTube, {self.name}."

    def _play_music(self) -> str:
        """Play a random music file from the configured music folder."""
        folder = Path(self.music_folder)
        if not folder.exists():
            return f"I couldn't locate your music folder at '{self.music_folder}', {self.name}. Please update config.json."

        audio_exts = [".mp3", ".wav", ".flac", ".m4a", ".ogg"]
        songs = [f for f in folder.iterdir() if f.suffix.lower() in audio_exts]

        if not songs:
            return f"No music files found in '{self.music_folder}', {self.name}."

        song = random.choice(songs)
        try:
            os.startfile(str(song)) if platform.system() == "Windows" else subprocess.Popen(["xdg-open", str(song)])
            logger.info(f"Playing: {song.name}")
            return f"Playing '{song.stem}' for you, {self.name}. Enjoy."
        except Exception as e:
            logger.error(f"Music playback error: {e}")
            return f"Unable to play music right now, {self.name}."

    def _shutdown(self) -> str:
        if platform.system() == "Windows":
            os.system("shutdown /s /t 10")
            return f"System shutdown initiated. You have 10 seconds, {self.name}. Goodbye."
        else:
            os.system("sudo shutdown -h +1")
            return f"Shutdown scheduled in 1 minute, {self.name}."

    def _restart(self) -> str:
        if platform.system() == "Windows":
            os.system("shutdown /r /t 10")
            return f"Restarting the system in 10 seconds, {self.name}."
        else:
            os.system("sudo reboot")
            return f"Initiating reboot, {self.name}."

    def _sleep(self) -> str:
        if platform.system() == "Windows":
            os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
            return f"Putting the system to sleep, {self.name}."
        return f"Sleep/hibernate control isn't configured for your OS, {self.name}."

    def _volume(self, direction: str) -> str:
        """
        Platform-aware volume control:
        - Windows: PyCAW (pycaw library)
        - macOS: osascript subprocess calls
        - Linux: pactl subprocess calls
        """
        system = platform.system()

        try:
            if system == "Windows":
                return self._volume_windows(direction)
            elif system == "Darwin":  # macOS
                return self._volume_macos(direction)
            elif system == "Linux":
                return self._volume_linux(direction)
            else:
                return f"Volume control not supported for {system}, {self.name}."
        except Exception as e:
            logger.error(f"Volume control error: {e}")
            return f"Volume control encountered an issue, {self.name}."

    def _volume_windows(self, direction: str) -> str:
        """Volume control for Windows using PyCAW."""
        try:
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            current = volume.GetMasterScalarVolume()

            if direction == "up":
                volume.SetMasterScalarVolume(min(1.0, current + 0.1), None)
                return f"Volume increased, {self.name}."
            elif direction == "down":
                volume.SetMasterScalarVolume(max(0.0, current - 0.1), None)
                return f"Volume decreased, {self.name}."
            elif direction == "mute":
                muted = volume.GetMute()
                volume.SetMute(not muted, None)
                return f"Volume {'unmuted' if muted else 'muted'}, {self.name}."
        except ImportError:
            logger.warning("pycaw not installed. Install with: pip install pycaw comtypes")
        return f"Volume control unavailable on Windows, {self.name}."

    def _volume_macos(self, direction: str) -> str:
        """Volume control for macOS using osascript."""
        try:
            if direction == "up":
                subprocess.run(
                    ["osascript", "-e", "set volume output volume ((output volume of (get volume settings)) + 10)"],
                    check=True,
                    capture_output=True
                )
                return f"Volume increased, {self.name}."
            elif direction == "down":
                subprocess.run(
                    ["osascript", "-e", "set volume output volume ((output volume of (get volume settings)) - 10)"],
                    check=True,
                    capture_output=True
                )
                return f"Volume decreased, {self.name}."
            elif direction == "mute":
                # Toggle mute by setting output mute status
                subprocess.run(
                    ["osascript", "-e", "set volume output muted (not (output muted of (get volume settings)))"],
                    check=True,
                    capture_output=True
                )
                return f"Volume mute toggled, {self.name}."
        except subprocess.CalledProcessError as e:
            logger.error(f"macOS volume control error: {e}")
        return f"Volume control failed on macOS, {self.name}."

    def _volume_linux(self, direction: str) -> str:
        """Volume control for Linux using pactl (PulseAudio)."""
        try:
            # Get current sink
            result = subprocess.run(
                ["pactl", "get-default-sink"],
                capture_output=True,
                text=True,
                check=True
            )
            sink = result.stdout.strip()

            if direction == "up":
                subprocess.run(
                    ["pactl", "set-sink-volume", sink, "+5%"],
                    check=True,
                    capture_output=True
                )
                return f"Volume increased, {self.name}."
            elif direction == "down":
                subprocess.run(
                    ["pactl", "set-sink-volume", sink, "-5%"],
                    check=True,
                    capture_output=True
                )
                return f"Volume decreased, {self.name}."
            elif direction == "mute":
                subprocess.run(
                    ["pactl", "set-sink-mute", sink, "toggle"],
                    check=True,
                    capture_output=True
                )
                return f"Volume mute toggled, {self.name}."
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error(f"Linux volume control error (pactl not found or failed): {e}")
            logger.info("Install PulseAudio tools: sudo apt-get install pulseaudio-utils")
        return f"Volume control failed on Linux, {self.name}."

    def _screenshot(self) -> str:
        try:
            import pyautogui
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = Path.home() / f"nova_screenshot_{timestamp}.png"
            pyautogui.screenshot(str(save_path))
            return f"Screenshot saved to {save_path}, {self.name}."
        except ImportError:
            return f"Screenshot requires pyautogui. Please install it, {self.name}."
        except Exception as e:
            logger.error(f"Screenshot error: {e}")
            return f"Couldn't capture a screenshot, {self.name}."

    def _system_stats(self) -> str:
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.5)
            ram = psutil.virtual_memory().percent
            battery = psutil.sensors_battery()
            
            stats = f"CPU usage is at {cpu} percent, and memory usage is at {ram} percent. "
            if battery:
                plugged = "plugged in" if battery.power_plugged else "on battery power"
                stats += f"The system is running {plugged} at {battery.percent} percent."
            return stats
        except ImportError:
            return f"System statistics module psutil is not installed, {self.name}."
        except Exception as e:
            logger.error(f"System stats error: {e}")
            return f"I am unable to retrieve system statistics right now, {self.name}."

    def _weather(self) -> str:
        try:
            import requests
            res = requests.get("https://wttr.in/?format=%l:+%C+%t", timeout=5)
            if res.status_code == 200:
                data = res.text.strip().replace("+", "")
                return f"The current weather is {data}, {self.name}."
            return f"I couldn't fetch the weather data at this moment, {self.name}."
        except Exception as e:
            logger.error(f"Weather error: {e}")
            return f"My weather sensors are currently offline, {self.name}."

    # ─── Productivity ─────────────────────────────────────────────────────────

    def _add_todo(self, text: str) -> str:
        if "remind me to" in text:
            item = text.split("remind me to", 1)[-1].strip()
        else:
            item = text.replace("to my to do list", "").replace("to my to-do list", "").replace("on my to do list", "").replace("add", "").replace("put", "").strip()

        if not item:
            return f"I didn't catch what you wanted me to add, {self.name}."

        todos = []
        if self.todo_file.exists():
            try:
                with open(self.todo_file, "r") as f:
                    todos = json.load(f)
            except Exception:
                pass
        
        todos.append(item)
        try:
            with open(self.todo_file, "w") as f:
                json.dump(todos, f)
            return f"I've added '{item}' to your to-do list, {self.name}."
        except Exception as e:
            logger.error(f"Todo error: {e}")
            return f"I was unable to save to your to-do list, {self.name}."

    def _read_todo(self) -> str:
        if not self.todo_file.exists():
            return f"Your to-do list is currently empty, {self.name}."
        try:
            with open(self.todo_file, "r") as f:
                todos = json.load(f)
            if not todos:
                return f"Your to-do list is currently empty, {self.name}."
            
            items = ", ".join(todos)
            return f"You have {len(todos)} items on your list: {items}."
        except Exception as e:
            logger.error(f"Todo error: {e}")
            return f"I encountered an error reading your to-do list, {self.name}."

    def _clear_todo(self) -> str:
        if self.todo_file.exists():
            try:
                with open(self.todo_file, "w") as f:
                    json.dump([], f)
                return f"Your to-do list has been cleared, {self.name}."
            except Exception:
                return f"I couldn't clear your to-do list, {self.name}."
        return f"Your to-do list is already empty, {self.name}."

    def _take_note(self, text: str) -> str:
        for trigger in ["take a note", "write down"]:
            if trigger in text:
                note = text.split(trigger, 1)[-1].strip()
                if note.startswith("that "):
                    note = note[5:]
                if note.startswith(":"):
                    note = note[1:].strip()
                break
        else:
            note = text
            
        if not note:
            return f"What would you like me to write down, {self.name}?"

        try:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(self.notes_file, "a") as f:
                f.write(f"[{timestamp}] {note}\n")
            return f"Note saved, {self.name}."
        except Exception as e:
            logger.error(f"Note taking error: {e}")
            return f"I was unable to save your note, {self.name}."

    def _read_notes(self) -> str:
        if not self.notes_file.exists():
            return f"You don't have any notes saved yet, {self.name}."
        try:
            with open(self.notes_file, "r") as f:
                lines = f.readlines()
            if not lines:
                return f"You don't have any notes saved yet, {self.name}."
            
            recent = lines[-3:]
            notes_str = " ... ".join([line.split("]", 1)[-1].strip() for line in recent])
            count = len(lines)
            if count <= 3:
                return f"Here are your notes: {notes_str}."
            else:
                return f"You have {count} notes. Your most recent ones are: {notes_str}."
        except Exception as e:
            logger.error(f"Read notes error: {e}")
            return f"I am unable to read your notes at the moment, {self.name}."

    def _set_alarm_timer(self, text: str) -> str:
        """Parse alarm/timer intent and duration/time."""
        if not self.alarm_manager:
            return f"The alarm system is currently offline, {self.name}."

        # 1. Check for Timer (e.g., "set a timer for 10 minutes")
        timer_match = re.search(r"timer for (\d+)\s*(second|minute|hour)s?", text)
        if timer_match:
            amount = int(timer_match.group(1))
            unit = timer_match.group(2)
            
            seconds = amount
            if "minute" in unit: seconds *= 60
            elif "hour" in unit: seconds *= 3600
            
            self.alarm_manager.add_timer(seconds)
            from utils import format_duration
            return f"Timer started for {format_duration(seconds)}, {self.name}."

        # 2. Check for Alarm (e.g., "set an alarm for 7:30 am")
        alarm_match = re.search(r"alarm for (\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", text)
        if alarm_match:
            time_str = alarm_match.group(1).upper().strip()
            try:
                # Parse the time string
                now = datetime.datetime.now()
                if ":" in time_str:
                    target_time = datetime.datetime.strptime(time_str, "%I:%M %p" if "M" in time_str else "%H:%M").time()
                else:
                    # Handle "7 am" or "19"
                    target_time = datetime.datetime.strptime(time_str, "%I %p" if "M" in time_str else "%H").time()
                
                alarm_dt = datetime.datetime.combine(now.date(), target_time)
                
                # If time is in the past, assume tomorrow
                if alarm_dt <= now:
                    alarm_dt += datetime.timedelta(days=1)
                
                self.alarm_manager.add_alarm(alarm_dt)
                return f"Alarm set for {alarm_dt.strftime('%I:%M %p')}, {self.name}."
            except ValueError:
                return f"I couldn't understand the time format '{time_str}', {self.name}. Please use '7:30 AM' or '18:00'."

        return f"I'm not sure if you want an alarm or a timer, {self.name}."

    def _list_alarms(self) -> str:
        if not self.alarm_manager:
            return "Alarm system offline."
        return self.alarm_manager.get_status_summary()

    def _clear_alarms(self) -> str:
        if not self.alarm_manager:
            return "Alarm system offline."
        self.alarm_manager.clear_all()
        return f"All active alarms and timers have been canceled, {self.name}."

    # ─── Utility ──────────────────────────────────────────────────────────────

    @staticmethod
    def _match(text: str, keywords: list) -> bool:
        """Check if any keyword/phrase is in the text."""
        return any(kw in text for kw in keywords)

    def is_exit_command(self, text: str) -> bool:
        """Check if user said something to quit the assistant."""
        exits = ["goodbye", "bye", "exit", "quit", "shut yourself down", "sleep mode", "goodbye nova", "close yourself", "close nova", "turn off", "terminate"]
        return any(w in text.lower() for w in exits)
