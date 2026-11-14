"""
test_nova.py
------------
Quick test suite to validate core Nova modules without needing
a microphone or Groq key. Run with:

    python test_nova.py    (or: python -m pytest)
"""

import unittest
import sys
import tempfile
import datetime
from pathlib import Path
from unittest import mock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from utils import load_config, get_greeting, sanitize_text, format_duration, _default_config
from command_handler import CommandHandler
from ai_brain import AIBrain
from alarm_manager import AlarmManager


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
        tmp = Path(tempfile.mkdtemp())
        self.handler.todo_file = tmp / "todo.json"
        self.handler.notes_file = tmp / "notes.txt"

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
        self.assertTrue(self.handler.is_exit_command("goodbye nova"))
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


# ─── Regression tests for fixed bugs ───────────────────────────────────────

class FakeAlarms:
    def __init__(self):
        self.timers, self.alarms = [], []
    def add_timer(self, seconds, label="Timer"):
        self.timers.append(seconds)
    def add_alarm(self, when, label="Alarm"):
        self.alarms.append(when)
    def clear_all(self):
        self.timers, self.alarms = [], []
    def get_status_summary(self):
        return "No active alarms or timers."


class TestCommandRegressions(unittest.TestCase):

    def setUp(self):
        self.alarms = FakeAlarms()
        self.h = CommandHandler(_default_config(), alarm_manager=self.alarms)
        tmp = Path(tempfile.mkdtemp())
        self.h.todo_file, self.h.notes_file = tmp / "todo.json", tmp / "notes.txt"
        self.h.plugin_triggers = []  # these tests target the built-in commands, not web-search answers
        # Nothing in these tests may open a browser, launch a process or power off the machine.
        for target in ("webbrowser.open", "subprocess.run", "subprocess.Popen", "os.system"):
            patcher = mock.patch(target, return_value=mock.Mock(returncode=0, stdout=""))
            self.addCleanup(patcher.stop)
            setattr(self, "m_" + target.split(".")[-1], patcher.start())

    def test_exit_requires_whole_utterance(self):
        for phrase in ("goodbye nova", "bye", "exit", "nova, quit", "Goodbye"):
            self.assertTrue(self.h.is_exit_command(phrase), phrase)
        for phrase in ("that is quite interesting", "turn off the lights", "exit strategy for startups", "maybe"):
            self.assertFalse(self.h.is_exit_command(phrase), phrase)

    def test_questions_do_not_trigger_power_actions(self):
        for phrase in ("how do i restart my router", "how many hours of sleep do i need", "what is a shutdown"):
            self.assertFalse(self.h.handle(phrase)[1], phrase)
        self.m_run.assert_not_called()
        self.m_system.assert_not_called()

    def test_power_requires_confirmation(self):
        reply, handled = self.h.handle("restart the computer")
        self.assertTrue(handled)
        self.assertIn("sure", reply.lower())
        self.m_run.assert_not_called()                      # nothing executed yet
        self.h.handle("no")
        self.m_run.assert_not_called()                      # cancelled
        self.h.handle("shutdown")
        self.h.handle("yes")
        self.m_run.assert_called_once()                     # executed only after "yes"

    def test_start_a_timer_is_a_timer_not_an_app(self):
        reply, handled = self.h.handle("start a timer for 5 minutes")
        self.assertTrue(handled)
        self.assertEqual(self.alarms.timers, [300])

    def test_timer_phrasings(self):
        cases = {"set a timer for 10 minutes": 600, "set a 5 minute timer": 300, "set a timer for 5 mins": 300,
                 "set a timer for 1 hour 30 minutes": 5400, "set a timer for half an hour": 1800,
                 "set a timer for 30 seconds": 30, "set a timer for an hour": 3600}
        for phrase, seconds in cases.items():
            self.alarms.clear_all()
            self.h.handle(phrase)
            self.assertEqual(self.alarms.timers, [seconds], phrase)

    def test_alarm_pm_is_not_parsed_as_am(self):
        for phrase, hour, minute in (("set an alarm for 7 p.m.", 19, 0), ("set an alarm at 7:30 am", 7, 30),
                                     ("set an alarm for 12 am", 0, 0), ("set an alarm for 18:45", 18, 45)):
            self.alarms.clear_all()
            self.h.handle(phrase)
            self.assertEqual((self.alarms.alarms[0].hour, self.alarms.alarms[0].minute), (hour, minute), phrase)
            self.assertGreater(self.alarms.alarms[0], datetime.datetime.now())

    def test_invalid_alarm_time_is_rejected(self):
        reply, _ = self.h.handle("set an alarm for 25:99")
        self.assertEqual(self.alarms.alarms, [])

    def test_alarm_questions_do_not_cancel_alarms(self):
        self.alarms.timers = [60]
        self.assertFalse(self.h.handle("how do i cancel an alarm on my phone")[1])
        self.assertEqual(self.alarms.timers, [60])               # not cleared
        self.assertFalse(self.h.handle("what is an alarm clock")[1])

    def test_whole_word_matching(self):
        self.assertFalse(self.h.handle("how long is my commute")[1])     # "mute"
        self.assertFalse(self.h.handle("set a stopwatch")[1])            # "watch"
        self.m_run.assert_not_called()
        self.m_open.assert_not_called()

    def test_youtube_queries(self):
        reply, _ = self.h.handle("play despacito on youtube")
        self.assertIn("despacito", self.m_open.call_args[0][0])
        self.h.handle("search youtube for cats")
        self.assertIn("youtube.com/results", self.m_open.call_args[0][0])

    def test_search_query_is_url_encoded(self):
        self.h.handle("search for c++ tutorial & more")
        self.assertIn("c%2B%2B", self.m_open.call_args[0][0])
        self.assertNotIn("&more", self.m_open.call_args[0][0])

    def test_open_prefers_longest_match(self):
        self.h.handle("open google chrome")
        self.m_open.assert_not_called()                      # did not open google.com
        self.h.handle("open youtube")
        self.assertIn("youtube.com", self.m_open.call_args[0][0])

    def test_todo_flow(self):
        self.h.handle("add address book to my todo list")
        self.h.handle("put milk on my to do list")
        reply, handled = self.h.handle("what's on my to do list")
        self.assertTrue(handled)
        self.assertIn("address book", reply)
        self.assertIn("milk", reply)
        self.h.handle("clear my to do list")
        self.assertIn("empty", self.h.handle("read my to do list")[0])

    def test_notes_and_unicode(self):
        self.h.handle("note this buy दूध")
        reply, _ = self.h.handle("read my notes")
        self.assertIn("buy दूध", reply)
        self.assertNotIn("note this", reply)

    def test_screenshot_phrasing(self):
        reply, handled = self.h.handle("take a screenshot")
        self.assertTrue(handled)

    def test_set_volume_percent(self):
        with mock.patch.object(self.h, "_volume", return_value="ok") as vol:
            self.h.handle("set volume to 50 percent")
            vol.assert_called_with("set", 50)
            self.h.handle("unmute")
            vol.assert_called_with("unmute")

    def test_clear_memory_phrases_share_one_source(self):
        for phrase in ("clear memory", "forget everything", "reset conversation"):
            self.assertTrue(self.h.is_clear_memory_command(phrase), phrase)

    def test_date_queries_are_not_swallowed(self):
        self.assertFalse(self.h.handle("what is the date of the battle of plassey")[1])

    def test_plugin_type_error_is_not_retried(self):
        calls = []
        def execute(text, config=None, trigger=None, alarm_manager=None, handler=None):
            calls.append(1)
            raise TypeError("bug inside plugin")
        self.h.plugin_triggers = [{"name": "p", "phrases": ["zzz"], "trigger": {}, "execute": execute, "module": None}]
        reply, handled = self.h.handle("zzz please")
        self.assertTrue(handled)
        self.assertEqual(len(calls), 1)                      # not re-run (would repeat side effects)

    def test_plugin_with_text_only_signature(self):
        self.h.plugin_triggers = [{"name": "p", "phrases": ["zzz"], "trigger": {}, "execute": lambda text: "pong", "module": None}]
        self.assertEqual(self.h.handle("zzz")[0], "pong")


