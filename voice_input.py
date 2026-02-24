"""
Voice Input — Speech-to-text using faster-whisper (CTranslate2 optimized Whisper).
Runs locally on the Pi 4 using the tiny model for low latency.

Install:
    pip install faster-whisper pyaudio --break-system-packages
    sudo apt install portaudio19-dev
"""

import threading
import queue
import time
import wave
import io
import tempfile
import os
import numpy as np

# Audio config
RATE = 16000
CHANNELS = 1
CHUNK = 1024
SILENCE_THRESHOLD = 500       # Amplitude threshold for silence detection
SILENCE_DURATION = 1.5        # Seconds of silence to trigger end of speech
MIN_SPEECH_DURATION = 0.5     # Minimum seconds of speech to process
MAX_SPEECH_DURATION = 30.0    # Maximum recording duration


class VoiceInput:
    def __init__(self, model_size="tiny", device="cpu", compute_type="int8"):
        """
        model_size: "tiny", "base", "small" — tiny recommended for Pi 4
        device: "cpu" for Pi
        compute_type: "int8" for Pi (fastest), "float32" for accuracy
        """
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model = None
        self.audio = None
        self.stream = None

        self.is_listening = False
        self.is_recording = False
        self.result_queue = queue.Queue()

        self._ready = False
        self._load_thread = threading.Thread(target=self._load_model, daemon=True)
        self._load_thread.start()

    def _load_model(self):
        """Load Whisper model in background."""
        try:
            from faster_whisper import WhisperModel
            print(f"[Voice] Loading Whisper {self.model_size} model...")
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
            print("[Voice] Whisper model loaded!")
            self._ready = True
        except ImportError:
            print("[Voice] faster-whisper not installed!")
            print("[Voice] Run: pip install faster-whisper --break-system-packages")
        except Exception as e:
            print(f"[Voice] Failed to load model: {e}")

    @property
    def ready(self) -> bool:
        return self._ready

    def _init_audio(self):
        """Initialize PyAudio."""
        if self.audio is None:
            import pyaudio
            self.audio = pyaudio.PyAudio()

    def start_listening(self):
        """Start the voice listening loop in a background thread."""
        if not self._ready:
            print("[Voice] Model not ready yet, waiting...")
            self._load_thread.join(timeout=30)
            if not self._ready:
                print("[Voice] Model failed to load, voice input disabled.")
                return

        self.is_listening = True
        thread = threading.Thread(target=self._listen_loop, daemon=True)
        thread.start()

    def stop_listening(self):
        """Stop listening."""
        self.is_listening = False

    def get_transcription(self) -> str | None:
        """Non-blocking: returns transcribed text or None."""
        try:
            return self.result_queue.get_nowait()
        except queue.Empty:
            return None

    def _listen_loop(self):
        """Continuous listening loop with voice activity detection."""
        self._init_audio()

        while self.is_listening:
            try:
                audio_data = self._record_speech()
                if audio_data is not None:
                    text = self._transcribe(audio_data)
                    if text and text.strip():
                        self.result_queue.put(text.strip())
            except Exception as e:
                print(f"[Voice] Error in listen loop: {e}")
                time.sleep(1)

    def _record_speech(self) -> np.ndarray | None:
        """
        Record audio with voice activity detection.
        Returns numpy array of audio data, or None if no speech detected.
        """
        import pyaudio

        stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )

        frames = []
        silent_chunks = 0
        speech_chunks = 0
        silence_limit = int(SILENCE_DURATION * RATE / CHUNK)
        min_speech_chunks = int(MIN_SPEECH_DURATION * RATE / CHUNK)
        max_chunks = int(MAX_SPEECH_DURATION * RATE / CHUNK)
        recording = False

        try:
            while self.is_listening:
                data = stream.read(CHUNK, exception_on_overflow=False)
                audio_array = np.frombuffer(data, dtype=np.int16)
                amplitude = np.abs(audio_array).mean()

                if amplitude > SILENCE_THRESHOLD:
                    if not recording:
                        recording = True
                        self.is_recording = True
                    silent_chunks = 0
                    speech_chunks += 1
                    frames.append(data)
                elif recording:
                    silent_chunks += 1
                    frames.append(data)

                    if silent_chunks > silence_limit:
                        # End of speech
                        break

                if recording and speech_chunks > max_chunks:
                    break

                # Small yield to not hog CPU
                if not recording:
                    time.sleep(0.01)

        finally:
            stream.stop_stream()
            stream.close()
            self.is_recording = False

        if speech_chunks < min_speech_chunks:
            return None

        # Convert to numpy float32 array for Whisper
        audio_bytes = b"".join(frames)
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        return audio_np

    def _transcribe(self, audio_data: np.ndarray) -> str:
        """Transcribe audio data using Whisper."""
        if self.model is None:
            return ""

        try:
            segments, info = self.model.transcribe(
                audio_data,
                beam_size=1,            # Fastest
                language="en",          # Set to None for auto-detect
                vad_filter=True,        # Filter out non-speech
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                ),
            )

            text = " ".join(segment.text for segment in segments)
            return text.strip()

        except Exception as e:
            print(f"[Voice] Transcription error: {e}")
            return ""

    def cleanup(self):
        """Clean up audio resources."""
        self.is_listening = False
        if self.audio:
            self.audio.terminate()
