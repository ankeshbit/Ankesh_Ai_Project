# JARVIS v2.0 - Elite AI Voice Assistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

JARVIS is a sophisticated, futuristic AI voice assistant inspired by the Marvel Cinematic Universe. It features a dual-interface system (Desktop HUD and Modern Web Dashboard), natural language processing via Groq/Ollama, and a wide array of system automation capabilities.

![JARVIS UI Preview](https://github.com/placeholder-ui-preview.png)

## 🚀 Key Features

- **Dual-Mode Interface**: 
  - **Desktop HUD**: A futuristic PyQt6 holographic interface with a pulsing AI core.
  - **Web Dashboard**: A modern, glassmorphic React dashboard with real-time waveform visualization.
- **Voice-First Interaction**: Fully hands-free activation using the "Jarvis" wake word.
- **Intelligence**: Integrated with Groq-hosted models and local Ollama (Llama 3) for deep reasoning.
- **System Automation**: Launch apps, search the web, take screenshots, and monitor system stats (CPU, RAM, Battery).
- **Active Alarms & Timers**: Real-time background monitoring for alarms and countdowns.
- **Productivity**: Integrated To-Do lists and voice-timestamped notes.
- **Media Control**: Voice-activated local music playback and volume management.

## 🛠️ Installation

### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/jarvis-ai.git
cd jarvis-ai
```

### 2. Setup Python Environment
```bash
# Install dependencies
pip install -r requirements.txt
```

### 3. Setup Web Interface (Optional)
```bash
cd web_ui
npm install
npm run build
cd ..
```

### 4. Configuration
 Rename `config.sample.json` to `config.json` and add your API keys:
```json
{
  "groq_api_key": "your_key_here",
  "groq_model": "llama-3.1-8b-instant",
    "user_name": "Ankesh"
}
```

## 🎙️ Usage

To start the assistant in **Desktop HUD mode**:
```bash
python main.py
```

To start the **FastAPI Server & Web Dashboard**:
```bash
python server.py
```
Then navigate to `http://localhost:8000`.

### Common Commands
- *"Jarvis, set a timer for 10 minutes."*
- *"Jarvis, open VS Code."*
- *"Jarvis, what is the current CPU usage?"*
- *"Jarvis, take a note: I finished the UI overhaul."*
- *"Jarvis, search for quantum computing on YouTube."*

## 📁 Project Structure

- `main.py`: Entry point for the Desktop application.
- `server.py`: Entry point for the Web Server & API.
- `alarm_manager.py`: Background service for alarms/timers.
- `voice_engine.py`: Text-to-Speech and Speech-to-Text orchestration.
- `ai_brain.py`: LLM integration (Groq/Ollama).
- `command_handler.py`: Intent parsing and system automation logic.
- `web_ui/`: React-based modern dashboard frontend.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🤝 Contributing

Contributions are welcome! Feel free to open an issue or submit a pull request.

---
*"All systems are online and ready. How may I serve you today?"*#
