from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import asyncio
import os
import logging
from pathlib import Path

from utils import load_config, setup_logging
from voice_engine import VoiceEngine
from ai_brain import AIBrain
from command_handler import CommandHandler
from alarm_manager import AlarmManager

setup_logging("INFO")
logger = logging.getLogger(__name__)

app = FastAPI(title="Jarvis Web Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Core Modules
config = load_config()
alarm_manager = AlarmManager()

voice = VoiceEngine(config)
brain = AIBrain(config)
commands = CommandHandler(config, alarm_manager=alarm_manager)

def on_alarm_triggered(trigger_type: str, label: str):
    """Callback for AlarmManager in web server mode."""
    logger.info(f"ALARM TRIGGERED: {trigger_type}")
    asyncio.run_coroutine_threadsafe(
        manager.broadcast({
            "status": "Alarm", 
            "type": "bot", 
            "text": f"ALARM: Your {trigger_type} for {label} is going off!"
        }),
        loop
    )

alarm_manager.set_callback(on_alarm_triggered)
alarm_manager.start()

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()


@app.post("/api/stt")
async def process_audio(file: UploadFile = File(...)):
    """Receives audio file from frontend, processes it, and returns Jarvis's response text and audio."""
    try:
        audio_bytes = await file.read()
        
        await manager.broadcast({"status": "Processing", "text": "Recognizing audio..."})
        
        # 1. Transcribe Audio
        user_text = voice.process_audio_file(audio_bytes)
        
        if not user_text:
            error_msg = "I didn't catch that."
            await manager.broadcast({"status": "Error", "text": error_msg})
            return JSONResponse({"user_text": "", "response_text": error_msg, "audio_url": ""})
            
        await manager.broadcast({"status": "Processing", "type": "user", "text": user_text})
        
        # 2. Route to commands
        response, handled = commands.handle(user_text)
        
        if not handled or not response:
            # 3. Route to AI Brain
            response = brain.ask(user_text)
            
        if "clear memory" in user_text.lower() or "forget everything" in user_text.lower():
            brain.clear_memory()
            
        if commands.is_exit_command(user_text):
            response = "Goodbye, Sir. Jarvis signing off."
            
        # 4. Generate TTS
        await manager.broadcast({"status": "Speaking", "type": "bot", "text": response})
        audio_path = "workspace_tts.wav"
        voice.generate_tts_file(response, audio_path)
        
        # 5. Reset status gracefully after a short delay letting UI update
        asyncio.create_task(reset_status_after(2))
        
        return JSONResponse({
            "user_text": user_text,
            "response_text": response,
            "audio_url": f"/api/audio?t={asyncio.get_event_loop().time()}"
        })
        
    except Exception as e:
        logger.error(f"Error in /api/stt: {str(e)}")
        await manager.broadcast({"status": "Error", "text": "An error occurred during processing."})
        return JSONResponse({"error": str(e)}, status_code=500)

async def reset_status_after(delay: float):
    await asyncio.sleep(delay)
    await manager.broadcast({"status": "Idle"})


@app.get("/api/audio")
async def get_audio():
    """Serves the latest TTS audio file."""
    if os.path.exists("workspace_tts.wav"):
        return FileResponse("workspace_tts.wav", media_type="audio/wav")
    return JSONResponse({"error": "No audio available"}, status_code=404)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Can be extended to accept JSON text commands directly via WS
            data = await websocket.receive_text()
            logger.info(f"Received WS text: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def broadcast_system_stats():
    """Background task to push CPU/RAM stats to the UI."""
    try:
        import psutil
        while True:
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            battery = psutil.sensors_battery()
            percent = battery.percent if battery else 100
            
            await manager.broadcast({
                "type": "stats",
                "cpu": cpu,
                "ram": ram,
                "battery": percent
            })
            await asyncio.sleep(2)
    except Exception as e:
        logger.error(f"Stats broadcast error: {e}")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(broadcast_system_stats())


# Mount Web UI if built
frontend_path = Path("web_ui/dist")
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
else:
    @app.get("/")
    def index():
        return {"message": "Frontend not built yet. cd web_ui && npm run build"}


def run_server():
    global loop
    loop = asyncio.get_event_loop()
    uvicorn.run("server:app", host="0.0.0.0", port=8000, log_level="info")

if __name__ == "__main__":
    run_server()