class TestBrainRegressions(unittest.TestCase):

    def setUp(self):
        self.brain = AIBrain({**_default_config(), "use_groq": False}, enable_rag=False)

    def test_math_is_bounded(self):
        self.assertIsNone(self.brain._try_math("calculate 9^9^9^9"))      # used to hang forever
        self.assertIsNone(self.brain._try_math("what is 10 ** 1000"))
        self.assertIsNone(self.brain._try_math("calculate 1 / 0"))

    def test_math_needs_an_operator(self):
        self.assertIsNone(self.brain._try_math("what is the capital of france in 2020"))

    def test_math_words(self):
        self.assertIn("84", self.brain._try_math("what is 12 times 7"))
        self.assertIn("2.5", self.brain._try_math("what is 10 divided by 4"))

    def test_greeting_needs_whole_word(self):
        self.assertNotIn("Good to hear from you", self.brain._ask_fallback("tell me about philosophy"))
        self.assertIn("Good to hear from you", self.brain._ask_fallback("hi"))

    def test_zero_memory_turns_still_keeps_user_message(self):
        brain = AIBrain({**_default_config(), "max_memory_turns": 0}, enable_rag=False)
        self.assertGreaterEqual(brain.memory.maxlen, 2)

    def test_complete_without_llm_returns_none_and_keeps_memory(self):
        self.assertIsNone(self.brain.complete("summarize"))
        self.assertEqual(len(self.brain.memory), 0)


