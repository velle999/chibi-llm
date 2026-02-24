"""
Voice Output — Text-to-speech using Piper TTS.
Runs locally on Pi 4, lightweight and fast.

Install:
    pip install piper-tts --break-system-packages

    OR install the standalone binary:
    wget https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz
    tar xzf piper_linux_aarch64.tar.gz

Voice models download automatically on first use, or manually:
    https://huggingface.co/rhasspy/piper-voices/tree/main
"""

import subprocess
import threading
import queue
import time
import os
import wave
import io
import tempfile

# Try to use pygame.mixer for audio playback (already initialized by main app)
USE_PYGAME_AUDIO = True


class VoiceOutput:
    def __init__(self, voice="en_US-lessac-medium", speed=1.0):
        """
        voice: Piper voice name. Good options for Pi:
            - "en_US-lessac-medium"   (natural, good quality)
            - "en_US-amy-medium"      (British-ish, clear)
            - "en_US-danny-low"       (fast, lower quality)
            - "en_GB-cori-medium"     (British female)
        speed: Speech rate multiplier (1.0 = normal)
        """
        self.voice = voice
        self.speed = speed
        self.speak_queue = queue.Queue()
        self.is_speaking = False
        self._running = True
        self._piper_available = False
        self._use_piper_cli = False

        # Check what's available
        self._check_piper()

        # Start speech worker thread
        self._worker = threading.Thread(target=self._speak_worker, daemon=True)
        self._worker.start()

    def _check_piper(self):
        """Check if Piper is available (Python package or CLI)."""
        # Try Python package first
        try:
            import piper
            self._piper_available = True
            self._use_piper_cli = False
            print("[TTS] Piper Python package found!")
            return
        except ImportError:
            pass

        # Try CLI binary
        try:
            result = subprocess.run(
                ["piper", "--help"],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                self._piper_available = True
                self._use_piper_cli = True
                print("[TTS] Piper CLI binary found!")
                return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Try local binary
        local_piper = os.path.expanduser("~/piper/piper")
        if os.path.exists(local_piper):
            self._piper_available = True
            self._use_piper_cli = True
            print(f"[TTS] Found local Piper at {local_piper}")
            return

        print("[TTS] Piper not found! Install with:")
        print("[TTS]   pip install piper-tts --break-system-packages")
        print("[TTS]   OR download binary from github.com/rhasspy/piper/releases")
        print("[TTS] Falling back to espeak (if available)")

    def speak(self, text: str):
        """Queue text for speech. Non-blocking."""
        if text and text.strip():
            self.speak_queue.put(text.strip())

    def speak_now(self, text: str):
        """Clear queue and speak immediately."""
        # Clear pending items
        while not self.speak_queue.empty():
            try:
                self.speak_queue.get_nowait()
            except queue.Empty:
                break
        self.speak(text)

    def stop(self):
        """Stop current speech."""
        # Clear queue
        while not self.speak_queue.empty():
            try:
                self.speak_queue.get_nowait()
            except queue.Empty:
                break
        # TODO: interrupt current playback

    @property
    def busy(self) -> bool:
        return self.is_speaking or not self.speak_queue.empty()

    def _speak_worker(self):
        """Background thread that processes speech queue."""
        while self._running:
            try:
                text = self.speak_queue.get(timeout=0.5)
                self.is_speaking = True

                if self._piper_available:
                    if self._use_piper_cli:
                        self._speak_piper_cli(text)
                    else:
                        self._speak_piper_python(text)
                else:
                    self._speak_espeak(text)

                self.is_speaking = False

            except queue.Empty:
                continue
            except Exception as e:
                print(f"[TTS] Speech error: {e}")
                self.is_speaking = False

    def _speak_piper_python(self, text: str):
        """Synthesize and play using Piper Python package."""
        try:
            import piper
            import struct

            # Create synthesizer (cached after first call)
            if not hasattr(self, '_synth'):
                self._synth = piper.PiperVoice.load(
                    self.voice,
                    use_cuda=False,
                )

            # Synthesize to WAV in memory
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name
                with wave.open(f, "wb") as wav:
                    self._synth.synthesize(text, wav)

            # Play with pygame
            self._play_wav(temp_path)

            # Cleanup
            os.unlink(temp_path)

        except Exception as e:
            print(f"[TTS] Piper Python error: {e}")
            self._speak_espeak(text)

    def _speak_piper_cli(self, text: str):
        """Synthesize and play using Piper CLI binary."""
        try:
            # Find piper binary
            piper_bin = "piper"
            local_piper = os.path.expanduser("~/piper/piper")
            if os.path.exists(local_piper):
                piper_bin = local_piper

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name

            # Piper CLI: echo text | piper --model voice --output_file out.wav
            proc = subprocess.run(
                [piper_bin, "--model", self.voice,
                 "--output_file", temp_path,
                 "--length_scale", str(1.0 / self.speed)],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=30,
            )

            if proc.returncode == 0 and os.path.exists(temp_path):
                self._play_wav(temp_path)

            os.unlink(temp_path)

        except Exception as e:
            print(f"[TTS] Piper CLI error: {e}")
            self._speak_espeak(text)

    def _speak_espeak(self, text: str):
        """Fallback: use espeak (pre-installed on most Pi OS)."""
        try:
            speed = int(150 * self.speed)
            subprocess.run(
                ["espeak", "-s", str(speed), "-v", "en", text],
                capture_output=True,
                timeout=30,
            )
        except FileNotFoundError:
            print("[TTS] espeak not found either! No TTS available.")
        except Exception as e:
            print(f"[TTS] espeak error: {e}")

    def _play_wav(self, filepath: str):
        """Play a WAV file using pygame.mixer or aplay."""
        if USE_PYGAME_AUDIO:
            try:
                import pygame
                if pygame.mixer.get_init():
                    pygame.mixer.music.load(filepath)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy():
                        time.sleep(0.05)
                    return
            except Exception:
                pass

        # Fallback to aplay
        try:
            subprocess.run(
                ["aplay", "-q", filepath],
                capture_output=True,
                timeout=30,
            )
        except Exception as e:
            print(f"[TTS] Playback error: {e}")

    def cleanup(self):
        """Clean up resources."""
        self._running = False
        self.stop()
