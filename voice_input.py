"""
Voice Input — Speech-to-text using faster-whisper (CTranslate2 optimized Whisper).
Runs locally on the Pi 4 using the tiny model for low latency.

Audio capture is done by streaming raw PCM from an external recorder subprocess
(`arecord` or, as a fallback, `pw-record`). This deliberately AVOIDS
PortAudio / PyAudio / sounddevice: libportaudio hard-links libjack, and merely
initializing it spawns a pipewire-jack client whose data loop can segfault the
whole process (a native crash Python cannot catch). The recorder subprocesses
talk to ALSA / PipeWire directly and never load libjack.

Install:
    pip install faster-whisper --break-system-packages
    # capture needs one of:  alsa-utils (arecord)  or  pipewire (pw-record)
"""

import os
import re
import threading
import queue
import time
import shutil
import subprocess
import numpy as np

# Audio config
RATE = 16000
CHANNELS = 1
CHUNK = 1024
SILENCE_THRESHOLD = 500       # Amplitude threshold for silence detection
SILENCE_DURATION = 1.5        # Seconds of silence to trigger end of speech
MIN_SPEECH_DURATION = 0.5     # Minimum seconds of speech to process
MAX_SPEECH_DURATION = 30.0    # Maximum recording duration

_BYTES_PER_SAMPLE = 2         # s16le

# Whisper-tiny hallucinates these stock phrases on low-level noise / near-silence
# (TV hum, fan, a cough). They're indistinguishable from real one-word replies by
# text alone, so we drop any transcription whose normalized form is exactly one of
# these. Multi-word real speech ("you were right") is unaffected — only the bare
# phrase matches.
_NOISE_HALLUCINATIONS = {
    "", "you", "thank you", "thanks", "thanks for watching",
    "thank you for watching", "thank you very much", "bye", "bye bye",
    "please subscribe", "see you next time", "okay", "ok", "uh", "um", "hmm",
    "subtitles by the amara.org community", "transcription by castingwords",
    "the", "yeah", "so",
}


