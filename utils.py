"""
utils.py
--------
Utility functions for Jarvis:
- Config loading/saving
- Conversation logging
- User preferences management
- Greeting generation
- Time-based salutation
"""

import json
import os
import datetime
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config.json"
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)


# ──────────────────────────────────────────────────────────────────────────────
# Config Management
# ──────────────────────────────────────────────────────────────────────────────

def load_config(path: Path = CONFIG_PATH) -> dict:
    """
    Load the Jarvis configuration from config.json.

    Returns:
        dict: Parsed configuration dictionary.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
        logger.info(f"Configuration loaded from {path}")
        return config
    except FileNotFoundError:
        logger.error(f"config.json not found at {path}. Using defaults.")
        return _default_config()
    except json.JSONDecodeError as e:
        logger.error(f"Config parse error: {e}. Using defaults.")
        return _default_config()


def save_config(config: dict, path: Path = CONFIG_PATH):
    """
    Persist changes to config.json.

    Args:
        config (dict): Configuration to save.
        path (Path): File path to write to.
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)
    logger.info("Configuration saved.")


def _default_config() -> dict:
    """Minimal default config if config.json is missing."""
    return {
        "assistant_name": "Jarvis",
        "user_name": "Sir",
        "wake_word": "jarvis",
        "voice_rate": 165,
        "voice_volume": 1.0,
        "voice_gender": "male",
        "groq_api_key": "",
        "groq_model": "llama-3.1-8b-instant",
        "use_groq": False,
        "music_folder": str(Path.home() / "Music"),
        "log_conversations": True,
        "max_memory_turns": 10,
        "greeting_enabled": True,
        "preferences": {"language": "en-US"},
    }


def update_preference(key: str, value, config: dict):
    """
    Update a top-level or nested preference and save.

    Args:
        key (str): Config key (supports dot notation e.g. 'preferences.theme').
        value: New value.
        config (dict): Current config dict (modified in place).
    """
    parts = key.split(".")
    target = config
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value
    save_config(config)
    logger.info(f"Preference updated: {key} = {value}")


# ──────────────────────────────────────────────────────────────────────────────
# Greeting Logic
# ──────────────────────────────────────────────────────────────────────────────

def get_greeting(config: dict) -> str:
    """
    Generate a time-appropriate greeting for the user.

    Returns:
        str: Personalized greeting string.
    """
    hour = datetime.datetime.now().hour
    name = config.get("user_name", "Sir")
    assistant = config.get("assistant_name", "Jarvis")

    if 5 <= hour < 12:
        salutation = "Good morning"
    elif 12 <= hour < 17:
        salutation = "Good afternoon"
    elif 17 <= hour < 21:
        salutation = "Good evening"
    else:
        salutation = "Good evening"

    return (
        f"{salutation}, {name}. I am {assistant}, your personal AI assistant. "
        "All systems are online and ready. How may I serve you today?"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Conversation Logging
# ──────────────────────────────────────────────────────────────────────────────

def log_conversation(user_text: str, assistant_text: str):
    """
    Append a conversation entry to today's log file.

    Args:
        user_text (str): What the user said.
        assistant_text (str): Jarvis's response.
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"conversation_{date_str}.log"

    entry = (
        f"[{timestamp}]\n"
        f"  USER    : {user_text}\n"
        f"  JARVIS  : {assistant_text}\n"
        f"{'─' * 60}\n"
    )

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(entry)

    logger.debug(f"Conversation logged to {log_file}")


def get_log_summary(days: int = 7) -> str:
    """
    Return a summary of recent conversation log files.

    Args:
        days (int): Number of recent days to check.

    Returns:
        str: Summary string listing log files and line counts.
    """
    logs = sorted(LOG_DIR.glob("conversation_*.log"), reverse=True)[:days]
    if not logs:
        return "No conversation logs found."
    lines = []
    for log in logs:
        count = sum(1 for line in open(log, encoding="utf-8") if line.startswith("["))
        lines.append(f"  {log.name}: {count} conversation(s)")
    return "Recent logs:\n" + "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Miscellaneous Helpers
# ──────────────────────────────────────────────────────────────────────────────

def sanitize_text(text: str) -> str:
    """Remove special characters from text for cleaner TTS output."""
    return re.sub(r"[*_`#]", "", text).strip()


def format_duration(seconds: int) -> str:
    """Convert seconds into a human-readable duration string."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    elif m:
        return f"{m}m {s}s"
    else:
        return f"{s}s"


def setup_logging(level: str = "INFO"):
    """
    Configure the root logger to write to both console and a log file.

    Args:
        level (str): Logging level — DEBUG, INFO, WARNING, ERROR.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    log_file = LOG_DIR / f"jarvis_{datetime.date.today()}.log"

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),                    # Console
            logging.FileHandler(log_file, encoding="utf-8"),  # File
        ],
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("comtypes").setLevel(logging.WARNING)
