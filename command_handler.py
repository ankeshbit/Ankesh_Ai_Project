"""
command_handler.py
------------------
Parses user intent and routes commands to the correct action handler.
Covers: app launching, web search, time/date, music playback,
        system controls, and engineering mode triggers.

All keyword matching is whole-word/whole-phrase. (Plain substring matching made
"restart" match "start ", "stopwatch" match "watch", "commute" match "mute", and
"how do I restart my router" reboot the computer.)
"""

import os
import re
import sys
import json
import time
import inspect
import datetime
import functools
import importlib.util
import webbrowser
import subprocess
import random
import logging
import platform
from pathlib import Path
from urllib.parse import quote_plus, quote

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=512)
def _phrase_regex(phrase: str) -> "re.Pattern":
    """Compile a whole-phrase matcher: the phrase must not be glued to other word characters."""
    return re.compile(r"(?<!\w)" + re.escape(phrase.strip()) + r"(?!\w)")


class CommandHandler:
    """
    Detects and executes system-level and utility commands spoken by the user.
    Returns a (response_text, handled) tuple so main.py knows whether to
    also query the AI brain.
    """

    # ─── App Name → Executable Mapping ───────────────────────────────────────
    APP_MAP = {
        "google chrome": ["chrome", "google-chrome", "chromium-browser", "chromium"],
        "chrome":       ["chrome", "google-chrome", "chromium-browser", "chromium"],
        "firefox":      ["firefox"],
        "edge":         ["msedge", "microsoft-edge"],
        "microsoft edge": ["msedge", "microsoft-edge"],
        "brave":        ["brave", "brave-browser"],
        "notepad":      ["notepad", "gedit", "mousepad", "kate"],
        "vs code":      ["code"],
        "vscode":       ["code"],
        "visual studio code": ["code"],
        "calculator":   ["calc", "gnome-calculator", "kcalc"],
        "paint":        ["mspaint"],
        "command prompt": ["cmd"],
        "terminal":     ["cmd", "x-terminal-emulator", "gnome-terminal", "konsole", "xterm"],
        "word":         ["winword"],
        "excel":        ["excel"],
        "powerpoint":   ["powerpnt"],
        "spotify":      ["spotify"],
        "vlc":          ["vlc"],
        "file explorer": ["explorer", "nautilus", "dolphin", "thunar"],
        "task manager": ["taskmgr", "gnome-system-monitor"],
    }

    # macOS needs the application bundle name for `open -a`.
    MAC_APP_NAMES = {
        "google chrome": "Google Chrome", "chrome": "Google Chrome", "firefox": "Firefox",
        "brave": "Brave Browser", "vs code": "Visual Studio Code", "vscode": "Visual Studio Code",
        "visual studio code": "Visual Studio Code", "calculator": "Calculator", "terminal": "Terminal",
        "word": "Microsoft Word", "excel": "Microsoft Excel", "powerpoint": "Microsoft PowerPoint",
        "spotify": "Spotify", "vlc": "VLC", "file explorer": "Finder", "notepad": "TextEdit",
        "edge": "Microsoft Edge", "microsoft edge": "Microsoft Edge",
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

    CLEAR_MEMORY_PHRASES = ["clear memory", "forget everything", "reset conversation", "clear your memory"]

    EXIT_PHRASES = [
        "goodbye", "good bye", "bye", "bye bye", "exit", "quit", "terminate",
        "shut yourself down", "close yourself", "sleep mode", "turn yourself off", "turn off",
        "goodbye nova", "exit nova", "quit nova", "close nova", "terminate nova",
        "shut down nova", "turn off nova",
    ]

    CONFIRM_WINDOW_SECONDS = 45

    def __init__(self, config: dict, alarm_manager=None):
        self.config = config
        self.alarm_manager = alarm_manager
        self.brain = None  # set by main so plugins can reuse the live AIBrain
        self.name = config.get("user_name", "Sir")
        self.music_folder = config.get("music_folder", str(Path.home() / "Music"))
        self.todo_file = Path.home() / "nova_todo.json"
        self.notes_file = Path.home() / "nova_notes.txt"
        self.plugin_triggers = []
        self._pending = None  # (action, expires_at) awaiting spoken confirmation
        wake = re.escape(str(config.get("wake_word", "nova")).lower())
        self._wake_prefix = re.compile(rf"^\s*(?:(?:hey|ok|okay)\s+)?{wake}\b[\s,.!:;-]*")
        self._exit_regex = re.compile(
            r"^(?:please\s+)?(?:" + "|".join(re.escape(p) for p in sorted(self.EXIT_PHRASES, key=len, reverse=True))
            + r")(?:\s+(?:nova|now|please|for now))*\s*[.!]?$"
        )
        self._load_plugins()

    # ─── Dispatcher ───────────────────────────────────────────────────────────

    def handle(self, text: str) -> tuple[str, bool]:
        """
        Main dispatcher. Checks text against known command patterns.

        Args:
            text (str): User input (any case; a leading wake word is ignored).

        Returns:
            tuple[str, bool]: (Response text, True if handled by commands)
        """
        try:
            return self._dispatch(self._normalize(text))
        except Exception:
            # A bug in one command must never take down the voice/text loop.
            logger.exception("Command handler error")
            return f"Sorry {self.name}, something went wrong while running that command.", True

    def _normalize(self, text: str) -> str:
        text = (text or "").lower().strip()
        return self._wake_prefix.sub("", text).strip()

    def _dispatch(self, text: str) -> tuple[str, bool]:
        if not text:
            return "", False

        # ── Pending shutdown/restart/sleep confirmation ──────────────────────
        pending = self._resolve_pending(text)
        if pending is not None:
            return pending, True

        # "how do I mute a call?" / "how do I cancel an alarm?" are questions for the AI,
        # not commands to execute.
        is_question = self._QUESTION_START.match(text) is not None

        # ── Clear Memory (main.py clears the brain using is_clear_memory_command) ──
        if self.is_clear_memory_command(text):
            return f"Memory cleared, {self.name}. Starting fresh.", True

        # ── Time & Date ──────────────────────────────────────────────────────
        if self._is_time_query(text):
            return self._get_time(), True

        if self._is_date_query(text):
            return self._get_date(), True

        if self._is_day_query(text):
            return self._get_day(), True

        # ── Alarms & Timers (before "start ..." so "start a timer" works) ─────
        if self._match(text, ["timer", "timers", "alarm", "alarms", "wake me"]):
            response = self._handle_alarm_timer(text, is_question)
            if response:
                return response, True

        # ── Power: shutdown / restart / sleep (always confirmed first) ───────
        if re.search(r"^(?:please\s+)?(?:cancel|abort|stop)\b.*\b(?:shut ?down|restart|reboot)\b", text) and \
                not self._match(text, ["timer", "alarm"]):
            return self._abort_power(), True

        power = self._power_intent(text)
        if power:
            return self._request_power(power), True

        # ── Volume ───────────────────────────────────────────────────────────
        volume_response = None if is_question else self._handle_volume_command(text)
        if volume_response:
            return volume_response, True

        # ── Screenshot ───────────────────────────────────────────────────────
        if not is_question and (
                re.search(r"\b(?:take|capture|grab|snap)\b.*\b(?:screenshot|screen shot|screen)\b", text)
                or self._match(text, ["screenshot", "screen shot"])):
            return self._screenshot(), True

        # ── System Stats ─────────────────────────────────────────────────────
        if self._match(text, ["system status", "battery level", "battery status", "cpu usage", "memory usage", "ram usage", "system stats"]):
            return self._system_stats(), True

        # ── Weather ──────────────────────────────────────────────────────────
        if self._match(text, ["weather", "temperature outside", "is it raining"]):
            return self._weather(text), True

        # ── Open Applications / Websites ─────────────────────────────────────
        if not is_question and self._match(text, ["open", "launch", "start"]):
            target = self._find_open_target(text)
            if target:
                return self._open_target(target), True
            if re.match(r"^(?:please\s+)?(?:open|launch)\b", text):
                return f"I'm not sure which application you'd like to open, {self.name}. Could you be more specific?", True
            # Otherwise ("start the day", ...) fall through to the other handlers / AI brain.

        # ── YouTube ──────────────────────────────────────────────────────────
        if not is_question and (self._match(text, ["youtube"]) or re.match(r"^(?:please\s+)?watch\b", text)):
            return self._search_youtube(text), True

        # ── Google Search ────────────────────────────────────────────────────
        if not is_question and self._match(text, ["search", "google", "look up"]):
            return self._search_google(text), True

        # ── Music Playback ───────────────────────────────────────────────────
        if not is_question and self._match(text, ["play music", "play a song", "play some music", "shuffle music"]):
            return self._play_music(), True

        # ── Productivity ─────────────────────────────────────────────────────
        if re.search(r"\b(?:to[ -]?do|todo)\s+list\b", text):
            wants_clear = self._match(text, ["clear", "empty", "delete all"])
            wants_add = self._match(text, ["add", "put"])
            if wants_clear and not is_question:
                return self._clear_todo(), True
            if wants_add and not is_question:
                return self._add_todo(text), True
            if not (wants_clear or wants_add):
                return self._read_todo(), True  # "what's on my to-do list", "read my todo list"

        if not is_question and self._match(text, ["remind me to"]):
            return self._add_todo(text), True

        if not is_question and self._match(text, ["take a note", "make a note", "write down", "note this", "note down"]):
            return self._take_note(text), True

        if self._match(text, ["read my notes", "what are my notes", "what did i note", "show my notes"]):
            return self._read_notes(), True

        # ── Fun / Utils ──────────────────────────────────────────────────────
        if self._match(text, ["flip a coin", "toss a coin", "flip coin"]):
            return f"It landed on {random.choice(['Heads', 'Tails'])}, {self.name}.", True

        if self._match(text, ["roll a dice", "roll a die", "roll the dice", "roll dice"]):
            return f"You rolled a {random.randint(1, 6)}, {self.name}.", True

        # ── Plugins (last, so broad plugin phrases like "what is" can't shadow built-ins) ──
        plugin_response = self._handle_plugin_triggers(text)
        if plugin_response:
            return plugin_response, True

        return "", False  # Not handled — pass to AI brain

    # ─── Plugins ──────────────────────────────────────────────────────────────

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
                # Register before executing so decorators/dataclasses that look the module up work.
                sys.modules[module_name] = module
                try:
                    spec.loader.exec_module(module)
                except Exception:
                    sys.modules.pop(module_name, None)
                    raise

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

    def _call_plugin(self, plugin: dict, text: str):
        """
        Call a plugin's execute() with the keyword arguments it declares.

        Signature inspection (instead of try/except TypeError) means a genuine
        TypeError raised *inside* a plugin is never mistaken for a signature
        mismatch and re-run, which could repeat side effects such as sending an email.
        """
        execute = plugin["execute"]
        kwargs = {
            "text": text,
            "config": self.config,
            "trigger": plugin["trigger"],
            "alarm_manager": self.alarm_manager,
            "handler": self,
        }
        try:
            params = inspect.signature(execute).parameters
        except (TypeError, ValueError):
            params = None
        if params is not None and not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            kwargs = {k: v for k, v in kwargs.items() if k in params}
        return execute(**kwargs)

    def _handle_plugin_triggers(self, text: str) -> str:
        """Route recognized plugin phrases to their execute() handlers."""
        for plugin in self.plugin_triggers:
            if not self._match(text, plugin["phrases"]):
                continue

            try:
                result = self._call_plugin(plugin, text)
            except Exception:
                logger.exception("Plugin '%s' failed", plugin["name"])
                return f"Sorry {self.name}, the {plugin['name'].replace('_', ' ')} plugin ran into a problem."

            response_text = result[0] if isinstance(result, tuple) else result
            if response_text:
                return response_text

        return ""

    # ─── Intent helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _match(text: str, keywords: list) -> bool:
        """True if any keyword/phrase occurs in `text` as a whole word/phrase."""
        return any(_phrase_regex(kw).search(text) for kw in keywords if kw and kw.strip())

    def is_exit_command(self, text: str) -> bool:
        """
        True if the user asked Nova to quit.

        The whole utterance must be an exit phrase ("goodbye nova", "bye", "exit").
        Substring matching quit the assistant on "that's quite interesting",
        "turn off the lights" and "exit strategy".
        """
        return self._exit_regex.match(self._normalize(text)) is not None

    def is_clear_memory_command(self, text: str) -> bool:
        """True if the text asks to wipe conversation memory."""
        return self._match(self._normalize(text), self.CLEAR_MEMORY_PHRASES)

    @staticmethod
    def _is_time_query(text: str) -> bool:
        return re.search(
            r"\bwhat(?:'s| is)? the time\b|\bwhat time is it\b|\bwhat time (?:is it )?now\b|"
            r"\bcurrent time\b|\btell me the time\b|\bthe time now\b|^time$",
            text,
        ) is not None

    @staticmethod
    def _is_date_query(text: str) -> bool:
        return re.search(
            r"\b(?:today's|todays|current)\s+date\b|\bwhat(?:'s| is)? the date(?:\s+(?:today|now))?\s*$|"
            r"\bwhat date is (?:it|today)\b|\bwhat is the date today\b|^date$",
            text,
        ) is not None

    @staticmethod
    def _is_day_query(text: str) -> bool:
        return re.search(
            r"\bwhat day (?:is it|is today|of the week)(?:\s+today)?\s*$|\bwhat's the day\b|\bday today\b|"
            r"\bwhich day is it\b|^what day$",
            text,
        ) is not None

    # ─── Handler Methods ──────────────────────────────────────────────────────

    def _get_time(self) -> str:
        now = datetime.datetime.now()
        time_str = now.strftime("%I:%M %p").lstrip("0")
        return f"The current time is {time_str}, {self.name}."

    def _get_date(self) -> str:
        today = datetime.date.today()
        date_str = today.strftime("%B %d, %Y")
        return f"Today is {date_str}, {self.name}."

    def _get_day(self) -> str:
        day = datetime.datetime.now().strftime("%A")
        return f"Today is {day}, {self.name}."

    # ── Opening apps / sites ──────────────────────────────────────────────────

    def _find_open_target(self, text: str):
        """
        Find the site or app the user named. The longest matching name wins, so
        "open google chrome" launches Chrome (not google.com) while
        "open youtube in chrome" opens YouTube.
        """
        best = None
        for name, url in self.WEB_MAP.items():
            if self._match(text, [name]) and (best is None or len(name) > len(best[1])):
                best = ("site", name, url)
        for name, executables in self.APP_MAP.items():
            if self._match(text, [name]) and (best is None or len(name) > len(best[1])):
                best = ("app", name, executables)
        return best

    def _open_target(self, target) -> str:
        kind, name, payload = target
        if kind == "site":
            webbrowser.open(payload)
            logger.info(f"Opened website: {name}")
            return f"Opening {name.title()} for you, {self.name}."
        if self._launch_app(name, payload):
            logger.info(f"Opened application: {name}")
            return f"Opening {name.title()} for you, {self.name}."
        return f"I couldn't find {name.title()} on your system, {self.name}."

    def _launch_app(self, app_name: str, executables: list) -> bool:
        """Try each candidate executable until one launches. Returns True on success."""
        system = platform.system()
        if system == "Darwin":
            try:
                mac_name = self.MAC_APP_NAMES.get(app_name, app_name.title())
                if subprocess.run(["open", "-a", mac_name], capture_output=True).returncode == 0:
                    return True
            except OSError:
                pass

        for exe in executables:
            try:
                if system == "Windows":
                    # 'start' resolves registered app aliases (chrome, code, ...).
                    result = subprocess.run(["cmd", "/c", "start", "", exe], capture_output=True)
                    if result.returncode != 0:
                        continue
                else:
                    # Detach fully so the app can't grab the assistant's terminal/stdin.
                    subprocess.Popen(
                        [exe],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                return True
            except (OSError, subprocess.SubprocessError):
                continue
        return False

    # ── Search ────────────────────────────────────────────────────────────────

    def _search_google(self, text: str) -> str:
        """Extract the search query and open it in the browser."""
        match = re.search(r"\b(?:search for|search|google|look up)\b\s*(.*)$", text)
        query = match.group(1) if match else ""
        query = re.sub(r"^(?:google|the web|the internet|online|up)?\s*(?:for\s+)?", "", query).strip()
        if not query:
            return f"What would you like me to search for, {self.name}?"
        webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}")
        return f"Searching Google for '{query}', {self.name}."

    def _search_youtube(self, text: str) -> str:
        """Search YouTube for a video ("play X on youtube", "youtube X", "watch X")."""
        query = ""
        for pattern in (
            r"\bplay\s+(.+?)\s+on\s+youtube\b",
            r"\b(?:search\s+)?youtube\s*(?:for\s+)?(.+)$",
            r"\bwatch\s+(.+?)(?:\s+on\s+youtube)?$",
        ):
            match = re.search(pattern, text)
            if match and match.group(1).strip():
                query = match.group(1).strip()
                break
        if not query:
            webbrowser.open(self.WEB_MAP["youtube"])
            return f"Opening YouTube for you, {self.name}."
        webbrowser.open(f"https://www.youtube.com/results?search_query={quote_plus(query)}")
        return f"Looking up '{query}' on YouTube, {self.name}."

    # ── Music ─────────────────────────────────────────────────────────────────

    def _play_music(self) -> str:
        """Play a random music file from the configured music folder."""
        folder = Path(str(self.music_folder)).expanduser()  # "~/Music" must be expanded
        if not folder.is_dir():
            return f"I couldn't locate your music folder at '{self.music_folder}', {self.name}. Please update config.json."

        audio_exts = {".mp3", ".wav", ".flac", ".m4a", ".ogg"}
        songs = [f for f in folder.rglob("*") if f.is_file() and f.suffix.lower() in audio_exts]

        if not songs:
            return f"No music files found in '{self.music_folder}', {self.name}."

        song = random.choice(songs)
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(str(song))
            else:
                opener = "open" if system == "Darwin" else "xdg-open"
                subprocess.Popen(
                    [opener, str(song)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            logger.info(f"Playing: {song.name}")
            return f"Playing '{song.stem}' for you, {self.name}. Enjoy."
        except Exception as e:
            logger.error(f"Music playback error: {e}")
            return f"Unable to play music right now, {self.name}."

    # ── Power (shutdown / restart / sleep) ────────────────────────────────────

    _DEVICE = r"(?:computer|pc|laptop|system|machine)"
    _QUESTION_START = re.compile(r"^(?:how|what|why|when|where|who|which|can i|could i|should i|is it|does|do i)\b")

    def _power_intent(self, text: str):
        """Return 'shutdown' | 'restart' | 'sleep' for an imperative power command, else None."""
        if self._QUESTION_START.match(text):
            return None  # "how do I restart my computer?" is a question, not a command
        d = self._DEVICE
        if re.search(rf"^(?:please\s+)?(?:shut ?down|power off)(?:\s+now|\s+please)?$", text) or \
                re.search(rf"\b(?:shut ?down|power off|turn off)\b\s+(?:the\s+|my\s+)?{d}\b", text):
            return "shutdown"
        if re.search(r"^(?:please\s+)?(?:restart|reboot)(?:\s+now|\s+please)?$", text) or \
                re.search(rf"\b(?:restart|reboot)\b\s+(?:the\s+|my\s+)?{d}\b", text):
            return "restart"
        if re.search(r"^(?:please\s+)?(?:go to sleep|hibernate|suspend)(?:\s+now|\s+please)?$", text) or \
                re.search(rf"\b(?:sleep|hibernate|suspend)\b\s+(?:the\s+|my\s+)?{d}\b", text) or \
                re.search(rf"\b(?:put|send)\b\s+(?:the\s+|my\s+)?{d}\b\s+to\s+sleep\b", text):
            return "sleep"
        return None

    _POWER_LABELS = {"shutdown": "shut down", "restart": "restart", "sleep": "put the system to sleep"}

    def _request_power(self, action: str) -> str:
        """Ask for spoken confirmation: a misheard word must not power off the machine."""
        self._pending = (action, time.monotonic() + self.CONFIRM_WINDOW_SECONDS)
        return (f"Are you sure you want me to {self._POWER_LABELS[action]}, {self.name}? "
                "Say yes to confirm or no to cancel.")

    def _resolve_pending(self, text: str):
        """Handle the yes/no that follows a power request. Returns a reply, or None if not applicable."""
        if not self._pending:
            return None
        action, expires = self._pending
        if time.monotonic() > expires:
            self._pending = None
            return None
        if re.match(r"^(?:yes|yeah|yep|yup|sure|confirm|confirmed|affirmative|do it|go ahead|please do|proceed)\b", text):
            self._pending = None
            return self._execute_power(action)
        if re.match(r"^(?:no|nope|cancel|stop|abort|never ?mind|don't|do not)\b", text):
            self._pending = None
            return f"Understood, {self.name}. I won't {self._POWER_LABELS[action]}."
        self._pending = None  # Something else was said: drop the request, handle the new command.
        return None

    def _run_system_command(self, argv: list) -> bool:
        try:
            return subprocess.run(argv, capture_output=True, timeout=15).returncode == 0
        except (OSError, subprocess.SubprocessError) as e:
            logger.error(f"System command {argv[0]} failed: {e}")
            return False

    def _execute_power(self, action: str) -> str:
        system = platform.system()
        commands = {
            "Windows": {
                "shutdown": ["shutdown", "/s", "/t", "10"],
                "restart": ["shutdown", "/r", "/t", "10"],
                "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            },
            "Darwin": {
                "shutdown": ["osascript", "-e", 'tell app "System Events" to shut down'],
                "restart": ["osascript", "-e", 'tell app "System Events" to restart'],
                "sleep": ["pmset", "sleepnow"],
            },
            # systemctl works for a logged-in desktop user via polkit; `sudo ...` would
            # hang waiting for a password prompt the assistant can't answer.
            "Linux": {
                "shutdown": ["systemctl", "poweroff"],
                "restart": ["systemctl", "reboot"],
                "sleep": ["systemctl", "suspend"],
            },
        }.get(system)
        if not commands:
            return f"Power control isn't supported on {system}, {self.name}."

        if not self._run_system_command(commands[action]):
            return f"I wasn't able to {self._POWER_LABELS[action]}, {self.name}."

        if system == "Windows" and action != "sleep":
            verb = "Shutting down" if action == "shutdown" else "Restarting"
            return f"{verb} in 10 seconds, {self.name}. Say cancel shutdown to abort."
        return {"shutdown": f"Shutting down now, {self.name}. Goodbye.",
                "restart": f"Restarting now, {self.name}.",
                "sleep": f"Putting the system to sleep, {self.name}."}[action]

    def _abort_power(self) -> str:
        self._pending = None
        if platform.system() == "Windows" and self._run_system_command(["shutdown", "/a"]):
            return f"Shutdown aborted, {self.name}."
        return f"There is no pending shutdown to cancel, {self.name}."

    # ── Volume ────────────────────────────────────────────────────────────────

    def _handle_volume_command(self, text: str):
        """Parse a volume request. Returns a response, or None if the text isn't about volume."""
        level = re.search(r"\bvolume\b.*?\b(?:to|at)\s+(\d{1,3})\s*(?:%|percent)?", text) or \
            re.search(r"\b(?:set|change|make|put)\b.*?\b(\d{1,3})\s*(?:%|percent)\b.*\bvolume\b", text)
        if level:
            return self._volume("set", min(100, int(level.group(1))))
        if self._match(text, ["unmute"]):
            return self._volume("unmute")
        if self._match(text, ["mute"]):
            return self._volume("mute")
        if self._match(text, ["increase volume", "volume up", "louder", "raise the volume", "turn up the volume", "turn the volume up", "increase the volume"]):
            return self._volume("up")
        if self._match(text, ["decrease volume", "volume down", "quieter", "lower volume", "lower the volume", "turn down the volume", "turn the volume down", "decrease the volume"]):
            return self._volume("down")
        return None

    def _volume(self, direction: str, level: int | None = None) -> str:
        """
        Platform-aware volume control (direction: up, down, mute, unmute, set):
        - Windows: PyCAW (pycaw library)
        - macOS: osascript subprocess calls
        - Linux: pactl subprocess calls
        """
        system = platform.system()

        try:
            if system == "Windows":
                return self._volume_windows(direction, level)
            elif system == "Darwin":  # macOS
                return self._volume_macos(direction, level)
            elif system == "Linux":
                return self._volume_linux(direction, level)
            else:
                return f"Volume control not supported for {system}, {self.name}."
        except Exception as e:
            logger.error(f"Volume control error: {e}")
            return f"Volume control encountered an issue, {self.name}."

    def _volume_message(self, direction: str, level: int | None) -> str:
        return {
            "up": f"Volume increased, {self.name}.",
            "down": f"Volume decreased, {self.name}.",
            "mute": f"Volume muted, {self.name}.",
            "unmute": f"Volume unmuted, {self.name}.",
            "set": f"Volume set to {level} percent, {self.name}.",
        }[direction]

    def _volume_windows(self, direction: str, level: int | None = None) -> str:
        """Volume control for Windows using PyCAW."""
        try:
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

            speakers = AudioUtilities.GetSpeakers()
            if hasattr(speakers, "EndpointVolume"):  # newer pycaw returns a wrapper object
                volume = speakers.EndpointVolume
            else:
                interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = cast(interface, POINTER(IAudioEndpointVolume))
            current = volume.GetMasterVolumeLevelScalar()

            if direction == "up":
                volume.SetMasterVolumeLevelScalar(min(1.0, current + 0.1), None)
            elif direction == "down":
                volume.SetMasterVolumeLevelScalar(max(0.0, current - 0.1), None)
            elif direction == "set":
                volume.SetMasterVolumeLevelScalar(level / 100.0, None)
            elif direction == "mute":
                volume.SetMute(1, None)
            elif direction == "unmute":
                volume.SetMute(0, None)
            return self._volume_message(direction, level)
        except ImportError:
            logger.warning("pycaw not installed. Install with: pip install pycaw comtypes")
        return f"Volume control unavailable on Windows, {self.name}."

    def _volume_macos(self, direction: str, level: int | None = None) -> str:
        """Volume control for macOS using osascript."""
        def osa(script: str) -> str:
            return subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True).stdout.strip()

        try:
            if direction in ("up", "down"):
                current = int(osa("output volume of (get volume settings)"))
                level = max(0, min(100, current + (10 if direction == "up" else -10)))
                osa(f"set volume output volume {level}")
            elif direction == "set":
                osa(f"set volume output volume {int(level)}")
            else:
                osa(f"set volume output muted {'true' if direction == 'mute' else 'false'}")
            return self._volume_message(direction, level)
        except (subprocess.CalledProcessError, ValueError) as e:
            logger.error(f"macOS volume control error: {e}")
        return f"Volume control failed on macOS, {self.name}."

    def _volume_linux(self, direction: str, level: int | None = None) -> str:
        """Volume control for Linux using pactl (PulseAudio / PipeWire)."""
        try:
            sink = subprocess.run(
                ["pactl", "get-default-sink"], capture_output=True, text=True, check=True
            ).stdout.strip()

            def pactl(*args):
                subprocess.run(["pactl", *args], check=True, capture_output=True)

            if direction == "up":
                pactl("set-sink-volume", sink, "+10%")
            elif direction == "down":
                pactl("set-sink-volume", sink, "-10%")
            elif direction == "set":
                pactl("set-sink-volume", sink, f"{int(level)}%")
            else:
                pactl("set-sink-mute", sink, "1" if direction == "mute" else "0")
            return self._volume_message(direction, level)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error(f"Linux volume control error (pactl not found or failed): {e}")
            logger.info("Install PulseAudio tools: sudo apt-get install pulseaudio-utils")
        return f"Volume control failed on Linux, {self.name}."

    # ── System ────────────────────────────────────────────────────────────────

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

    def _weather(self, text: str = "") -> str:
        """Current weather; uses the city if the user named one ("weather in London")."""
        city = ""
        match = re.search(r"\bweather\b.*?\b(?:in|at|for)\s+([a-z][a-z .'-]*?)(?:\s+(?:today|tomorrow|now|right now|currently))?\s*$", text)
        if match:
            city = match.group(1).strip()
        try:
            import requests
            res = requests.get(f"https://wttr.in/{quote(city)}?format=%l:+%C+%t", timeout=5)
            if res.status_code == 200:
                data = res.text.strip().replace("+", "")
                return f"The current weather is {data}, {self.name}."
            return f"I couldn't fetch the weather data at this moment, {self.name}."
        except Exception as e:
            logger.error(f"Weather error: {e}")
            return f"My weather sensors are currently offline, {self.name}."

    # ─── Productivity ─────────────────────────────────────────────────────────

    def _load_todos(self) -> list:
        """Read the to-do list. A corrupt file is set aside rather than overwritten (data loss)."""
        if not self.todo_file.exists():
            return []
        try:
            with open(self.todo_file, "r", encoding="utf-8") as f:
                todos = json.load(f)
            return todos if isinstance(todos, list) else []
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Todo file unreadable ({e}); keeping a backup copy.")
            try:
                self.todo_file.replace(self.todo_file.with_suffix(".json.bak"))
            except OSError:
                pass
            return []

    def _save_todos(self, todos: list):
        with open(self.todo_file, "w", encoding="utf-8") as f:
            json.dump(todos, f, ensure_ascii=False)

    def _add_todo(self, text: str) -> str:
        if self._match(text, ["remind me to"]):
            item = re.split(r"\bremind me to\b", text, maxsplit=1)[-1].strip()
        else:
            # "add <item> to my to-do list" (whole words only: str.replace("add", "")
            # used to turn "add address book" into "ress book").
            match = re.search(
                r"\b(?:add|put)\s+(.+?)\s+(?:to|on|in|into)\s+(?:my\s+|the\s+)?(?:to[ -]?do|todo)\s+list\b", text)
            if match:
                item = match.group(1).strip()
            else:
                match = re.search(r"\b(?:add|put)\b\s+(?:to\s+)?(?:my\s+|the\s+)?(?:to[ -]?do|todo)\s+list\s*:?\s*(.*)$", text)
                item = match.group(1).strip() if match else ""

        if not item:
            return f"I didn't catch what you wanted me to add, {self.name}."

        try:
            todos = self._load_todos()
            todos.append(item)
            self._save_todos(todos)
            return f"I've added '{item}' to your to-do list, {self.name}."
        except Exception as e:
            logger.error(f"Todo error: {e}")
            return f"I was unable to save to your to-do list, {self.name}."

    def _read_todo(self) -> str:
        try:
            todos = self._load_todos()
            if not todos:
                return f"Your to-do list is currently empty, {self.name}."
            noun = "item" if len(todos) == 1 else "items"
            return f"You have {len(todos)} {noun} on your list: {', '.join(str(t) for t in todos)}."
        except Exception as e:
            logger.error(f"Todo error: {e}")
            return f"I encountered an error reading your to-do list, {self.name}."

    def _clear_todo(self) -> str:
        if self.todo_file.exists():
            try:
                self._save_todos([])
                return f"Your to-do list has been cleared, {self.name}."
            except Exception:
                return f"I couldn't clear your to-do list, {self.name}."
        return f"Your to-do list is already empty, {self.name}."

    def _take_note(self, text: str) -> str:
        match = re.search(r"\b(?:take a note|make a note|write down|note this|note down)\b[\s:,-]*(?:that\s+)?(.*)$", text)
        note = match.group(1).strip() if match else ""

        if not note:
            return f"What would you like me to write down, {self.name}?"

        try:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(self.notes_file, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {note}\n")
            return f"Note saved, {self.name}."
        except Exception as e:
            logger.error(f"Note taking error: {e}")
            return f"I was unable to save your note, {self.name}."

    def _read_notes(self) -> str:
        if not self.notes_file.exists():
            return f"You don't have any notes saved yet, {self.name}."
        try:
            with open(self.notes_file, "r", encoding="utf-8") as f:
                lines = [ln for ln in f.readlines() if ln.strip()]
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

    # ─── Alarms & Timers ──────────────────────────────────────────────────────

    _DURATION_UNITS = {"hour": 3600, "hr": 3600, "minute": 60, "min": 60, "second": 1, "sec": 1}

    @classmethod
    def _parse_duration(cls, text: str) -> int | None:
        """
        Total seconds for phrases like "5 minutes", "5 mins", "1 hour 30 minutes",
        "1.5 hours", "an hour", "half an hour". None if no duration is present.
        """
        total = 0.0
        if re.search(r"\bhalf an? hour\b|\bhalf hour\b", text):
            total += 1800
        for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?)\b", text):
            total += float(amount) * cls._DURATION_UNITS[unit.rstrip("s")]
        if total == 0:
            match = re.search(r"\ban?\s+(hour|minute|second)\b", text)
            if match:
                total = cls._DURATION_UNITS[match.group(1)]
        seconds = int(total)
        return seconds if 0 < seconds <= 365 * 86400 else None

    @staticmethod
    def _parse_clock(text: str):
        """
        Parse a clock time like "7:30 am", "7 p.m.", "19:00", "7 in the evening".
        Returns a datetime.time, or None.
        """
        normalized = re.sub(r"\b([ap])\.?\s?m\.?(?=\W|$)", r"\1m", text.lower())
        match = re.search(r"\b(?:for|at)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", normalized)
        if not match:
            return None
        hour, minute, meridiem = int(match.group(1)), int(match.group(2) or 0), match.group(3)
        if not meridiem:
            if re.search(r"\bin the (?:evening|afternoon)\b|\bat night\b", normalized):
                meridiem = "pm"
            elif re.search(r"\bin the morning\b", normalized):
                meridiem = "am"
        if not 0 <= minute <= 59:
            return None
        if meridiem:
            if not 1 <= hour <= 12:
                return None
            hour = hour % 12 + (12 if meridiem == "pm" else 0)
        elif not 0 <= hour <= 23:
            return None
        return datetime.time(hour, minute)

    _ALARM_LIST_PHRASES = [
        "list", "show", "what are my", "do i have", "how much time", "time left", "left", "remaining",
        "any alarms", "any timers", "my alarms", "my timers", "active alarms", "active timers", "running",
    ]

    def _handle_alarm_timer(self, text: str, is_question: bool = False) -> str:
        """
        Route alarm/timer requests. Returns "" when the text only *mentions* an
        alarm or timer ("what is an alarm clock?") so it can go to the AI brain.
        """
        if self._match(text, self._ALARM_LIST_PHRASES):
            return self._list_alarms()
        if is_question:
            return ""
        if self._match(text, ["cancel", "clear", "delete", "remove", "stop", "dismiss"]):
            return self._clear_alarms()
        if self._match(text, ["set", "start", "create", "make", "add", "wake me"]) or \
                self._parse_duration(text) or self._parse_clock(text):
            return self._set_alarm_timer(text)
        return ""

    def _set_alarm_timer(self, text: str) -> str:
        """Parse alarm/timer intent and duration/time. Returns "" if nothing could be parsed."""
        if not self.alarm_manager:
            return f"The alarm system is currently offline, {self.name}."
        from utils import format_duration

        wants_alarm = self._match(text, ["alarm", "alarms", "wake me"]) and not self._match(text, ["timer", "timers"])
        duration = self._parse_duration(text)

        # Timer ("set a timer for 10 minutes", "set a 5 minute timer")
        if duration and not wants_alarm:
            self.alarm_manager.add_timer(duration)
            return f"Timer started for {format_duration(duration)}, {self.name}."

        # Relative alarm ("wake me in 20 minutes", "alarm in an hour")
        if duration and wants_alarm:
            alarm_dt = datetime.datetime.now() + datetime.timedelta(seconds=duration)
            self.alarm_manager.add_alarm(alarm_dt)
            return f"Alarm set for {alarm_dt.strftime('%I:%M %p').lstrip('0')}, {self.name}."

        # Clock-time alarm ("set an alarm for 7:30 am", "alarm at 7 p.m.")
        target_time = self._parse_clock(text)
        if target_time:
            now = datetime.datetime.now()
            alarm_dt = datetime.datetime.combine(now.date(), target_time)
            tomorrow = self._match(text, ["tomorrow"])
            if tomorrow or alarm_dt <= now:
                alarm_dt += datetime.timedelta(days=1)  # time already passed today: next occurrence
            self.alarm_manager.add_alarm(alarm_dt)
            when = alarm_dt.strftime("%I:%M %p").lstrip("0")
            suffix = " tomorrow" if alarm_dt.date() > now.date() else ""
            return f"Alarm set for {when}{suffix}, {self.name}."

        if self._match(text, ["alarm", "timer"]) and self._match(text, ["set", "start", "create", "make"]):
            return (f"I couldn't work out the time, {self.name}. "
                    "Try 'set a timer for 5 minutes' or 'set an alarm for 7 30 am'.")
        return ""

    def _list_alarms(self) -> str:
        if not self.alarm_manager:
            return "Alarm system offline."
        return self.alarm_manager.get_status_summary()

    def _clear_alarms(self) -> str:
        if not self.alarm_manager:
            return "Alarm system offline."
        self.alarm_manager.clear_all()
        return f"All active alarms and timers have been canceled, {self.name}."
