"""
Voice Input — Speech-to-text using faster-whisper + sounddevice.

Uses callback-based InputStream to avoid Windows blocking API bugs.
Prioritizes DirectSound/MME host APIs which handle sample rate
conversion internally (WASAPI exclusive mode does not).

Install:
    pip install faster-whisper sounddevice numpy
"""

import threading
import queue
import time
import numpy as np
import sys


# Audio config
TARGET_RATE = 16000
SILENCE_THRESHOLD = 500
SILENCE_DURATION = 1.5
MIN_SPEECH_DURATION = 0.5
MAX_SPEECH_DURATION = 30.0


class VoiceInput:
    def __init__(self, model_size="tiny", device="cpu", compute_type="int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model = None

        self.is_listening = False
        self.is_recording = False
        self.result_queue = queue.Queue()

        self._sd = None
        self._mic_device = None
        self._mic_rate = None
        self._mic_channels = 1
        self._audio_queue = queue.Queue()

        self._ready = False
        self._load_thread = threading.Thread(target=self._load_model, daemon=True)
        self._load_thread.start()

    def _load_model(self):
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
            print("[Voice] faster-whisper not installed! Run: pip install faster-whisper")
        except Exception as e:
            print(f"[Voice] Failed to load model: {e}")

    @property
    def ready(self) -> bool:
        return self._ready

    def _init_audio(self):
        """Find a working mic using callback-based streams."""
        if self._sd is not None:
            return self._mic_device is not None

        try:
            import sounddevice as sd
            self._sd = sd
        except ImportError:
            print("[Voice] sounddevice not installed! Run: pip install sounddevice")
            return False

        devices = sd.query_devices()
        apis = sd.query_hostapis()

        # Log what we see
        print(f"[Voice] {len(devices)} audio devices across {len(apis)} host APIs")

        # Build list of input devices with API info
        input_devs = []
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                api_name = apis[dev['hostapi']]['name']
                input_devs.append({
                    'index': i,
                    'name': dev['name'],
                    'api': api_name,
                    'rate': int(dev['default_samplerate']),
                    'channels': dev['max_input_channels'],
                })
                print(f"[Voice]   [{i}] {dev['name']} | {api_name} | "
                      f"{dev['max_input_channels']}ch {int(dev['default_samplerate'])}Hz")

        if not input_devs:
            print("[Voice] No input devices!")
            return False

        # Sort by API reliability: DirectSound > MME > WASAPI > WDM-KS
        api_rank = {
            'Windows DirectSound': 0,
            'MME': 1,
            'Core Audio': 0,     # macOS
            'ALSA': 0,           # Linux
            'Windows WASAPI': 2,
            'Windows WDM-KS': 3,
        }
        input_devs.sort(key=lambda d: api_rank.get(d['api'], 5))

        # Test each with callback stream
        for dev in input_devs:
            idx = dev['index']
            name = dev['name']
            api = dev['api']
            native_rate = dev['rate']
            max_ch = dev['channels']

            rates = list(dict.fromkeys([native_rate, 48000, 44100, 16000, 22050]))
            channels_list = [1, 2] if max_ch >= 2 else [max_ch]

            for ch in channels_list:
                for rate in rates:
                    ok = self._test_callback_stream(idx, rate, ch)
                    if ok:
                        self._mic_device = idx
                        self._mic_rate = rate
                        self._mic_channels = ch
                        print(f"[Voice] ✓ Mic: [{idx}] {name} ({rate}Hz {ch}ch {api})")
                        return True
                    # Don't print every failure — just the first per device
            print(f"[Voice]   ✗ [{idx}] {name} — no working config")

        print("[Voice] ⚠ No working mic found!")
        return False

    def _test_callback_stream(self, device, samplerate, channels):
        """Test if a device works by opening a callback stream and reading data."""
        import sounddevice as sd

        got_data = threading.Event()

        def callback(indata, frames, time_info, status):
            got_data.set()
            raise sd.CallbackStop()

        try:
            stream = sd.InputStream(
                device=device,
                samplerate=samplerate,
                channels=channels,
                dtype='int16',
                blocksize=1024,
                callback=callback,
            )
            stream.start()
            success = got_data.wait(timeout=2)
            stream.stop()
            stream.close()
            return success
        except Exception:
            return False

    # ─── Listening ──────────────────────────────────────────────────────

    def start_listening(self):
        if not self._ready:
            self._load_thread.join(timeout=30)
            if not self._ready:
                print("[Voice] Model failed to load.")
                return
        self.is_listening = True
        thread = threading.Thread(target=self._listen_loop, daemon=True)
        thread.start()

    def stop_listening(self):
        self.is_listening = False

    def get_transcription(self) -> str | None:
        try:
            return self.result_queue.get_nowait()
        except queue.Empty:
            return None

    def _listen_loop(self):
        if not self._init_audio():
            print("[Voice] Voice disabled — text only mode.")
            self.is_listening = False
            return

        while self.is_listening:
            try:
                audio_data = self._record_speech()
                if audio_data is not None:
                    text = self._transcribe(audio_data)
                    if text and text.strip():
                        self.result_queue.put(text.strip())
            except Exception as e:
                print(f"[Voice] Error: {e}")
                time.sleep(1)

    # ─── Recording with callback stream ─────────────────────────────────

    def _record_speech(self) -> np.ndarray | None:
        """Record using a callback-based stream — no blocking API."""
        import sounddevice as sd

        chunk_ms = 64
        chunk_samples = max(512, int(self._mic_rate * chunk_ms / 1000))
        silence_chunks = int(SILENCE_DURATION * 1000 / chunk_ms)
        min_speech = int(MIN_SPEECH_DURATION * 1000 / chunk_ms)
        max_speech = int(MAX_SPEECH_DURATION * 1000 / chunk_ms)

        # Clear audio queue
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

        # Callback pushes chunks into queue
        def audio_callback(indata, frames, time_info, status):
            self._audio_queue.put(indata.copy())

        try:
            stream = sd.InputStream(
                device=self._mic_device,
                samplerate=self._mic_rate,
                channels=self._mic_channels,
                dtype='int16',
                blocksize=chunk_samples,
                callback=audio_callback,
            )
            stream.start()
        except Exception as e:
            print(f"[Voice] Stream open failed: {e}")
            time.sleep(1)
            return None

        frames = []
        silent_count = 0
        speech_count = 0
        recording = False

        try:
            while self.is_listening:
                try:
                    data = self._audio_queue.get(timeout=0.5)
                except queue.Empty:
                    continue

                # Mix to mono
                if self._mic_channels > 1:
                    audio = data.mean(axis=1).astype(np.int16)
                else:
                    audio = data.flatten()

                amplitude = np.abs(audio).mean()

                if amplitude > SILENCE_THRESHOLD:
                    if not recording:
                        recording = True
                        self.is_recording = True
                    silent_count = 0
                    speech_count += 1
                    frames.append(audio)
                elif recording:
                    silent_count += 1
                    frames.append(audio)
                    if silent_count > silence_chunks:
                        break

                if recording and speech_count > max_speech:
                    break

                if not recording:
                    time.sleep(0.003)
        finally:
            stream.stop()
            stream.close()
            self.is_recording = False

        if speech_count < min_speech:
            return None

        audio_np = np.concatenate(frames).astype(np.float32) / 32768.0

        # Resample to 16kHz for Whisper
        if self._mic_rate != TARGET_RATE:
            duration = len(audio_np) / self._mic_rate
            target_len = int(duration * TARGET_RATE)
            if target_len > 0 and len(audio_np) > 0:
                indices = np.linspace(0, len(audio_np) - 1, target_len)
                audio_np = np.interp(
                    indices, np.arange(len(audio_np)), audio_np
                ).astype(np.float32)

        return audio_np

    # ─── Transcription ──────────────────────────────────────────────────

    def _transcribe(self, audio_data: np.ndarray) -> str:
        if self.model is None:
            return ""
        try:
            segments, info = self.model.transcribe(
                audio_data,
                beam_size=1,
                language="en",
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
            )
            return " ".join(s.text for s in segments).strip()
        except Exception as e:
            print(f"[Voice] Transcription error: {e}")
            return ""

    def cleanup(self):
        self.is_listening = False
