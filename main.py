"""
main.py
-------
Nova AI Voice Assistant — Entry Point
Orchestrates the voice engine, AI brain, command handler, and GUI.

Run:
    python main.py              → Full GUI + Voice mode
    python main.py --no-gui     → Terminal-only mode
    python main.py --text       → Text input mode (no mic)

Wake Word: Say "Nova" to activate
Exit:      Say "Goodbye Nova" or close the window
"""

from __future__ import annotations

import sys
import time
import threading
import logging
import argparse

# winsound only exists on Windows; importing it unconditionally crashed Linux/macOS at startup.
try:
    import winsound
except ImportError:
    winsound = None

# PyQt6 is only needed for GUI mode. Importing it unconditionally made even
# `--no-gui` / `--text` fail on machines without it.
try:
    from PyQt6.QtWidgets import QApplication
    from gui import NovaGUI
except ImportError:
    QApplication = None
    NovaGUI = None


# ─── Local Modules ────────────────────────────────────────────────────────────
from utils import load_config, get_greeting, log_conversation, sanitize_text, setup_logging
from voice_engine import VoiceEngine
from command_handler import CommandHandler
from ai_brain import AIBrain
from alarm_manager import AlarmManager

# ─── Logging Setup ────────────────────────────────────────────────────────────
setup_logging("INFO")
logger = logging.getLogger(__name__)

# ─── ASCII Banner ─────────────────────────────────────────────────────────────
BANNER = r"""
    _   _  _____     _____
   | \ | |/ _ \ \   / / _ \
   |  \| | | | \ \ / / |_| |
   | |\  | |_| |\ V /|  _  |
   |_| \_|\___/  \_/ |_| |_|

   Your Personal AI Voice Assistant
   --------------------------------
   Version 2.0
"""


def _beep(frequency: int | None = None, duration_ms: int = 400):
    """Audible alert on any OS (system sound on Windows, terminal bell elsewhere)."""
    try:
        if winsound is not None:
            if frequency:
                winsound.Beep(frequency, duration_ms)
            else:
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
        else:
            sys.stdout.write("\a")
            sys.stdout.flush()
            time.sleep(duration_ms / 1000)
    except Exception:
        pass