class TestUtilsRegressions(unittest.TestCase):

    def test_sanitize_keeps_identifiers(self):
        self.assertEqual(sanitize_text("saved nova_screenshot_1.png in C#"), "saved nova_screenshot_1.png in C#")

    def test_load_config_fills_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            path.write_text('{"user_name": "Ankesh"}', encoding="utf-8")
            cfg = load_config(path)
        self.assertEqual(cfg["user_name"], "Ankesh")
        self.assertEqual(cfg["wake_word"], "nova")
        self.assertIn("language", cfg["preferences"])


class TestAlarmManager(unittest.TestCase):

    def test_bad_entry_does_not_wipe_valid_alarms(self):
        import json
        path = Path(tempfile.mkdtemp()) / "a.json"
        future = (datetime.datetime.now() + datetime.timedelta(hours=1)).isoformat()
        path.write_text(json.dumps([{"type": "timer", "time": future, "label": "ok"}, {"junk": 1}]))
        self.assertEqual(len(AlarmManager(path).alarms), 1)

    def test_callback_error_does_not_kill_monitor(self):
        mgr = AlarmManager(Path(tempfile.mkdtemp()) / "a.json")
        fired = []
        def cb(kind, label):
            fired.append(label)
            raise RuntimeError("boom")
        mgr.set_callback(cb)
        mgr.add_timer(0, "first")
        mgr.add_timer(0, "second")
        for item in mgr._collect_expired():
            mgr._fire(item)                                  # must swallow the exception
        self.assertEqual(sorted(fired), ["first", "second"])


try:
    from voice_engine import VoiceEngine
except Exception:                                             # SpeechRecognition not installed
    VoiceEngine = None


@unittest.skipIf(VoiceEngine is None, "SpeechRecognition not installed")
class TestVoiceEngine(unittest.TestCase):

    def test_wake_word_is_whole_word(self):
        self.assertTrue(VoiceEngine.contains_wake_word("hey nova what time is it", "nova"))
        self.assertFalse(VoiceEngine.contains_wake_word("what an innovation", "nova"))
        self.assertFalse(VoiceEngine.contains_wake_word(None, "nova"))

    def test_tts_text_never_goes_through_a_shell(self):
        engine = VoiceEngine.__new__(VoiceEngine)
        engine.config = {}
        evil = "hi $(touch /tmp/x); `id` & \"q\" %PATH%"
        argv, kwargs = engine._build_tts_command(evil)
        self.assertNotIn(evil, " ".join(argv))
        self.assertTrue(evil == kwargs.get("input") or evil == kwargs.get("env", {}).get("NOVA_TTS_TEXT"))


# ─── Run Tests ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  Nova — Test Suite")
    print("=" * 55)
    unittest.main(verbosity=2)
