"""
voice_engine.py
---------------
Handles all Speech-to-Text (STT) and Text-to-Speech (TTS) operations.
Uses SpeechRecognition for STT and pyttsx3 for offline TTS.
"""

import speech_recognition as sr
import pyttsx3
import threading
import queue
import time
import logging
import subprocess
import os
import platform
import io
from typing import Optional

logger = logging.getLogger(__name__)


class VoiceEngine:
    """
    Manages microphone input recognition and voice synthesis.
    Isolates pyttsx3 to a dedicated worker thread to prevent Windows COM errors.
    """

    def __init__(self, config: dict):
        self.config = config
        self.recognizer = sr.Recognizer()
        self.microphone = None
        self._listen_failures = 0

        self.listen_timeout = int(self.config.get("stt_timeout", 6))
        self.phrase_time_limit = int(self.config.get("stt_phrase_time_limit", 12))
        self.ambient_calibration_seconds = float(self.config.get("stt_calibration_seconds", 1.0))
        
        # Microphone fine-tuning for more reliable capture across rooms and devices.
        self.recognizer.energy_threshold = float(self.config.get("stt_energy_threshold", 300))
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.dynamic_energy_adjustment_damping = 0.15
        self.recognizer.dynamic_energy_ratio = 1.6
        self.recognizer.pause_threshold = 1.0
        self.recognizer.non_speaking_duration = 0.6

        try:
            self.microphone = sr.Microphone()
        except Exception as e:
            logger.error(f"Microphone initialization failed: {e}")

        # Run ambient noise calibration once on boot when a microphone is available.
        if self.microphone is not None:
            try:
                logger.info("Calibrating microphone for ambient noise... Please wait.")
                with self.microphone as source:
                    self.recognizer.adjust_for_ambient_noise(source, duration=self.ambient_calibration_seconds)
                logger.info("Microphone calibration complete.")
            except Exception as e:
                logger.warning(f"Ambient calibration skipped: {e}")
        
        self.speaking = False
        self.tts_engine = None
        
        # Dedicated Thread for TTS
        self.tts_queue = queue.Queue()
        self.tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self.tts_thread.start()

    def _tts_worker(self):
        """Native OS background worker for Text-to-Speech that completely bypasses Windows COM threading locks."""
        logger.info("TTS worker thread initialized successfully.")

        while True:
            text = self.tts_queue.get()
            if text is None: break
            try:
                self.speaking = True
                logger.info(f"[Nova Speaking API]: {text}")
                
                # Sanitize text for console string parsing
                clean_text = text.replace("'", "").replace('"', "")
                
                if platform.system() == "Windows":
                    # Use native PowerShell speech synthesizer to guarantee audio plays without crashing
                    cmd = f'powershell -Command "Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Speak(\'{clean_text}\')"'
                    subprocess.run(cmd, shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    # Generic fallback for macOS / Linux
                    os.system(f'say "{clean_text}"' if platform.system() == "Darwin" else f'espeak "{clean_text}"')
                    
            except Exception as e:
                logger.error(f"TTS engine error: {e}")
            finally:
                self.speaking = False
                self.tts_queue.task_done()

    def _set_voice_gender(self):
        """Select the appropriate voice based on gender preference."""
        if not self.tts_engine: return
        gender = self.config.get("voice_gender", "male").lower()
        voices = self.tts_engine.getProperty("voices")
        for voice in voices:
            voice_name = voice.name.lower()
            if gender == "female" and ("female" in voice_name or "zira" in voice_name or "hazel" in voice_name):
                self.tts_engine.setProperty("voice", voice.id)
                return
            elif gender == "male" and ("male" in voice_name or "david" in voice_name or "mark" in voice_name):
                self.tts_engine.setProperty("voice", voice.id)
                return
        if voices:
            self.tts_engine.setProperty("voice", voices[0].id)

    def speak(self, text: str):
        """
        Queue text for the TTS worker and block until finished processing.
        """
        if not text:
            return
        self.tts_queue.put(text)
        self.tts_queue.join()  # Block so microphone doesn't listen to Nova's own voice

    def listen(self, timeout: int = 5, phrase_limit: int = 15) -> str | None:
        """
        Listen from the microphone and return recognized speech as text.

        Args:
            timeout (int): Seconds to wait before giving up.
            phrase_limit (int): Max seconds for a single phrase.

        Returns:
            str | None: Recognized text or None on failure.
        """
        if self.microphone is None:
            logger.warning("Microphone is unavailable; listening is disabled.")
            return None

        with self.microphone as source:
            try:
                if self._listen_failures >= 2:
                    try:
                        self.recognizer.adjust_for_ambient_noise(source, duration=0.35)
                    except Exception:
                        pass

                audio = self.recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_limit,
                )
            except sr.WaitTimeoutError:
                self._listen_failures += 1
                return None
            except Exception as e:
                self._listen_failures += 1
                logger.error(f"Microphone error: {e}")
                return None

        return self._recognize(audio)

    def _recognize(self, audio) -> str | None:
        """
        Attempt to transcribe audio using Google Web Speech API (free tier).

        Args:
            audio: AudioData from SpeechRecognition.

        Returns:
            str | None: Transcribed text or None.
        """
        try:
            language = self.config.get("preferences", {}).get("language", "en-US")
            candidate_languages = [language]
            if "-" in language:
                candidate_languages.append(language.split("-", 1)[0])

            last_error = None
            for candidate in candidate_languages:
                try:
                    text = self.recognizer.recognize_google(audio, language=candidate)
                    logger.info(f"[User Said]: {text}")
                    self._listen_failures = 0
                    return text.lower().strip()
                except sr.UnknownValueError as e:
                    last_error = e
                    continue

            raise last_error or sr.UnknownValueError()
        except sr.UnknownValueError:
            logger.warning("Speech not understood.")
            self._listen_failures += 1
            return None
        except sr.RequestError as e:
            logger.error(f"Google STT service error: {e}")
            self._listen_failures += 1
            return None

    def process_audio_file(self, file_path_or_bytes: str | bytes) -> str | None:
        """
        Process an audio file (e.g., from web frontend) to text.
        """
        try:
            if isinstance(file_path_or_bytes, bytes):
                audio_file = sr.AudioFile(io.BytesIO(file_path_or_bytes))
            else:
                audio_file = sr.AudioFile(file_path_or_bytes)
                
            with audio_file as source:
                audio = self.recognizer.record(source)
            return self._recognize(audio)
        except Exception as e:
            logger.error(f"Error processing audio file: {e}")
            return None

    def generate_tts_file(self, text: str, output_path: str = "response.wav") -> str:
        """
        Generate a TTS audio file for the web frontend using pyttsx3.
        Returns the path to the written file.
        """
        try:
            clean_text = text.replace("'", "").replace('"', "")
            engine = pyttsx3.init()
            
            # Apply voice settings if available
            gender = self.config.get("voice_gender", "male").lower()
            voices = engine.getProperty("voices")
            for voice in voices:
                voice_name = voice.name.lower()
                if gender == "female" and ("female" in voice_name or "zira" in voice_name):
                    engine.setProperty("voice", voice.id)
                    break
                elif gender == "male" and ("male" in voice_name or "david" in voice_name):
                    engine.setProperty("voice", voice.id)
                    break
                    
            engine.save_to_file(clean_text, output_path)
            engine.runAndWait()
            return output_path
        except Exception as e:
            logger.error(f"TTS generation error: {e}")
            return ""

    def listen_for_wake_word(self, wake_word: str = "nova", timeout: int = 8) -> bool:
        """
        Continuously listen until the wake word is detected.

        Args:
            wake_word (str): The trigger keyword.
            timeout (int): Seconds to wait per listen cycle.

        Returns:
            bool: True if wake word detected, False otherwise.
        """
        end_time = time.time() + timeout
        while time.time() < end_time:
            remaining = max(1, int(end_time - time.time()))
            text = self.listen(timeout=remaining, phrase_limit=min(4, remaining))
            if text and wake_word.lower() in text:
                logger.info(f"Wake word '{wake_word}' detected!")
                return True
        return False
