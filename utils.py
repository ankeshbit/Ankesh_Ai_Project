"""
utils.py
--------
Utility functions for Nova:
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
    Load the Nova configuration from config.json.

    Missing keys are filled in from the built-in defaults, so every field in
    config.json is optional. A ``GROQ_API_KEY`` environment variable (or a
    ``.env`` file next to config.json, if python-dotenv is installed) is used
    when ``groq_api_key`` is empty or still the sample placeholder.

    Returns:
        dict: Parsed configuration dictionary.
    """
    config = _default_config()
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            raise ValueError("config.json must contain a JSON object")
        prefs = {**config.get("preferences", {}), **(loaded.get("preferences") or {})}
        config.update(loaded)
        config["preferences"] = prefs
        logger.info(f"Configuration loaded from {path}")
    except FileNotFoundError:
        logger.error(f"config.json not found at {path}. Using defaults.")
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Config parse error: {e}. Using defaults.")

    _apply_env_overrides(config, Path(path).parent)
    return config


_PLACEHOLDER_KEYS = {"", "YOUR_GROQ_API_KEY_HERE", "YOUR_OPENAI_API_KEY_HERE"}


def _apply_env_overrides(config: dict, env_dir: Path):
    """Pull the Groq API key from .env / the environment when config has none."""
    try:
        from dotenv import load_dotenv
        load_dotenv(env_dir / ".env")
    except ImportError:
        pass

    env_key = os.environ.get("GROQ_API_KEY", "").strip()
    if env_key and str(config.get("groq_api_key", "")).strip() in _PLACEHOLDER_KEYS:
        config["groq_api_key"] = env_key  # use_groq is still controlled by config.json


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
        "assistant_name": "Nova",
        "user_name": "Sir",
        "wake_word": "nova",
        "voice_rate": 165,
        "voice_volume": 1.0,
        "voice_gender": "male",
        "groq_api_key": "",
        "groq_model": "llama-3.1-8b-instant",
        "use_groq": False,
        "use_ollama": False,
        "ollama_model": "llama3",
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
    assistant = config.get("assistant_name", "Nova")

    if 5 <= hour < 12:
        salutation = "Good morning"
    elif 12 <= hour < 17:
        salutation = "Good afternoon"
    elif 17 <= hour < 24:
        salutation = "Good evening"
    else:
        salutation = "Hello"  # small hours (00:00-04:59)

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
        assistant_text (str): Nova's response.
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"conversation_{date_str}.log"

    entry = (
        f"[{timestamp}]\n"
        f"  USER    : {user_text}\n"
        f"  NOVA    : {assistant_text}\n"
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
        with open(log, encoding="utf-8") as fh:
            count = sum(1 for line in fh if line.startswith("["))
        lines.append(f"  {log.name}: {count} conversation(s)")
    return "Recent logs:\n" + "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Miscellaneous Helpers
# ──────────────────────────────────────────────────────────────────────────────

def sanitize_text(text: str) -> str:
    """
    Strip Markdown decoration for cleaner TTS/GUI output.

    Only emphasis markers are removed: ``*``, backticks, leading ``#`` heading
    marks and ``_`` that is not inside a word. So ``nova_screenshot_1.png`` and
    ``C#`` are left intact.
    """
    text = re.sub(r"[*`]", "", text)
    text = re.sub(r"(?m)^\s*#+\s*", "", text)
    text = re.sub(r"(?<!\w)_+|_+(?!\w)", "", text)
    return text.strip()


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
    log_file = LOG_DIR / f"nova_{datetime.date.today()}.log"

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),                    # Console
            logging.FileHandler(log_file, encoding="utf-8"),  # File
        ],
        force=True,  # allow re-configuring (e.g. --debug after the import-time setup)
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("comtypes").setLevel(logging.WARNING)
