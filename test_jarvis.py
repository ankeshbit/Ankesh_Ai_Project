"""
test_jarvis.py
--------------
Quick test suite to validate core Jarvis modules without needing
a microphone or Groq key. Run with:

    python test_jarvis.py
"""

import unittest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from utils import load_config, get_greeting, sanitize_text, format_duration, _default_config
from command_handler import CommandHandler
from ai_brain import AIBrain


# ─── Config Tests ───────────────────────────────────────────────────────────

class TestConfig(unittest.TestCase):

    def test_default_config_has_required_keys(self):
        cfg = _default_config()
        required = ["assistant_name", "user_name", "wake_word", "voice_rate", "music_folder"]
        for key in required:
            self.assertIn(key, cfg, f"Missing key: {key}")

    def test_load_config_returns_dict(self):
        cfg = load_config()
        self.assertIsInstance(cfg, dict)
        self.assertIn("assistant_name", cfg)


# ─── Greeting Tests ─────────────────────────────────────────────────────────

class TestGreeting(unittest.TestCase):

    def setUp(self):
        self.config = _default_config()

    def test_greeting_contains_user_name(self):
        self.config["user_name"] = "TestUser"
        greeting = get_greeting(self.config)
        self.assertIn("TestUser", greeting)

    def test_greeting_contains_assistant_name(self):
        self.config["assistant_name"] = "TestBot"
        greeting = get_greeting(self.config)
        self.assertIn("TestBot", greeting)


# ─── Utils Tests ────────────────────────────────────────────────────────────

class TestUtils(unittest.TestCase):

    def test_sanitize_removes_markdown(self):
        self.assertEqual(sanitize_text("**bold** and _italic_"), "bold and italic")

    def test_format_duration_seconds(self):
        self.assertEqual(format_duration(45), "45s")

    def test_format_duration_minutes(self):
        self.assertEqual(format_duration(90), "1m 30s")

    def test_format_duration_hours(self):
        self.assertEqual(format_duration(3661), "1h 1m 1s")


# ─── Command Handler Tests ──────────────────────────────────────────────────

class TestCommandHandler(unittest.TestCase):

    def setUp(self):
        self.config = _default_config()
        self.handler = CommandHandler(self.config)

    def test_time_command(self):
        response, handled = self.handler.handle("what time is it")
        self.assertTrue(handled)
        self.assertIn("time", response.lower())

    def test_date_command(self):
        response, handled = self.handler.handle("what is today's date")
        self.assertTrue(handled)
        self.assertIn(self.config["user_name"], response)

    def test_google_search(self):
        response, handled = self.handler.handle("search for Python programming")
        self.assertTrue(handled)
        self.assertIn("search", response.lower())

    def test_unknown_command_not_handled(self):
        response, handled = self.handler.handle("explain quantum entanglement please")
        self.assertFalse(handled)

    def test_exit_detection(self):
        self.assertTrue(self.handler.is_exit_command("goodbye jarvis"))
        self.assertTrue(self.handler.is_exit_command("bye"))
        self.assertFalse(self.handler.is_exit_command("what time is it"))


# ─── AI Brain Tests (Fallback) ──────────────────────────────────────────────

class TestAIBrain(unittest.TestCase):

    def setUp(self):
        # Force offline/fallback mode for tests
        config = _default_config()
        config["use_groq"] = False
        self.brain = AIBrain(config)

    def test_ohms_law_response(self):
        response = self.brain.ask("what is ohm's law")
        self.assertIn("V = I", response)

    def test_power_formula_response(self):
        response = self.brain.ask("what is the power formula in watts")
        self.assertIn("P =", response)

    def test_greeting_response(self):
        response = self.brain.ask("hello")
        self.assertGreater(len(response), 5)

    def test_math_calculation(self):
        response = self.brain.ask("calculate 25 + 75")
        self.assertIn("100", response)

    def test_memory_adds_entries(self):
        self.brain.ask("Hello there")
        self.brain.ask("What is ohm's law")
        self.assertEqual(len(self.brain.memory), 4)  # 2 user + 2 bot

    def test_clear_memory(self):
        self.brain.ask("test")
        self.brain.clear_memory()
        self.assertEqual(len(self.brain.memory), 0)


# ─── Run Tests ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  JARVIS — Test Suite")
    print("=" * 55)
    unittest.main(verbosity=2)
