"""
Voice Output — Cute TTS for Chibi using Piper.

Piper voices that sound good for a kawaii character:
  - en_US-lessac-medium   (warm female, good default)
  - en_GB-cori-medium     (bright British female, cute)
  - en_US-amy-medium      (clear, slightly higher pitch)
  - en_GB-aru-medium      (gentle British female, multi-speaker)

The trick for a "cute" voice: use a naturally higher-pitched voice
and optionally speed it up slightly + pitch shift with sox/ffmpeg.

Setup on Pi:
    pip install piper-tts --break-system-packages
    # OR download binary:
    mkdir -p ~/piper && cd ~/piper
    wget https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz
    tar xzf piper_linux_aarch64.tar.gz

    # Download a voice model:
    mkdir -p ~/.local/share/piper-voices
    cd ~/.local/share/piper-voices
    wget https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/cori/medium/en_GB-cori-medium.onnx
    wget https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/cori/medium/en_GB-cori-medium.onnx.json

    # Optional for pitch shifting:
    sudo apt install sox libsox-fmt-all
"""

import subprocess
import threading
import queue
import time
import os
import sys
import tempfile

# Auto-detect platform for audio playback
IS_WINDOWS = sys.platform == "win32"
USE_APLAY = not IS_WINDOWS  # aplay on Linux, pygame.mixer on Windows