class Nova:
    """
    Main controller class for the Nova assistant.
    Manages the interaction loop, coordinates modules, and handles
    the threading model between GUI and voice listener.
    """

    def __init__(self, config: dict, gui: NovaGUI | None = None, text_mode: bool = False,
                 alarm_manager: AlarmManager | None = None):
        self.config = config
        self.gui = gui
        self.text_mode = text_mode
        self.running = True
        self.wake_word = config.get("wake_word", "nova")
        self.name = config.get("user_name", "Sir")
        self.log_enabled = config.get("log_conversations", True)

        # Initialize core modules
        logger.info("Initializing Nova modules...")
        # Kept out of `config`: config gets written back to config.json
        # (update_preference/save_config) and an AlarmManager is not JSON serializable.
        self.alarm_manager = alarm_manager
        self.voice = VoiceEngine(config)
        self.brain = AIBrain(config)
        self.commands = CommandHandler(config, alarm_manager=self.alarm_manager)
        self.commands.brain = self.brain  # lets plugins reuse the live LLM backend

    # ──────────────────────────────────────────────────────────────────────────
    # Startup
    # ──────────────────────────────────────────────────────────────────────────

    def start(self):
        """Boot sequence — greeting and main interaction loop."""
        print(BANNER)

        if self.config.get("greeting_enabled", True):
            greeting = get_greeting(self.config)
            self._respond(greeting, is_greeting=True)

        if not self.text_mode and self.voice.microphone is None:
            logger.warning("No microphone available. Falling back to text input mode.")
            print("\n[!] No microphone detected - switching to text input mode.")
            self.text_mode = True

        if self.text_mode:
            self._text_loop()
        else:
            self._voice_loop()

    # ──────────────────────────────────────────────────────────────────────────
    # Main Voice Loop
    # ──────────────────────────────────────────────────────────────────────────

    def _voice_loop(self):
        """
        Primary loop:
        1. Listen for wake word
        2. Alert user
        3. Listen for command/query
        4. Process and respond
        5. Repeat
        """
        logger.info("Starting voice interaction loop.")
        retry_count = 0
        max_retries = 3

        while self.running:
            try:
                # ── Wait for Wake Word ─────────────────────────────────────
                self._set_status("Wake Word")
                logger.info(f"Waiting for wake word: '{self.wake_word}'")

                if not self.voice.listen_for_wake_word(self.wake_word, timeout=8):
                    retry_count = 0
                    continue  # Keep waiting

                # ── Wake Word Detected ─────────────────────────────────────
                _beep()
                self._set_status("Listening")
                self._speak_and_show("Yes? I'm listening.", is_system=True)
                retry_count = 0

                # ── Listen for Command ─────────────────────────────────────
                user_text = self._listen_with_retry(max_retries)
                if not user_text:
                    self._respond("I didn't catch that. Please say 'Nova' to try again.")
                    continue

                self._handle_input(user_text)

            except KeyboardInterrupt:
                logger.info("KeyboardInterrupt received. Shutting down.")
                self.shutdown()
                break
            except Exception as e:
                logger.error(f"Unexpected error in voice loop: {e}", exc_info=True)
                time.sleep(1)

    def _listen_with_retry(self, max_retries: int = 3) -> str | None:
        """
        Attempt to capture speech with retries on failure.

        Returns:
            str | None: Recognized text or None after exhausting retries.
        """
        for attempt in range(1, max_retries + 1):
            text = self.voice.listen(timeout=6, phrase_limit=12)
            if text:
                return text
            if attempt < max_retries:
                logger.warning(f"Listen attempt {attempt}/{max_retries} failed. Retrying...")
                self.voice.speak("Could you repeat that?")
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Text Loop (no microphone)
    # ──────────────────────────────────────────────────────────────────────────

    def _text_loop(self):
        """Fallback interactive terminal text loop for no-microphone environments."""
        logger.info("Running in text-input mode.")
        print(f"\n[TEXT MODE] Type your message and press Enter. Type 'exit' to quit.\n")

        while self.running:
            try:
                user_input = input(f"You : ").strip()
                if not user_input:
                    continue
                self._handle_input(user_input)
                if not self.running:
                    break
            except (KeyboardInterrupt, EOFError):
                self.shutdown()
                break

    # ──────────────────────────────────────────────────────────────────────────
    # Input Processing (shared by voice + text + GUI)
    # ──────────────────────────────────────────────────────────────────────────

    def _handle_input(self, user_text: str):
        """
        Process a user's input (text or transcribed speech).
        Routes to command handler first, then AI brain if not handled.

        Args:
            user_text (str): User's message.
        """
        logger.info(f"Processing input: '{user_text}'")
        self._set_status("Processing")

        # Show user message in GUI
        if self.gui:
            self.gui.add_message("user", user_text)

        try:
            # ── Exit Check ────────────────────────────────────────────────
            if self.commands.is_exit_command(user_text):
                farewell = f"Goodbye, {self.name}. Nova, signing off."
                self._respond(farewell, user_text=user_text)
                self.shutdown()
                return

            # ── Clear Memory (same phrase list the command handler uses) ──
            if self.commands.is_clear_memory_command(user_text):
                self.brain.clear_memory()

            # ── Route to Command Handler ──────────────────────────────────
            response, handled = self.commands.handle(user_text)

            if not handled or not response:
                # ── Route to AI Brain ─────────────────────────────────────
                self._set_status("Processing")
                response = self.brain.ask(user_text)
        except Exception:
            # One failing command/LLM call must not kill the interaction loop.
            logger.exception("Error while processing input")
            response = f"I'm sorry, {self.name}. Something went wrong while processing that."

        self._respond(response, user_text=user_text)

    # ──────────────────────────────────────────────────────────────────────────
    # Response Delivery
    # ──────────────────────────────────────────────────────────────────────────

    def _respond(self, text: str, is_greeting: bool = False, user_text: str | None = None):
        """
        Deliver a response via TTS and log it.

        Args:
            text (str): Response text.
            is_greeting (bool): If True, display as system message in GUI.
            user_text (str | None): What the user said, for the conversation log.
        """
        clean_text = sanitize_text(text)
        print(f"\n[Nova]: {clean_text}\n")

        if self.gui:
            role = "system" if is_greeting else "bot"
            self.gui.add_message(role, clean_text)

        self._set_status("Speaking")
        self.voice.speak(clean_text)
        self._set_status("Idle")

        # Log to file
        if self.log_enabled and not is_greeting:
            try:
                log_conversation(user_text or "[system]", clean_text)
            except Exception:
                pass

    def _speak_and_show(self, text: str, is_system: bool = False):
        """Speak text and optionally show in GUI as a system message."""
        clean = sanitize_text(text)
        if self.gui:
            self.gui.add_message("system" if is_system else "bot", clean)
        self.voice.speak(clean)

    def _set_status(self, status: str):
        """Update GUI status (safe no-op if no GUI)."""
        if self.gui:
            self.gui.set_status(status)

    def on_alarm_trigger(self, trigger_type: str, label: str):
        """Callback for AlarmManager when an alarm or timer goes off."""
        logger.info(f"ALARM TRIGGERED: {trigger_type} - {label}")

        # 1. Beep loudly
        self._set_status("Alert")
        for _ in range(3):
            _beep(1000, 400)
            _beep(1500, 400)

        # 2. Alert the user ("your timer for Timer" sounded broken for default labels)
        if str(label).strip().lower() in ("", trigger_type.lower()):
            msg = f"Excuse me, {self.name}. Your {trigger_type} is going off now."
        else:
            msg = f"Excuse me, {self.name}. Your {trigger_type} for {label} is going off now."
        self._respond(msg)

    # ──────────────────────────────────────────────────────────────────────────
    # Shutdown
    # ──────────────────────────────────────────────────────────────────────────

    def stop(self):
        """Mark Nova as stopped and stop background services (does not touch the GUI)."""
        self.running = False
        if self.alarm_manager:
            self.alarm_manager.stop()

    def shutdown(self):
        """Gracefully stop all modules and exit."""
        logger.info("Nova shutdown initiated.")
        self.stop()

        if self.gui:
            try:
                self.gui.sig_shutdown.emit()
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────────────────────
# Entry Point
# ──────────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Nova AI Voice Assistant")
    parser.add_argument("--no-gui", action="store_true", help="Run without GUI (terminal only)")
    parser.add_argument("--text", action="store_true", help="Use text input instead of microphone")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.debug:
        setup_logging("DEBUG")

    # Load configuration
    config = load_config()
    logger.info(f"Loaded config for assistant: '{config.get('assistant_name', 'Nova')}'")

    text_mode = args.text
    use_gui = not args.no_gui
    if use_gui and (QApplication is None or NovaGUI is None):
        logger.warning("PyQt6 is not installed; running without the GUI. Install it with: pip install PyQt6")
        print("[!] PyQt6 not found - running in terminal mode (use --no-gui to silence this).")
        use_gui = False

    alarm_manager = AlarmManager()

    if use_gui:
        # ── GUI Mode ──────────────────────────────────────────────────────
        app = QApplication(sys.argv)
        gui = NovaGUI(config)

        nova = Nova(config, gui=gui, text_mode=text_mode, alarm_manager=alarm_manager)
        alarm_manager.set_callback(nova.on_alarm_trigger)
        alarm_manager.start()

        # Connect GUI submit signal safely to a new threaded execution of handle_input
        gui.sig_text_submit.connect(
            lambda text: threading.Thread(target=nova._handle_input, args=(text,), daemon=True).start()
        )

        # Shutdown hooks. Closing the window must also stop Nova's own loop and the alarm
        # service (stop() does not emit sig_shutdown, so there is no signal recursion).
        gui.sig_shutdown.connect(nova.stop)
        gui.sig_shutdown.connect(app.quit)

        # Run Nova in a background thread so PyQt GUI runs on main thread
        bot_thread = threading.Thread(target=nova.start, daemon=True)
        bot_thread.start()

        gui.show()
        sys.exit(app.exec())

    else:
        # ── Terminal Mode ─────────────────────────────────────────────────
        nova = Nova(config, gui=None, text_mode=text_mode, alarm_manager=alarm_manager)
        alarm_manager.set_callback(nova.on_alarm_trigger)
        alarm_manager.start()

        # No custom SIGINT handler: replacing it with one that only sets a flag made Ctrl+C
        # do nothing while blocked in input() (text mode). The default KeyboardInterrupt
        # is handled below and inside the loops.
        try:
            nova.start()
        except KeyboardInterrupt:
            nova.shutdown()


if __name__ == "__main__":
    main()