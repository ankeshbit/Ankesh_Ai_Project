# Nova — Voice Assistant Platform

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.5+-green.svg)](https://www.riverbankcomputing.com/software/pyqt/)
[![Groq API](https://img.shields.io/badge/Groq-LLM-blue.svg)](https://console.groq.com/)

Nova is an open-source, feature-rich voice assistant for desktop with advanced AI reasoning capabilities. It combines speech recognition, text-to-speech synthesis, and large language models to deliver a comprehensive voice-first automation and interaction system.

## 📋 Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)

## ✨ Features

| Category | Capability | Details |
| **Voice Processing** | Speech Recognition | Google Web Speech API with multi-language support |
| | Text-to-Speech | Native OS integration (Windows PowerShell, macOS `say`, Linux `espeak`) |
| **Intelligence** | LLM Integration | Groq API (hosted) and Ollama (local) support |
| | RAG Memory | ChromaDB with sentence-transformers embeddings |
| | Fallback Engine | Rule-based responses for common queries |
| **Automation** | System Control | App launching, screenshot capture, volume control |
| | Web Access | Search integration and browser automation |
| **Monitoring** | Alarms & Timers | Background service with real-time tracking |
| | System Stats | CPU, RAM, and battery monitoring |
| **Interface** | Desktop UI | PyQt6 holographic HUD with waveform visualization |
| **Productivity** | Task Management | To-do lists with voice-based note-taking |
| | Conversation Logging | Timestamped conversation history and persistence |

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│              PyQt6 Desktop Interface                    │
│         (Waveform, Chat, Real-time Status)              │
└─────────────────────────────────────────────────────────┘
                          ↕
┌─────────────────────────────────────────────────────────┐
│            Voice Engine                                 │
│  • Speech Recognition (Google Web API)                  │
│  • Text-to-Speech (pyttsx3 + OS Native)                │
└─────────────────────────────────────────────────────────┘
                          ↕
┌─────────────────────────────────────────────────────────┐
│            Command Handler                              │
│  • Intent Parsing & Routing                             │
│  • Plugin System (Calendar, Email, Web Search)          │
└─────────────────────────────────────────────────────────┘
                    ↙         ↘
        ┌─────────────┐   ┌──────────────┐
        │ Groq LLM    │   │ Ollama Local │
        │ (Hosted)    │   │ Models       │
        └─────────────┘   └──────────────┘
                    ↘         ↙
        ┌─────────────────────────────────┐
        │   ChromaDB RAG Memory           │
        │   (Semantic Exchange Storage)   │
        └─────────────────────────────────┘
                    ↕
        ┌─────────────────────────────────┐
        │   Alarm Manager                 │
        │   (Background Tasks)            │
        └─────────────────────────────────┘
```

## 🛠️ Installation

### Prerequisites
- **Python 3.10+**
- **Git**
- **Microphone** (for voice input)
- **Speaker/Headphones** (for TTS output)

### Quick Start

```bash
# 1. Clone repository
git clone https://github.com/ankeshbit/Ankesh_Ai_Project.git
cd Ankesh_Ai_Project

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Copy and configure
cp config.sample.json config.json
# Edit config.json with your API keys and preferences
```

### Notes

RAG long-term memory is optional. To enable it: `pip install chromadb sentence-transformers`.

You can keep your API key out of `config.json`: set the `GROQ_API_KEY` environment variable or put it in a `.env` file next to `config.json`.

If you plan to use the Google Calendar and Gmail plugin, install the OAuth client libraries and Google API client support:

```bash
pip install google-api-python-client google-auth google-auth-oauthlib google-auth-httplib2
```

Then set `GOOGLE_CREDENTIALS_PATH` in `config.json` to your Google OAuth client secrets file. The first successful login creates a local `token.json` file in the project root.

### Running Nova

**Desktop GUI Mode (Full Interface):**
```bash
python main.py
```

**Terminal Mode (Voice + CLI):**
```bash
python main.py --no-gui
```

**Text Input Mode (No Microphone):**
```bash
python main.py --text
```

## ⚙️ Configuration

Create `config.json` from `config.sample.json`. All fields are optional with sensible defaults.

### Core Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `assistant_name` | string | `"Nova"` | Name used in responses |
| `user_name` | string | `"Sir"` | User's preferred title |
| `wake_word` | string | `"nova"` | Activation keyword for voice mode |

### Voice Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `voice_rate` | integer | `165` | TTS speech rate (WPM) |
| `voice_volume` | float | `1.0` | TTS volume (0.0 to 1.0) |
| `voice_gender` | string | `"male"` | TTS voice preference (male/female) |

### LLM Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `groq_api_key` | string | `""` | Groq API key for hosted models |
| `groq_model` | string | `"llama-3.1-8b-instant"` | Model ID to use |
| `use_groq` | boolean | `false` | Enable Groq backend |
| `use_ollama` | boolean | `false` | Enable local Ollama backend |
| `ollama_model` | string | `"llama3"` | Local model name |
| `ollama_timeout` | number | `60` | Seconds to wait for the local model |

### Advanced Settings

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_memory_turns` | integer | `10` | Conversation history depth |
| `log_conversations` | boolean | `true` | Save conversation logs |
| `greeting_enabled` | boolean | `true` | Play greeting on startup |
| `sound_effects` | boolean | `true` | Play system sound effects |
| `music_folder` | string | `"~/Music"` | Default music directory |
| `browser` | string | `"chrome"` | Browser for web search |
| `preferences.theme` | string | `"dark"` | UI theme (dark/light) |
| `preferences.language` | string | `"en-US"` | Speech recognition language |



## 📖 Usage Examples

### Voice Commands

```bash
# Wake the assistant
"Nova, ..."

# Questions
"Nova, what is Ohm's law?"
"Nova, who is Albert Einstein?"

# System control
"Nova, open VS Code"
"Nova, search for Python documentation"
"Nova, take a screenshot"

# Productivity
"Nova, set a timer for 5 minutes"
"Nova, add milk to my todo list"
"Nova, take a note: implement feature X"

# Audio
"Nova, play music"
"Nova, set volume to 50 percent"

# Power (always asks for confirmation first - say "yes" to proceed)
"Nova, restart the computer"

# Memory
"Nova, clear memory"
```

### Extending with Plugins

Create custom voice commands by adding plugins to the `plugins/` directory:

```python
# plugins/my_plugin.py
TRIGGERS = [
    {
        "name": "my_command",
        "description": "My custom command",
        "phrases": ["trigger phrase 1", "trigger phrase 2"]
    }
]

def execute(text, config, trigger, alarm_manager, handler):
    """Handle the voice command."""
    return "Response text here"
```

Existing plugins include:
- **Calendar & Email** (`plugins/calendar_email.py`) — Google Calendar and Gmail integration
- **Web Search** (`plugins/web_search.py`) — DuckDuckGo search with LLM summarization

## 🛠️ Tech Stack

### Core
- **Python 3.10+** - Programming language
- **PyQt6** - Desktop GUI framework
- **Groq API** - Hosted LLM inference
- **Ollama** - Local LLM execution (optional)

### Voice & Speech
- **SpeechRecognition** - STT via Google Web API
- **pyttsx3** - Cross-platform TTS
- **PyAudio** - Microphone input

### AI & Memory
- **ChromaDB** - Vector database for RAG
- **sentence-transformers** - Semantic embeddings

### System
- **psutil** - CPU, RAM, battery monitoring
- **requests** - HTTP client
- **duckduckgo-search** - Web search API

### Optional
- **google-api-python-client** - Google Calendar/Gmail
- **google-auth** - OAuth2 credentials

## 📁 Project Structure

```
nova-ai/
├── main.py                  # Entry point
├── ai_brain.py              # LLM integration with RAG memory
├── command_handler.py       # Intent parsing and routing
├── alarm_manager.py         # Background alarm/timer service
├── voice_engine.py          # STT/TTS orchestration
├── gui.py                   # PyQt6 desktop interface
├── utils.py                 # Utility functions
├── config.json              # Runtime configuration (create from sample)
├── config.sample.json       # Configuration template
├── requirements.txt         # Python dependencies
├── test_nova.py             # Unit/regression tests (python -m pytest)
├── README.md                # This file
├── LICENSE                  # MIT License
├── logs/                    # Application logs
├── plugins/                 # Voice command plugins
│   ├── calendar_email.py    # Google Calendar/Gmail integration
│   └── web_search.py        # DuckDuckGo search with LLM
└── .gitignore
```

## 🤝 Contributing

Contributions are welcome! Please follow these guidelines:

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Commit** changes (`git commit -m 'Add amazing feature'`)
4. **Push** to branch (`git push origin feature/amazing-feature`)
5. **Open** a Pull Request

### Development Setup

```bash
# Install dev dependencies
pip install -r requirements.txt
pip install pytest black flake8

# Run tests
python -m pytest

# Format code
black *.py
```

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/nova-ai/issues)
- **Documentation**: See [README.md](README.md) and code docstrings
- **Community**: Discussions and feedback welcome

---

**Nova** is actively maintained and designed for extensibility. Contributions, bug reports, and feature requests are highly appreciated.
