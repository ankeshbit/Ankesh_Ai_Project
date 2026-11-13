"""
voice_engine.py
---------------
Handles all Speech-to-Text (STT) and Text-to-Speech (TTS) operations.
Uses SpeechRecognition for STT and pyttsx3 for offline TTS.
"""

import speech_recognition as sr
import threading
import queue
import time
import logging
import subprocess
import platform
import io
import re

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
        
        # sr.Microphone is not re-entrant: serialize access across threads.
        self._mic_lock = threading.Lock()

        self.speaking = False

        # Dedicated Thread for TTS
        self.tts_queue = queue.Queue()
        self.tts_thread = threading.Thread(target=self._tts_worker, daemon=True)
        self.tts_thread.start()

    # ──────────────────────────────────────────────────────────────────────────
    # Text-to-Speech
    # ──────────────────────────────────────────────────────────────────────────

    def _tts_settings(self) -> tuple[int, float, str]:
        """Read voice_rate (WPM), voice_volume (0-1) and voice_gender from config."""
        try:
            rate = int(self.config.get("voice_rate", 165))
        except (TypeError, ValueError):
            rate = 165
        try:
            volume = min(1.0, max(0.0, float(self.config.get("voice_volume", 1.0))))
        except (TypeError, ValueError):
            volume = 1.0
        gender = str(self.config.get("voice_gender", "male")).lower()
        return rate, volume, gender

    def _build_tts_command(self, text: str) -> tuple[list[str], dict]:
        """
        Build the OS-native TTS command for `text`.

        The text is never interpolated into a shell string: it is passed through
        an environment variable (Windows) or stdin (macOS/Linux), so quotes,
        `$(...)`, `&`, `%` etc. in a spoken reply can neither break the command
        nor execute anything.

        Returns:
            (argv, subprocess.run keyword arguments)
        """
        rate, volume, gender = self._tts_settings()
        system = platform.system()

        if system == "Windows":
            # SpeechSynthesizer.Rate is -10..10 (0 = ~165 WPM); Volume is 0..100.
            ps_rate = max(-10, min(10, round((rate - 165) / 15)))
            ps_gender = "Female" if gender == "female" else "Male"
            script = (
                "Add-Type -AssemblyName System.Speech; "
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$s.Rate = {ps_rate}; $s.Volume = {int(volume * 100)}; "
                f"try {{ $s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::{ps_gender}) }} catch {{}}; "
                "$s.Speak($env:NOVA_TTS_TEXT)"
            )
            import os
            env = {**os.environ, "NOVA_TTS_TEXT": text}
            kwargs = {"env": env, "creationflags": subprocess.CREATE_NO_WINDOW}
            return ["powershell", "-NoProfile", "-Command", script], kwargs

        if system == "Darwin":
            return ["say", "-r", str(rate), "-f", "-"], {"input": text}

        # Linux / other: espeak reads from stdin when no text argument is given.
        amplitude = int(volume * 200)
        voice = "en+f3" if gender == "female" else "en"
        return ["espeak", "-v", voice, "-s", str(rate), "-a", str(amplitude), "--stdin"], {"input": text}

    def _tts_worker(self):
        """Native OS background worker for Text-to-Speech (avoids Windows COM threading locks)."""
        logger.info("TTS worker thread initialized successfully.")

        while True:
            item = self.tts_queue.get()
            if item is None:
                break
            text, done = item
            try:
                self.speaking = True
                logger.info(f"[Nova Speaking API]: {text}")
                argv, kwargs = self._build_tts_command(text)
                # Generous cap so a hung synthesizer can never freeze the assistant.
                subprocess.run(
                    argv,
                    text=True,
                    timeout=30 + len(text) // 8,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    **kwargs,
                )
            except FileNotFoundError:
                logger.error(f"TTS command '{argv[0]}' not found. Install it (e.g. 'sudo apt install espeak') to hear Nova.")
            except subprocess.TimeoutExpired:
                logger.error("TTS timed out.")
            except Exception as e:
                logger.error(f"TTS engine error: {e}")
            finally:
                self.speaking = False
                done.set()

    def speak(self, text: str):
        """
        Queue text for the TTS worker and block until *this* utterance finishes.

        Blocking keeps the microphone from hearing Nova's own voice. Waiting on a
        per-utterance event (instead of Queue.join) means a caller is never stuck
        behind unrelated queue items, and can never hang forever if TTS dies.
        """
        if not text or not text.strip():
            return
        done = threading.Event()
        self.tts_queue.put((text, done))
        done.wait(timeout=120)

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

        with self._mic_lock, self.microphone as source:
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
            import pyttsx3  # imported lazily: only this helper needs it
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

    @staticmethod
    def contains_wake_word(text: str, wake_word: str) -> bool:
        """
        True if `wake_word` appears in `text` as a whole word.

        A plain substring test fires on "innovation" or "renovate" for the
        wake word "nova".
        """
        if not text or not wake_word:
            return False
        return re.search(rf"\b{re.escape(wake_word.lower())}\b", text.lower()) is not None

    def listen_for_wake_word(self, wake_word: str = "nova", timeout: int = 8) -> bool:
        """
        Continuously listen until the wake word is detected.

        Args:
            wake_word (str): The trigger keyword.
            timeout (int): Seconds to wait per listen cycle.

        Returns:
            bool: True if wake word detected, False otherwise.
        """
        if self.microphone is None:
            # Without a mic listen() returns instantly; don't spin the CPU.
            time.sleep(timeout)
            return False

        end_time = time.time() + timeout
        while time.time() < end_time:
            remaining = max(1, int(end_time - time.time()))
            text = self.listen(timeout=remaining, phrase_limit=min(4, remaining))
            if self.contains_wake_word(text, wake_word):
                logger.info(f"Wake word '{wake_word}' detected!")
                return True
        return False
