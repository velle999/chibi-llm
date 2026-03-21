"""
Vision Module — Gives Chibi eyes via a PS3 Eye webcam.

Captures frames from the webcam, encodes them as base64,
and sends them to a multimodal LLM (llava/moondream/bakllava)
for scene understanding.

Modes:
  - On-demand: User says "what do you see" / "look" / "describe"
  - Periodic awareness: Sends a frame every N seconds for passive context
  - Motion detection: Notices when something changes

PS3 Eye works out of the box on Linux (ov534/gspca driver).

Install:
    pip install opencv-python-headless --break-system-packages
    # or for full OpenCV with GUI (not needed for headless Pi):
    # pip install opencv-python --break-system-packages
"""

import base64
import io
import json
import math
import threading
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    print("[Vision] opencv not installed! Run: pip install opencv-python-headless --break-system-packages")

try:
    import numpy as np
    NP_AVAILABLE = True
except ImportError:
    NP_AVAILABLE = False


@dataclass
class VisionResult:
    description: str = ""
    timestamp: str = ""
    motion_detected: bool = False
    people_detected: bool = False
    raw_frame: bytes = b""  # JPEG bytes for display


class Vision:
    def __init__(self, config):
        self.config = config
        self._cap = None
        self._running = False
        self._lock = threading.Lock()

        # State
        self.last_frame: bytes = b""           # Latest JPEG frame
        self.last_description: str = ""         # Latest scene description
        self.last_capture_time: float = 0
        self.motion_detected: bool = False
        self._prev_gray = None                  # For motion detection

        # Results queue (non-blocking reads from main thread)
        self._description_ready = False

        if not CV2_AVAILABLE:
            print("[Vision] OpenCV not available, vision disabled.")
            return

        self._init_camera()

    def _init_camera(self):
        """Initialize the webcam. PS3 Eye is usually /dev/video0."""
        try:
            # Try device index 0 first
            self._cap = cv2.VideoCapture(self.config.camera_device)
            if not self._cap.isOpened():
                print(f"[Vision] Failed to open camera device {self.config.camera_device}")
                self._cap = None
                return

            # PS3 Eye supports 640x480@60fps or 320x240@120fps
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.camera_width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.camera_height)
            self._cap.set(cv2.CAP_PROP_FPS, self.config.camera_fps)

            # Read a test frame
            ret, frame = self._cap.read()
            if ret:
                h, w = frame.shape[:2]
                print(f"[Vision] Camera ready: {w}x{h}")
            else:
                print("[Vision] Camera opened but can't read frames")
                self._cap.release()
                self._cap = None

        except Exception as e:
            print(f"[Vision] Camera init error: {e}")
            self._cap = None

    @property
    def available(self) -> bool:
        return self._cap is not None and CV2_AVAILABLE

    @property
    def has_new_description(self) -> bool:
        return self._description_ready

    def get_description(self) -> str:
        """Get latest description and clear the ready flag."""
        self._description_ready = False
        return self.last_description

    def capture_frame(self) -> bytes | None:
        """Capture a single frame, return as JPEG bytes."""
        if not self.available:
            return None

        with self._lock:
            ret, frame = self._cap.read()
            if not ret:
                return None

            # Resize for LLM (smaller = faster, less tokens)
            h, w = frame.shape[:2]
            target_w = self.config.vision_resize_width
            if w > target_w:
                scale = target_w / w
                frame = cv2.resize(frame, (target_w, int(h * scale)))

            # Motion detection
            self._check_motion(frame)

            # Encode to JPEG
            _, jpeg = cv2.imencode('.jpg', frame,
                                    [cv2.IMWRITE_JPEG_QUALITY, self.config.vision_jpeg_quality])
            jpeg_bytes = jpeg.tobytes()
            self.last_frame = jpeg_bytes
            self.last_capture_time = time.time()
            return jpeg_bytes

    def _check_motion(self, frame):
        """Simple motion detection via frame differencing."""
        if not NP_AVAILABLE:
            return

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self._prev_gray is None:
            self._prev_gray = gray
            return

        delta = cv2.absdiff(self._prev_gray, gray)
        thresh = cv2.threshold(delta, 30, 255, cv2.THRESH_BINARY)[1]
        motion_amount = thresh.sum() / 255  # Number of changed pixels

        # Threshold for "significant motion"
        total_pixels = gray.shape[0] * gray.shape[1]
        motion_pct = motion_amount / total_pixels

        self.motion_detected = motion_pct > self.config.vision_motion_threshold
        self._prev_gray = gray

    def describe_scene(self, extra_context: str = "") -> str:
        """
        Capture a frame and send to multimodal LLM for description.
        Blocks until response is received. Call from a thread.
        """
        jpeg_bytes = self.capture_frame()
        if jpeg_bytes is None:
            return "I can't see anything right now — camera might not be connected."

        b64_image = base64.b64encode(jpeg_bytes).decode("utf-8")

        prompt = (
            "Describe what you see in this image briefly (1-2 sentences). "
            "Focus on: people present, what they're doing, notable objects, "
            "lighting/mood. Be conversational, not clinical."
        )
        if extra_context:
            prompt += f"\nContext: {extra_context}"

        return self._query_vision_llm(b64_image, prompt)

    def analyze_for_context(self) -> str:
        """
        Quick periodic capture for passive awareness.
        Returns a short context string, not a full description.
        """
        jpeg_bytes = self.capture_frame()
        if jpeg_bytes is None:
            return ""

        b64_image = base64.b64encode(jpeg_bytes).decode("utf-8")

        prompt = (
            "In 10 words or less, note: who's visible, what they're doing, "
            "general scene. Example: 'Velle at desk typing, lamp on, night time'. "
            "If nothing notable, just say 'nothing notable'."
        )

        result = self._query_vision_llm(b64_image, prompt)
        return result if result != "nothing notable" else ""

    def _query_vision_llm(self, b64_image: str, prompt: str) -> str:
        """Send image + prompt to Ollama multimodal model."""
        url = f"http://{self.config.llm_host}:{self.config.llm_port}/api/chat"

        payload = json.dumps({
            "model": self.config.vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [b64_image],
                }
            ],
            "stream": False,
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
                return data.get("message", {}).get("content", "").strip()
        except urllib.error.URLError as e:
            print(f"[Vision] LLM query failed: {e}")
            return "I had trouble processing what I see."
        except Exception as e:
            print(f"[Vision] Error: {e}")
            return ""

    def start_awareness(self):
        """Start background thread for periodic scene awareness."""
        if not self.available:
            return
        self._running = True
        t = threading.Thread(target=self._awareness_loop, daemon=True)
        t.start()

    def _awareness_loop(self):
        """Periodically capture and analyze the scene for passive context."""
        while self._running:
            try:
                time.sleep(self.config.vision_awareness_interval)
                if not self._running:
                    break

                context = self.analyze_for_context()
                if context:
                    self.last_description = context
                    self._description_ready = True
                    print(f"[Vision] Scene: {context}")

            except Exception as e:
                print(f"[Vision] Awareness error: {e}")
                time.sleep(5)

    def stop(self):
        """Stop vision and release camera."""
        self._running = False
        if self._cap:
            self._cap.release()
            self._cap = None

    def get_frame_for_display(self) -> bytes:
        """Get latest frame as JPEG for optional PiP display."""
        return self.last_frame


# ─── Vision Trigger Detection ────────────────────────────────────────────────

# Keywords that should trigger a vision capture and description
VISION_TRIGGERS = [
    "what do you see", "what can you see", "look at", "look around",
    "see me", "see anything", "what's in front", "who's there",
    "describe what", "show me", "take a look", "check the camera",
    "what's happening", "what am i doing", "how do i look",
    "what's around", "look at me", "can you see", "watch",
    "what's on my", "read this", "what does this",
]


def is_vision_request(text: str) -> bool:
    """Check if user message is asking Chibi to look/see something."""
    lower = text.lower().strip()
    return any(trigger in lower for trigger in VISION_TRIGGERS)
