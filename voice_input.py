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


def _has_alsa_pcm(name):
    """Is ``name`` a PCM ALSA can open?

    Matched at COLUMN 0. ``arecord -L`` prints each PCM name flush left with an
    indented description under it, and those descriptions mention "pipewire"
    too — an ``in`` test over the whole output, or a strip() per line, answers
    yes on a box that has no such device and hands arecord a name that does not
    open.
    """
    try:
        out = subprocess.run(
            ["arecord", "-L"], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:
        return False
    return any(line.rstrip() == name for line in out.splitlines())


def _resolve_alsa_device():
    """Pick an ALSA capture device for arecord.

    ⛔ THE FIRST CARD IS NOT THE MICROPHONE. This used to take the first
    ``card N:`` out of ``arecord -l`` and address it by name, which is right on
    the single-card Pi this was written for and wrong on anything else: on a
    desktop the first card is the built-in analogue codec, usually with nothing
    plugged into it, and the USB microphone is card 3. chibi then recorded an
    empty jack — peak 153/32768 against 925 from the mic actually in use — and
    every attempt came back "heard nothing", which is ALSO the message for a
    user who simply said nothing. An empty jack is not an error: arecord opens
    it, reads its noise floor and exits 0, so nothing anywhere reports a wrong
    device. The only symptom is that it never works.

    So: an explicit ``CHIBI_MIC_DEVICE`` first — it is the escape hatch and
    somebody who set it meant it. Then PipeWire's own PCM, which follows the
    DEFAULT SOURCE and therefore tracks whatever the desktop is set to,
    including a microphone plugged in or swapped mid-session. Naming the right
    card instead would pin today's hardware and be wrong again at the next
    replug.

    Only then the old first-card probe, unchanged, for the Pi: the bare ALSA
    ``default`` is frequently absent there (no card 0 capture), so ``arecord``
    exits instantly with "audio open error: No such file or directory" and the
    recorder appears to "stop unexpectedly". ``plughw:CARD=<name>`` is stable
    where the USB index (``hw:3``) drifts across reboots, and it converts to
    s16le @ RATE if the mic cannot deliver that natively.

    Returns None to fall back to ``default``.
    """
    override = os.environ.get("CHIBI_MIC_DEVICE")
    if override:
        return override
    # Not cached: this runs once at the start of a capture that already costs
    # seconds of model load, and a cached answer would outlive the audio stack
    # it described.
    if _has_alsa_pcm("pipewire"):
        return "pipewire"
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
                 min_speech_duration=MIN_SPEECH_DURATION,
                 oww_enabled=False, oww_model="", oww_threshold=0.5,
                 model_dir=""):
        """
        model_size: "tiny", "base", "small" — tiny recommended for Pi 4
        model_dir: path to an already-converted faster-whisper model directory.
            When set, it is loaded directly instead of `model_size` — which is
            what makes offline startup possible: a bare model NAME sends
            faster-whisper to HuggingFace to download ~75MB on first run, so a
            freshly installed machine with no network would come up deaf. The
            SynapseOS package ships the model and points this at it.
        device: "cpu" for Pi
        compute_type: "int8" for Pi (fastest), "float32" for accuracy
        silence_threshold: mean-amplitude floor to start recording. Higher =
            less sensitive (keeps the TV / room noise from triggering).
        min_speech_duration: drop captures shorter than this (seconds).
        oww_*: optional openWakeWord engine — a detection sets wake_detected
            (polled by the app), which opens the conversation window exactly
            like saying the transcription wake word. Degrades to disabled if
            the package/model isn't available.
        """
        self.model_size = model_size
        self.model_dir = model_dir
        self.device = device
        self.compute_type = compute_type
        self.silence_threshold = silence_threshold
        self.min_speech_duration = min_speech_duration
        self.model = None
        self._proc = None

        # Optional wake-word engine (experimental; config oww_enabled)
        self._oww = None
        self._oww_threshold = oww_threshold
        self.wake_detected = False
        if oww_enabled:
            self._init_oww(oww_model)

        self.is_listening = False
        self.is_recording = False
        # When muted (set by the app while Chibi is speaking), the listen loop
        # keeps reading the recorder so its pipe doesn't back up, but discards
        # the audio and clears the queue — this is the half-duplex guard that
        # stops Chibi's own TTS from being transcribed and fed back as input.
        self.muted = False
        self.result_queue = queue.Queue()
        # Throttle the "capture unavailable" log when the mic is missing
        # (e.g. USB camera unplugged) so it doesn't flood the log file.
        self._last_capture_err_log = 0.0

        self._ready = False
        self._load_thread = threading.Thread(target=self._load_model, daemon=True)
        self._load_thread.start()

    def _load_model(self):
        """Load Whisper model in background."""
        try:
            from faster_whisper import WhisperModel
            # A local directory is loaded as-is; a bare size name makes
            # faster-whisper fetch it from HuggingFace on first run.
            if self.model_dir and os.path.isdir(self.model_dir):
                target = self.model_dir
                print(f"[Voice] Loading Whisper from {target} (offline)...")
            else:
                if self.model_dir:
                    print(f"[Voice] stt_model_dir {self.model_dir!r} not found — "
                          "falling back to download")
                target = self.model_size
                print(f"[Voice] Loading Whisper {target} model...")
            self.model = WhisperModel(
                target,
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

    def _init_oww(self, model_path: str):
        """Load openWakeWord if installed; any failure just disables it."""
        try:
            from openwakeword.model import Model
            kwargs = {"wakeword_models": [model_path]} if model_path else {}
            self._oww = Model(**kwargs)
            print(f"[Voice] openWakeWord active "
                  f"({model_path or 'bundled models'})")
        except Exception as e:
            print(f"[Voice] openWakeWord unavailable ({e}); "
                  f"using the transcription wake word only.")
            self._oww = None

    def consume_wake_detection(self) -> bool:
        """True once per wake-word detection (cleared on read)."""
        if self.wake_detected:
            self.wake_detected = False
            return True
        return False

    def _feed_oww(self, chunk: np.ndarray):
        """Run the wake-word model on a PCM chunk; sets wake_detected on a hit."""
        try:
            scores = self._oww.predict(chunk)
            if scores and max(scores.values()) >= self._oww_threshold:
                self.wake_detected = True
                self._oww.reset()
        except Exception as e:
            print(f"[Voice] openWakeWord error ({e}); disabling engine.")
            self._oww = None

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
                    # The recorder subprocess died — usually the USB mic was
                    # unplugged / never enumerated (arecord falls back to a
                    # non-existent "default" and exits instantly). Tear the dead
                    # process down and REOPEN the stream so capture self-heals
                    # when the device comes back, instead of spinning forever on
                    # a corpse. Log is throttled to once / 30s so a missing mic
                    # doesn't flood chibi.log.
                    self._close_stream()
                    now = time.time()
                    if now - self._last_capture_err_log > 30:
                        print(f"[Voice] Audio capture unavailable ({e}); "
                              f"is the mic plugged in? Retrying until it returns.")
                        self._last_capture_err_log = now
                    time.sleep(3)
                    try:
                        self._open_stream()
                    except Exception:
                        pass  # still gone; back off and retry on the next pass
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
                # Wake-word engine sees every (unmuted) chunk, whether or not
                # VAD is currently recording.
                if self._oww is not None:
                    self._feed_oww(audio_array)
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

            text = " ".join(seg.text for seg in segments).strip()

            # Drop bare known-hallucination phrases (normalized: lowercase,
            # punctuation stripped). Real multi-word speech is untouched.
            #
            # NOTE: we deliberately do NOT gate on per-segment avg_logprob /
            # no_speech_prob. On a marginal mic (the PS3 Eye) those run low for
            # genuine speech too, which silently ate real input — "records but
            # never activates". Whisper's own vad_filter plus this phrase list
            # are enough to suppress the common noise hallucinations.
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