def _resolve_alsa_device():
    """Pick an ALSA capture device for arecord.

    The bare ALSA ``default`` device is frequently absent on a headless Pi
    (no card 0 capture), so ``arecord`` exits instantly with "audio open
    error: No such file or directory" and the recorder appears to "stop
    unexpectedly". So: honour an explicit ``CHIBI_MIC_DEVICE`` override;
    otherwise probe ``arecord -l`` and address the first capture card by
    NAME. The USB index (``hw:3``) drifts across reboots/replugs, but
    ``plughw:CARD=<name>`` is stable and also converts to s16le @ RATE if the
    mic can't deliver that natively. Returns None to fall back to ``default``.
    """
    override = os.environ.get("CHIBI_MIC_DEVICE")
    if override:
        return override
    try:
        out = subprocess.run(
            ["arecord", "-l"], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:
        return None
    m = re.search(r"^card \d+: (\S+)", out, re.MULTILINE)
    if m:
        return f"plughw:CARD={m.group(1)},DEV=0"
    return None


def _build_capture_cmd():
    """
    Return (argv, name) for a raw-PCM recorder, preferring arecord (ALSA),
    falling back to pw-record (PipeWire). Returns (None, None) if neither
    is installed.
    """
    if shutil.which("arecord"):
        cmd = [
            "arecord", "-q",
            "-f", "S16_LE",
            "-r", str(RATE),
            "-c", str(CHANNELS),
            "-t", "raw",
        ]
        device = _resolve_alsa_device()
        if device:
            cmd += ["-D", device]
        cmd.append("-")
        return (cmd, f"arecord ({device or 'default'})")
    if shutil.which("pw-record"):
        return ([
            "pw-record",
            "--rate", str(RATE),
            "--channels", str(CHANNELS),
            "--format", "s16",
            "--raw",
            "-",
        ], "pw-record")
    return (None, None)


class VoiceInput:
    def __init__(self, model_size="tiny", device="cpu", compute_type="int8",
                 silence_threshold=SILENCE_THRESHOLD,
                 min_speech_duration=MIN_SPEECH_DURATION):
        """
        model_size: "tiny", "base", "small" — tiny recommended for Pi 4
        device: "cpu" for Pi
        compute_type: "int8" for Pi (fastest), "float32" for accuracy
        silence_threshold: mean-amplitude floor to start recording. Higher =
            less sensitive (keeps the TV / room noise from triggering).
        min_speech_duration: drop captures shorter than this (seconds).
        """
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.silence_threshold = silence_threshold
        self.min_speech_duration = min_speech_duration
        self.model = None
        self._proc = None

        self.is_listening = False
        self.is_recording = False
        # When muted (set by the app while Chibi is speaking), the listen loop
        # keeps reading the recorder so its pipe doesn't back up, but discards
        # the audio and clears the queue — this is the half-duplex guard that
        # stops Chibi's own TTS from being transcribed and fed back as input.
        self.muted = False
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

    def _open_stream(self):
        """Start the recorder subprocess streaming raw s16le PCM to stdout."""
        cmd, name = _build_capture_cmd()
        if cmd is None:
            raise RuntimeError(
                "no audio recorder found — install alsa-utils (arecord) "
                "or pipewire (pw-record)"
            )
        print(f"[Voice] Capturing audio via {name}")
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

    def _close_stream(self):
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    def _read_chunk(self) -> np.ndarray | None:
        """Read exactly CHUNK samples of int16 PCM, or None on EOF/death."""
        want = CHUNK * _BYTES_PER_SAMPLE
        buf = b""
        while len(buf) < want:
            part = self._proc.stdout.read(want - len(buf))
            if not part:
                return None  # recorder exited / EOF
            buf += part
        return np.frombuffer(buf, dtype=np.int16)

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
        try:
            self._open_stream()
        except Exception as e:
            print(f"[Voice] Could not start audio capture: {e}")
            self.is_listening = False
            return

        try:
            while self.is_listening:
                try:
                    if self.muted:
                        # Chibi is speaking: keep the recorder drained so its
                        # pipe doesn't back up, but throw the audio away and
                        # clear anything already queued, so its TTS is never
                        # transcribed and looped back as fake input.
                        if self._read_chunk() is None:
                            raise RuntimeError("audio recorder stopped unexpectedly")
                        self._drain_queue()
                        continue
                    audio_data = self._record_speech()
                    if audio_data is not None and not self.muted:
                        text = self._transcribe(audio_data)
                        if text and text.strip() and not self.muted:
                            self.result_queue.put(text.strip())
                except Exception as e:
                    print(f"[Voice] Error in listen loop: {e}")
                    time.sleep(1)
        finally:
            self._close_stream()

    def _drain_queue(self):
        """Discard any pending transcriptions."""
        try:
            while True:
                self.result_queue.get_nowait()
        except queue.Empty:
            pass

    def _record_speech(self) -> np.ndarray | None:
        """
        Record audio with voice activity detection from the recorder stream.
        Returns numpy array of audio data, or None if no speech detected.
        """
        frames = []
        silent_chunks = 0
        speech_chunks = 0
        silence_limit = int(SILENCE_DURATION * RATE / CHUNK)
        min_speech_chunks = int(self.min_speech_duration * RATE / CHUNK)
        max_chunks = int(MAX_SPEECH_DURATION * RATE / CHUNK)
        recording = False

        try:
            while self.is_listening and not self.muted:
                audio_array = self._read_chunk()
                if audio_array is None:
                    # recorder died; surface as error so the loop can restart it
                    raise RuntimeError("audio recorder stopped unexpectedly")
                amplitude = np.abs(audio_array.astype(np.int32)).mean()

                if amplitude > self.silence_threshold:
                    if not recording:
                        recording = True
                        self.is_recording = True
                    silent_chunks = 0
                    speech_chunks += 1
                    frames.append(audio_array.copy())
                elif recording:
                    silent_chunks += 1
                    frames.append(audio_array.copy())

                    if silent_chunks > silence_limit:
                        # End of speech
                        break

                if recording and speech_chunks > max_chunks:
                    break
        finally:
            self.is_recording = False

        if speech_chunks < min_speech_chunks:
            return None

        # Convert to numpy float32 array for Whisper
        audio_np = np.concatenate(frames).astype(np.float32) / 32768.0
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
                condition_on_previous_text=False,  # don't let prior text seed loops
            )

            # Keep only confident, speech-like segments. Whisper-tiny emits a
            # high no_speech_prob and a very low avg_logprob when it's
            # "transcribing" noise — drop those instead of forwarding a
            # hallucinated phrase to the LLM.
            kept = []
            for seg in segments:
                no_speech = getattr(seg, "no_speech_prob", 0.0)
                avg_logprob = getattr(seg, "avg_logprob", 0.0)
                if no_speech > 0.6:
                    continue
                if avg_logprob < -1.0:
                    continue
                kept.append(seg.text)

            text = " ".join(kept).strip()

            # Drop bare known-hallucination phrases (normalized: lowercase,
            # punctuation stripped). Real multi-word speech is untouched.
            norm = re.sub(r"[^a-z' ]", "", text.lower()).strip()
            norm = re.sub(r"\s+", " ", norm)
            if norm in _NOISE_HALLUCINATIONS:
                return ""

            return text

        except Exception as e:
            print(f"[Voice] Transcription error: {e}")
            return ""

    def cleanup(self):
        """Clean up audio resources."""
        self.is_listening = False
        self._close_stream()
