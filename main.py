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

import sys
import time
import threading
import logging
import signal
import argparse
import winsound
from pathlib import Path

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:
    pass


# ─── Local Modules ────────────────────────────────────────────────────────────
from utils import load_config, get_greeting, log_conversation, sanitize_text, setup_logging
from voice_engine import VoiceEngine
from command_handler import CommandHandler
from ai_brain import AIBrain
from gui import NovaGUI
from alarm_manager import AlarmManager

# ─── Logging Setup ────────────────────────────────────────────────────────────
setup_logging("INFO")
logger = logging.getLogger(__name__)

# ─── ASCII Banner ─────────────────────────────────────────────────────────────
BANNER = r"""
     _  ___  ______  _   _ ___ ____
    | |/ _ \|  _ \ \| | | |_ _/ ___|
    | | |_| | |_) | \ | | || |\___ \
 _  | |  _  |  _ <|\ \/ / | | ___) |
| |_| | | | | | \ \ \__/ |___|____/
 \___/|_| |_|_|  \_\

   Just A Rather Versatile Intelligent Organization
   -----------------------------------------------
   Version 2.0  |  AI Voice Assistant
"""


class Nova:
    """
    Main controller class for the Nova assistant.
    Manages the interaction loop, coordinates modules, and handles
    the threading model between GUI and voice listener.
    """

    def __init__(self, config: dict, gui: NovaGUI | None = None, text_mode: bool = False):
        self.config = config
        self.gui = gui
        self.text_mode = text_mode
        self.running = True
        self.wake_word = config.get("wake_word", "nova")
        self.name = config.get("user_name", "Sir")
        self.log_enabled = config.get("log_conversations", True)

        # Initialize core modules
        logger.info("Initializing Nova modules...")
        self.alarm_manager = config.get("alarm_manager") # Passed from main
        self.voice = VoiceEngine(config)
        self.brain = AIBrain(config)
        self.commands = CommandHandler(config, alarm_manager=self.alarm_manager)

    # ──────────────────────────────────────────────────────────────────────────
    # Startup
    # ──────────────────────────────────────────────────────────────────────────

    def start(self):
        """Boot sequence — greeting and main interaction loop."""
        print(BANNER)

        if self.config.get("greeting_enabled", True):
            greeting = get_greeting(self.config)
            self._respond(greeting, is_greeting=True)

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
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
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

        # ── Exit Check ────────────────────────────────────────────────────
        if self.commands.is_exit_command(user_text):
            farewell = f"Goodbye, {self.name}. Nova, signing off."
            self._respond(farewell)
            self.shutdown()
            return

        # ── Route to Command Handler ──────────────────────────────────────
        response, handled = self.commands.handle(user_text)

        if not handled or not response:
            # ── Route to AI Brain ─────────────────────────────────────────
            self._set_status("Processing")
            response = self.brain.ask(user_text)

        # Special case: memory clear
        if "clear memory" in user_text.lower() or "forget everything" in user_text.lower():
            self.brain.clear_memory()

        self._respond(response)

    # ──────────────────────────────────────────────────────────────────────────
    # Response Delivery
    # ──────────────────────────────────────────────────────────────────────────

    def _respond(self, text: str, is_greeting: bool = False):
        """
        Deliver a response via TTS and log it.

        Args:
            text (str): Response text.
            is_greeting (bool): If True, display as system message in GUI.
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
                log_conversation("[user voice]", clean_text)
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
        for _ in range(3):
            winsound.Beep(1000, 400)
            winsound.Beep(1500, 400)
            
        # 2. Alert the user
        msg = f"Excuse me, {self.name}. Your {trigger_type} for {label} is going off now."
        self._respond(msg)
        
        # 3. Update status
        self._set_status("Alert")

    # ──────────────────────────────────────────────────────────────────────────
    # Shutdown
    # ──────────────────────────────────────────────────────────────────────────

    def shutdown(self):
        """Gracefully stop all modules and exit."""
        logger.info("Nova shutdown initiated.")
        self.running = False

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

    gui = None
    text_mode = args.text

    if not args.no_gui:
        # ── GUI Mode ──────────────────────────────────────────────────────
        # Initialize Alarm Manager
        alarm_manager = AlarmManager()
        config["alarm_manager"] = alarm_manager

        app = QApplication(sys.argv)
        gui = NovaGUI(config)

        nova = Nova(config, gui=gui, text_mode=text_mode)
        alarm_manager.set_callback(nova.on_alarm_trigger)
        alarm_manager.start()

        # Connect GUI submit signal safely to a new threaded execution of handle_input
        gui.sig_text_submit.connect(
            lambda text: threading.Thread(target=nova._handle_input, args=(text,), daemon=True).start()
        )
        
        # Shutdown hook
        gui.sig_shutdown.connect(app.quit)

        # Run Nova in a background thread so PyQt GUI runs on main thread
        bot_thread = threading.Thread(target=nova.start, daemon=True)
        bot_thread.start()

        gui.show()
        sys.exit(app.exec())

    else:
        # ── Terminal Mode ─────────────────────────────────────────────────
        # Initialize Alarm Manager
        alarm_manager = AlarmManager()
        config["alarm_manager"] = alarm_manager

        nova = Nova(config, gui=None, text_mode=text_mode)
        alarm_manager.set_callback(nova.on_alarm_trigger)
        alarm_manager.start()

        # Graceful Ctrl+C
        signal.signal(signal.SIGINT, lambda *_: nova.shutdown())
        nova.start()


if __name__ == "__main__":
    main()