class VoiceOutput:
    def __init__(self, voice="en_GB-cori-medium", speed=1.0, pitch_semitones=0):
        """
        voice: Piper voice name or path to .onnx file
        speed: Speech rate via length_scale (< 1.0 = faster, > 1.0 = slower)
               Note: Piper length_scale is inverted — lower = faster
        pitch_semitones: Shift pitch up/down with sox (0 = no shift, 2-3 = cuter)
        """
        self.voice = voice
        self.speed = speed
        self.pitch_semitones = pitch_semitones
        self.speak_queue = queue.Queue()
        self.is_speaking = False
        self._running = True
        self._piper_cmd = None
        self._voice_path = None
        self._sox_available = False

        self._find_piper()
        self._find_voice()
        self._check_sox()

        # Start speech worker
        self._worker = threading.Thread(target=self._speak_worker, daemon=True)
        self._worker.start()

    def _find_piper(self):
        """Find the piper binary."""
        # Check pip-installed piper
        try:
            result = subprocess.run(["piper", "--version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                self._piper_cmd = "piper"
                print("[TTS] Found piper (pip install)")
                return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Check local binary
        local = os.path.expanduser("~/piper/piper")
        if os.path.exists(local):
            self._piper_cmd = local
            print(f"[TTS] Found piper at {local}")
            return

        # Check python module
        try:
            import piper
            self._piper_cmd = "__python__"
            print("[TTS] Found piper Python module")
            return
        except ImportError:
            pass

        print("[TTS] ⚠ Piper not found! Voice will fall back to espeak.")
        print("[TTS] Install: pip install piper-tts --break-system-packages")

    def _find_voice(self):
        """Find the voice model file."""
        if self._piper_cmd == "__python__":
            # Python module handles voice download itself
            self._voice_path = self.voice
            return

        voice_dirs = [
            os.path.expanduser("~/.local/share/piper-voices"),
            os.path.expanduser("~/piper-voices"),
            os.path.join(os.environ.get("USERPROFILE", ""), ".local", "share", "piper-voices"),
            "/usr/share/piper-voices",
        ]

        # Check if voice is already a full path
        if os.path.exists(self.voice):
            self._voice_path = self.voice
            print(f"[TTS] Voice model: {self.voice}")
            return

        # Search for .onnx file matching voice name
        for d in voice_dirs:
            candidate = os.path.join(d, f"{self.voice}.onnx")
            if os.path.exists(candidate):
                self._voice_path = candidate
                print(f"[TTS] Voice model: {candidate}")
                return

        # Not found — piper can auto-download some voices
        self._voice_path = self.voice
        print(f"[TTS] Voice '{self.voice}' not found locally, piper may download it")

    def _check_sox(self):
        """Check if sox is available for pitch shifting."""
        try:
            result = subprocess.run(["sox", "--version"], capture_output=True, timeout=3)
            self._sox_available = result.returncode == 0
            if self._sox_available:
                print(f"[TTS] Sox available — pitch shift: {self.pitch_semitones} semitones")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._sox_available = False

    def speak(self, text: str):
        """Queue text for speech. Non-blocking."""
        if text and text.strip():
            # Clean text for TTS — strip special chars that confuse piper
            clean = text.strip()
            clean = clean.replace('"', '').replace("'", "'")
            clean = clean.replace(':3', '').replace('^_^', '')
            clean = clean.replace('>w<', '').replace('~', '')
            if clean:
                self.speak_queue.put(clean)

    def speak_now(self, text: str):
        """Clear queue and speak immediately."""
        while not self.speak_queue.empty():
            try:
                self.speak_queue.get_nowait()
            except queue.Empty:
                break
        self.speak(text)

    def stop(self):
        """Stop and clear queue."""
        while not self.speak_queue.empty():
            try:
                self.speak_queue.get_nowait()
            except queue.Empty:
                break

    @property
    def busy(self) -> bool:
        return self.is_speaking or not self.speak_queue.empty()

    def _speak_worker(self):
        """Background thread processing speech queue."""
        while self._running:
            try:
                text = self.speak_queue.get(timeout=0.5)
                self.is_speaking = True
                self._synthesize_and_play(text)
                self.is_speaking = False
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[TTS] Error: {e}")
                self.is_speaking = False

    def _synthesize_and_play(self, text: str):
        """Synthesize text to WAV and play it."""
        if self._piper_cmd == "__python__":
            self._speak_piper_python(text)
        elif self._piper_cmd:
            self._speak_piper_cli(text)
        else:
            self._speak_espeak(text)

    def _speak_piper_cli(self, text: str):
        """Synthesize with Piper CLI, optionally pitch-shift with sox."""
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                raw_path = f.name

            # Piper synthesis
            # length_scale: lower = faster. 0.9 = slightly faster & perkier
            length_scale = 1.0 / self.speed if self.speed > 0 else 1.0

            proc = subprocess.run(
                [self._piper_cmd,
                 "--model", self._voice_path,
                 "--output_file", raw_path,
                 "--length_scale", str(length_scale),
                 "--sentence_silence", "0.15"],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=30,
            )

            if proc.returncode != 0:
                stderr = proc.stderr.decode(errors='replace')
                print(f"[TTS] Piper error: {stderr[:200]}")
                self._speak_espeak(text)
                return

            play_path = raw_path

            # Pitch shift with sox if available and requested
            if self._sox_available and self.pitch_semitones != 0:
                shifted_path = raw_path + ".shifted.wav"
                try:
                    subprocess.run(
                        ["sox", raw_path, shifted_path,
                         "pitch", str(self.pitch_semitones * 100),
                         "rate", "22050"],
                        capture_output=True, timeout=10,
                    )
                    if os.path.exists(shifted_path) and os.path.getsize(shifted_path) > 100:
                        play_path = shifted_path
                except Exception as e:
                    print(f"[TTS] Sox pitch error: {e}")

            # Play
            self._play_wav(play_path)

            # Cleanup
            for p in [raw_path, raw_path + ".shifted.wav"]:
                try:
                    os.unlink(p)
                except OSError:
                    pass

        except subprocess.TimeoutExpired:
            print("[TTS] Piper timed out")
        except Exception as e:
            print(f"[TTS] Piper CLI error: {e}")
            self._speak_espeak(text)

    def _speak_piper_python(self, text: str):
        """Synthesize with Piper Python module."""
        try:
            import piper
            import wave

            if not hasattr(self, '_synth'):
                self._synth = piper.PiperVoice.load(self._voice_path, use_cuda=False)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name
                with wave.open(f, "wb") as wav:
                    self._synth.synthesize(text, wav,
                                           length_scale=1.0 / self.speed if self.speed > 0 else 1.0)

            play_path = temp_path

            # Pitch shift
            if self._sox_available and self.pitch_semitones != 0:
                shifted = temp_path + ".shifted.wav"
                try:
                    subprocess.run(
                        ["sox", temp_path, shifted,
                         "pitch", str(self.pitch_semitones * 100),
                         "rate", "22050"],
                        capture_output=True, timeout=10,
                    )
                    if os.path.exists(shifted) and os.path.getsize(shifted) > 100:
                        play_path = shifted
                except Exception:
                    pass

            self._play_wav(play_path)

            for p in [temp_path, temp_path + ".shifted.wav"]:
                try:
                    os.unlink(p)
                except OSError:
                    pass

        except Exception as e:
            print(f"[TTS] Piper Python error: {e}")
            self._speak_espeak(text)

    def _speak_espeak(self, text: str):
        """Fallback — espeak with higher pitch to sound cuter."""
        # On Windows, espeak might be in Program Files
        espeak_cmd = "espeak"
        if IS_WINDOWS:
            pf = os.environ.get("ProgramFiles", r"C:\Program Files")
            win_path = os.path.join(pf, "eSpeak NG", "espeak-ng.exe")
            if os.path.exists(win_path):
                espeak_cmd = win_path

        try:
            subprocess.run(
                [espeak_cmd,
                 "-s", "160",    # speed (words per minute)
                 "-p", "80",     # pitch (0-99, higher = cuter)
                 "-v", "en+f3",  # female voice variant 3
                 text],
                capture_output=True,
                timeout=30,
            )
        except FileNotFoundError:
            print("[TTS] espeak not found! No TTS available.")
            if IS_WINDOWS:
                print("[TTS] Install eSpeak NG from https://github.com/espeak-ng/espeak-ng/releases")
        except subprocess.TimeoutExpired:
            print("[TTS] espeak timed out")
        except Exception as e:
            print(f"[TTS] espeak error: {e}")

    def _play_wav(self, filepath: str):
        """Play a WAV file — prefer aplay on Pi, with hard timeout."""
        if not os.path.exists(filepath):
            return

        if USE_APLAY:
            try:
                subprocess.run(
                    ["aplay", "-q", filepath],
                    capture_output=True,
                    timeout=30,
                )
                return
            except FileNotFoundError:
                pass  # Fall through to pygame
            except subprocess.TimeoutExpired:
                print("[TTS] aplay timed out")
                return
            except Exception as e:
                print(f"[TTS] aplay error: {e}")

        # Fallback: pygame.mixer
        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.music.load(filepath)
                pygame.mixer.music.play()
                start = time.time()
                while pygame.mixer.music.get_busy() and (time.time() - start) < 30:
                    time.sleep(0.05)
                pygame.mixer.music.stop()
        except Exception as e:
            print(f"[TTS] pygame playback error: {e}")

    def cleanup(self):
        self._running = False
        self.stop()
