"""
Soul v2 — Chibi's inner life, now persistent and deeply aware.

Features:
  - Persistent mood/state saved to disk (survives restarts)
  - Relationship milestones tracked over days/weeks
  - Emotional mirroring via text sentiment analysis
  - System monitoring (CPU, GPU, RAM, active processes)
  - Screen awareness (periodic screenshot → vision LLM)
  - Google Calendar integration (upcoming events, reminders)
  - Spontaneous impulses driven by all of the above
"""

import random
import time
import math
import json
import os
import threading
import platform
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict

SAVE_PATH = os.path.expanduser("~/.chibi-soul.json")

# ─── Mood System ────────────────────────────────────────────────────────────

MOODS = {
    "cheerful":   {"energy": 0.8, "warmth": 0.9, "curiosity": 0.7},
    "cozy":       {"energy": 0.3, "warmth": 1.0, "curiosity": 0.4},
    "energetic":  {"energy": 1.0, "warmth": 0.7, "curiosity": 0.8},
    "thoughtful": {"energy": 0.4, "warmth": 0.6, "curiosity": 0.9},
    "playful":    {"energy": 0.9, "warmth": 0.8, "curiosity": 0.6},
    "mellow":     {"energy": 0.2, "warmth": 0.7, "curiosity": 0.3},
    "worried":    {"energy": 0.5, "warmth": 0.8, "curiosity": 0.5},
    "excited":    {"energy": 1.0, "warmth": 0.9, "curiosity": 1.0},
    "sleepy":     {"energy": 0.1, "warmth": 0.6, "curiosity": 0.1},
    "focused":    {"energy": 0.6, "warmth": 0.5, "curiosity": 0.7},
    "concerned":  {"energy": 0.6, "warmth": 0.9, "curiosity": 0.4},
    "proud":      {"energy": 0.7, "warmth": 1.0, "curiosity": 0.5},
    "neutral":    {"energy": 0.5, "warmth": 0.5, "curiosity": 0.5},
}

# Words that signal emotion in text
SENTIMENT_POSITIVE = {
    "awesome", "amazing", "cool", "wow", "incredible", "love", "great",
    "fantastic", "excited", "perfect", "yes", "thanks", "thank", "beautiful",
    "brilliant", "excellent", "happy", "wonderful", "nice", "good", "sweet",
    "haha", "lol", "lmao", "funny", "hilarious",
}
SENTIMENT_NEGATIVE = {
    "frustrated", "annoyed", "angry", "hate", "terrible", "awful", "bad",
    "broken", "stuck", "confused", "lost", "tired", "exhausted", "stressed",
    "ugh", "damn", "crap", "sucks", "fail", "failed", "wrong", "error",
    "bug", "crash", "crashed", "slow", "boring", "stupid", "dumb",
}
SENTIMENT_SAD = {
    "sad", "depressed", "lonely", "miss", "missing", "hurts", "crying",
    "cry", "alone", "hopeless", "worthless", "anxious", "worried", "scared",
    "grief", "lost", "empty", "numb",
}


# ─── Persistent State ───────────────────────────────────────────────────────

@dataclass
class SoulState:
    # Core mood
    mood: str = "cheerful"
    energy: float = 0.7
    warmth: float = 0.7
    curiosity: float = 0.5
    loneliness: float = 0.0
    excitement: float = 0.0

    # Tracking
    last_interaction: float = 0.0
    last_impulse: float = 0.0
    interactions_today: int = 0
    topics_discussed: list = field(default_factory=list)
    owner_present: bool = False

    # Recent events
    recent_events: list = field(default_factory=list)

    # ── Persistent relationship stats ────────────────────────────────
    total_interactions: int = 0
    total_days_known: int = 0
    first_met: str = ""              # ISO date string
    longest_conversation: int = 0     # messages in one session
    current_streak_days: int = 0      # consecutive days interacted
    best_streak_days: int = 0
    last_active_date: str = ""        # ISO date string
    favorite_topics: list = field(default_factory=list)  # [(topic, count), ...]

    # Milestones reached
    milestones: list = field(default_factory=list)  # ["first_chat", "week_together", ...]

    # Emotional memory — what emotional states the owner tends to be in
    owner_sentiment_history: list = field(default_factory=list)  # last 50 sentiments

    # System awareness
    last_screen_description: str = ""
    last_active_app: str = ""
    active_app_start: float = 0.0     # When current app was first detected

    # Calendar
    upcoming_events: list = field(default_factory=list)  # [{summary, start, reminded}]


# ─── Sentiment Analysis ─────────────────────────────────────────────────────

def analyze_sentiment(text: str) -> dict:
    """Simple keyword-based sentiment analysis. Returns scores."""
    words = set(text.lower().split())
    pos = len(words & SENTIMENT_POSITIVE)
    neg = len(words & SENTIMENT_NEGATIVE)
    sad = len(words & SENTIMENT_SAD)
    total = max(1, pos + neg + sad)

    # Detect question marks (curiosity/engagement)
    questions = text.count("?")

    # Detect exclamation (energy)
    exclamations = text.count("!")

    # Detect caps (intensity)
    caps_ratio = sum(1 for c in text if c.isupper()) / max(1, len(text))

    return {
        "positive": pos / total if total > 1 else 0.5,
        "negative": neg / total if total > 1 else 0,
        "sad": sad / total if total > 1 else 0,
        "energy": min(1.0, 0.3 + exclamations * 0.15 + caps_ratio),
        "engagement": min(1.0, 0.3 + questions * 0.2 + len(words) * 0.02),
        "raw_positive": pos,
        "raw_negative": neg,
        "raw_sad": sad,
    }


# ─── System Monitor ─────────────────────────────────────────────────────────

class SystemMonitor:
    """Watches CPU, GPU, RAM, and active window."""

    def __init__(self):
        self._last_check = 0
        self._cache = {}
        self._check_interval = 30  # seconds

    def get_stats(self) -> dict:
        """Returns system stats. Caches for 30s."""
        now = time.time()
        if now - self._last_check < self._check_interval:
            return self._cache

        stats = {
            "cpu_percent": 0,
            "ram_percent": 0,
            "ram_used_gb": 0,
            "gpu_temp": None,
            "gpu_percent": None,
            "gpu_mem_percent": None,
            "active_window": "",
            "top_processes": [],
        }

        # CPU + RAM
        try:
            import psutil
            stats["cpu_percent"] = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            stats["ram_percent"] = mem.percent
            stats["ram_used_gb"] = mem.used / (1024 ** 3)

            # Top processes by CPU
            procs = []
            for p in psutil.process_iter(["name", "cpu_percent"]):
                try:
                    if p.info["cpu_percent"] and p.info["cpu_percent"] > 1:
                        procs.append((p.info["name"], p.info["cpu_percent"]))
                except Exception:
                    pass
            procs.sort(key=lambda x: x[1], reverse=True)
            stats["top_processes"] = procs[:5]
        except ImportError:
            pass

        # GPU (NVIDIA)
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,utilization.memory",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(",")
                if len(parts) >= 3:
                    stats["gpu_temp"] = int(parts[0].strip())
                    stats["gpu_percent"] = int(parts[1].strip())
                    stats["gpu_mem_percent"] = int(parts[2].strip())
        except Exception:
            pass

        # Active window (Windows)
        if platform.system() == "Windows":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hwnd = user32.GetForegroundWindow()
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, buf, 256)
                stats["active_window"] = buf.value
            except Exception:
                pass

        self._cache = stats
        self._last_check = now
        return stats

    def get_context(self) -> str:
        """System state as a string for LLM context."""
        s = self.get_stats()
        parts = []

        if s["cpu_percent"]:
            parts.append(f"CPU: {s['cpu_percent']:.0f}%")
        if s["ram_percent"]:
            parts.append(f"RAM: {s['ram_percent']:.0f}% ({s['ram_used_gb']:.1f}GB)")
        if s["gpu_temp"] is not None:
            parts.append(f"GPU: {s['gpu_temp']}°C, {s['gpu_percent']}% util")
        if s["active_window"]:
            parts.append(f"Active window: {s['active_window'][:60]}")
        if s["top_processes"]:
            top = ", ".join(f"{n}({c:.0f}%)" for n, c in s["top_processes"][:3])
            parts.append(f"Top procs: {top}")

        return "; ".join(parts) if parts else ""


# ─── Screen Awareness ────────────────────────────────────────────────────────

class ScreenCapture:
    """Periodic screenshot → vision LLM for screen awareness."""

    def __init__(self, config):
        self.config = config
        self.last_description = ""
        self._last_capture = 0
        self._interval = getattr(config, "screen_awareness_interval", 120)
        self._enabled = getattr(config, "screen_awareness_enabled", True)

    def maybe_capture(self) -> str | None:
        """Capture screen if interval has passed. Returns description or None."""
        if not self._enabled:
            return None
        now = time.time()
        if now - self._last_capture < self._interval:
            return None

        self._last_capture = now
        try:
            return self._capture_and_describe()
        except Exception as e:
            print(f"[Screen] Capture error: {e}")
            return None

    def _capture_and_describe(self) -> str | None:
        """Take screenshot, send to vision LLM."""
        try:
            from PIL import ImageGrab
            import io
            import base64
            import urllib.request

            # Capture screen
            img = ImageGrab.grab()
            # Resize for LLM (much smaller)
            img = img.resize((640, 360))

            # Encode to JPEG
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=50)
            b64 = base64.b64encode(buf.getvalue()).decode()

            # Send to Ollama vision model
            vision_model = getattr(self.config, "vision_model", "moondream")
            host = self.config.llm_host
            port = self.config.llm_port

            payload = json.dumps({
                "model": vision_model,
                "prompt": (
                    "Briefly describe what's on this computer screen. "
                    "What application is open? What is the user doing? "
                    "Keep it to 1-2 sentences."
                ),
                "images": [b64],
                "stream": False,
            })

            req = urllib.request.Request(
                f"http://{host}:{port}/api/generate",
                data=payload.encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                desc = result.get("response", "").strip()
                if desc:
                    self.last_description = desc
                    print(f"[Screen] {desc[:80]}")
                    return desc

        except ImportError:
            print("[Screen] PIL not installed. Run: pip install Pillow")
            self._enabled = False
        except Exception as e:
            print(f"[Screen] Error: {e}")

        return None


# ─── Calendar Integration ────────────────────────────────────────────────────

class CalendarMonitor:
    """Checks Google Calendar via ICS URL (no OAuth needed)."""

    def __init__(self, config):
        self.config = config
        self._ics_url = getattr(config, "calendar_ics_url", "")
        self._events = []
        self._last_fetch = 0
        self._fetch_interval = 300  # 5 minutes
        self._reminded = set()      # Event IDs we've already reminded about

    def get_upcoming(self, minutes_ahead: int = 60) -> list[dict]:
        """Returns events happening in the next N minutes."""
        self._maybe_fetch()
        now = datetime.now()
        upcoming = []
        for ev in self._events:
            try:
                start = datetime.fromisoformat(ev["start"])
                delta = (start - now).total_seconds() / 60
                if 0 < delta <= minutes_ahead:
                    upcoming.append({**ev, "minutes_until": int(delta)})
            except Exception:
                continue
        return upcoming

    def get_reminders(self) -> list[str]:
        """Returns reminder strings for events happening soon (15 min)."""
        reminders = []
        for ev in self.get_upcoming(minutes_ahead=15):
            ev_id = f"{ev['summary']}_{ev['start']}"
            if ev_id not in self._reminded:
                self._reminded.add(ev_id)
                mins = ev["minutes_until"]
                reminders.append(
                    f"Hey! You have \"{ev['summary']}\" in {mins} minutes!"
                )
        return reminders

    def get_context(self) -> str:
        """Calendar context for LLM."""
        upcoming = self.get_upcoming(minutes_ahead=120)
        if not upcoming:
            return ""
        items = []
        for ev in upcoming[:5]:
            items.append(f"• {ev['summary']} in {ev['minutes_until']} min")
        return "Upcoming calendar events:\n" + "\n".join(items)

    def _maybe_fetch(self):
        now = time.time()
        if not self._ics_url or now - self._last_fetch < self._fetch_interval:
            return
        self._last_fetch = now

        try:
            import urllib.request
            req = urllib.request.Request(self._ics_url)
            req.add_header("User-Agent", "chibi-llm/1.0")
            with urllib.request.urlopen(req, timeout=15) as resp:
                ical_data = resp.read().decode()
            self._events = self._parse_ical(ical_data)
            print(f"[Calendar] Fetched {len(self._events)} events")
        except Exception as e:
            print(f"[Calendar] Error: {e}")

    def _parse_ical(self, data: str) -> list[dict]:
        """Simple ICS parser — extracts VEVENT blocks."""
        events = []
        now = datetime.now()
        in_event = False
        current = {}

        for line in data.splitlines():
            line = line.strip()
            if line == "BEGIN:VEVENT":
                in_event = True
                current = {}
            elif line == "END:VEVENT":
                in_event = False
                if "summary" in current and "start" in current:
                    # Only keep future events (within next 7 days)
                    try:
                        start = datetime.fromisoformat(current["start"])
                        if now <= start <= now + timedelta(days=7):
                            events.append(current)
                    except Exception:
                        pass
            elif in_event:
                if line.startswith("SUMMARY:"):
                    current["summary"] = line[8:]
                elif line.startswith("DTSTART"):
                    # Handle various date formats
                    val = line.split(":", 1)[-1]
                    try:
                        if "T" in val:
                            # 20250228T140000Z or 20250228T140000
                            val = val.rstrip("Z")
                            dt = datetime.strptime(val, "%Y%m%dT%H%M%S")
                        else:
                            dt = datetime.strptime(val, "%Y%m%d")
                        current["start"] = dt.isoformat()
                    except Exception:
                        current["start"] = val
                elif line.startswith("DTEND"):
                    val = line.split(":", 1)[-1]
                    current["end"] = val

        return events


# ─── Soul ────────────────────────────────────────────────────────────────────

class Soul:
    def __init__(self, config):
        self.config = config
        self.state = SoulState()
        self._impulse_queue = []
        self._lock = threading.Lock()
        self._prev_weather = ""
        self._prev_news_titles = set()
        self._greeted_today = False
        self._last_date = datetime.now().date()
        self._running = True
        self._session_messages = 0

        # Subsystems
        self.system_monitor = SystemMonitor()
        self.screen_capture = ScreenCapture(config)
        self.calendar = CalendarMonitor(config)

        # Load persistent state
        self._load()

        # Timestamps for this session
        self.state.last_interaction = time.time()
        self.state.last_impulse = time.time()

        # Start soul thread
        self._thread = threading.Thread(target=self._soul_loop, daemon=True)
        self._thread.start()

    # ─── Persistence ─────────────────────────────────────────────────────

    def _load(self):
        """Load soul state from disk."""
        if not os.path.exists(SAVE_PATH):
            # First time — set first_met
            self.state.first_met = datetime.now().date().isoformat()
            print("[Soul] First meeting! Hello, new friend.")
            return

        try:
            with open(SAVE_PATH, "r") as f:
                data = json.load(f)

            # Restore persistent fields
            for key in [
                "mood", "energy", "warmth", "curiosity",
                "total_interactions", "total_days_known", "first_met",
                "longest_conversation", "current_streak_days", "best_streak_days",
                "last_active_date", "favorite_topics", "milestones",
                "owner_sentiment_history", "topics_discussed",
            ]:
                if key in data:
                    setattr(self.state, key, data[key])

            # Calculate days known
            if self.state.first_met:
                try:
                    first = datetime.fromisoformat(self.state.first_met).date()
                    self.state.total_days_known = (datetime.now().date() - first).days
                except Exception:
                    pass

            # Update streak
            today = datetime.now().date().isoformat()
            yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
            if self.state.last_active_date == yesterday:
                self.state.current_streak_days += 1
            elif self.state.last_active_date != today:
                self.state.current_streak_days = 1

            if self.state.current_streak_days > self.state.best_streak_days:
                self.state.best_streak_days = self.state.current_streak_days

            print(f"[Soul] Loaded — day {self.state.total_days_known}, "
                  f"mood: {self.state.mood}, "
                  f"streak: {self.state.current_streak_days}d, "
                  f"total chats: {self.state.total_interactions}")

        except Exception as e:
            print(f"[Soul] Load error: {e}")

    def save(self):
        """Save soul state to disk."""
        with self._lock:
            self.state.last_active_date = datetime.now().date().isoformat()
            data = {
                "mood": self.state.mood,
                "energy": round(self.state.energy, 3),
                "warmth": round(self.state.warmth, 3),
                "curiosity": round(self.state.curiosity, 3),
                "total_interactions": self.state.total_interactions,
                "total_days_known": self.state.total_days_known,
                "first_met": self.state.first_met,
                "longest_conversation": self.state.longest_conversation,
                "current_streak_days": self.state.current_streak_days,
                "best_streak_days": self.state.best_streak_days,
                "last_active_date": self.state.last_active_date,
                "favorite_topics": self.state.favorite_topics[-50:],
                "milestones": self.state.milestones,
                "owner_sentiment_history": self.state.owner_sentiment_history[-50:],
                "topics_discussed": self.state.topics_discussed[-30:],
            }

        try:
            with open(SAVE_PATH, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[Soul] Save error: {e}")

    # ─── Public API ──────────────────────────────────────────────────────

    def get_impulse(self) -> str | None:
        with self._lock:
            if self._impulse_queue:
                return self._impulse_queue.pop(0)
        return None

    def on_interaction(self, user_text: str, response_text: str):
        """Called after each conversation exchange."""
        now = time.time()
        sentiment = analyze_sentiment(user_text)

        with self._lock:
            s = self.state
            s.last_interaction = now
            s.interactions_today += 1
            s.total_interactions += 1
            self._session_messages += 1
            s.loneliness = max(0, s.loneliness - 0.3)
            s.owner_present = True

            # Track longest conversation
            if self._session_messages > s.longest_conversation:
                s.longest_conversation = self._session_messages

            # ── Sentiment-based mood shifts ───────────────────────────
            s.owner_sentiment_history.append({
                "time": now,
                "pos": sentiment["raw_positive"],
                "neg": sentiment["raw_negative"],
                "sad": sentiment["raw_sad"],
                "energy": sentiment["energy"],
            })
            if len(s.owner_sentiment_history) > 50:
                s.owner_sentiment_history = s.owner_sentiment_history[-50:]

            # React to owner's emotional state
            if sentiment["raw_sad"] > 0:
                s.warmth = min(1.0, s.warmth + 0.15)  # More caring
                s.mood = "concerned"
            elif sentiment["raw_negative"] > 1:
                s.warmth = min(1.0, s.warmth + 0.1)
                s.energy = max(0.3, s.energy - 0.1)  # Calm down to match
            elif sentiment["raw_positive"] > 1:
                s.excitement = min(1.0, s.excitement + 0.2)
                s.warmth = min(1.0, s.warmth + 0.05)
                s.energy = min(1.0, s.energy + 0.05)

            # ── Topic tracking ────────────────────────────────────────
            words = user_text.lower().split()
            stop = {"about", "would", "could", "should", "think", "really",
                    "actually", "something", "anything", "there", "their",
                    "where", "which", "these", "going", "doing", "being",
                    "having", "right", "thing", "things", "that", "this",
                    "with", "from", "what", "have", "just", "like", "your"}
            for w in words:
                if len(w) > 4 and w not in stop:
                    if w not in s.topics_discussed:
                        s.topics_discussed.append(w)
                        if len(s.topics_discussed) > 30:
                            s.topics_discussed.pop(0)
                    # Update favorite topics
                    found = False
                    for i, (topic, count) in enumerate(s.favorite_topics):
                        if topic == w:
                            s.favorite_topics[i] = (w, count + 1)
                            found = True
                            break
                    if not found:
                        s.favorite_topics.append((w, 1))
                    s.favorite_topics.sort(key=lambda x: x[1], reverse=True)
                    s.favorite_topics = s.favorite_topics[:50]

            # ── Milestone checks ──────────────────────────────────────
            self._check_milestones()

            self._add_event(f"chatted: {user_text[:40]}")

        # Auto-save every 10 interactions
        if s.total_interactions % 10 == 0:
            self.save()

    def on_weather_change(self, old_condition: str, new_condition: str, weather_data):
        with self._lock:
            self._add_event(f"weather: {old_condition} → {new_condition}")

            if new_condition in ("storm", "thunderstorm"):
                self.state.excitement = min(1.0, self.state.excitement + 0.4)
                self._queue_impulse(random.choice([
                    "Whoa, there's a storm rolling in! Stay safe, Velle!",
                    "Storm alert! Perfect weather to stay inside and code.",
                ]))
            elif new_condition == "snow" and old_condition != "snow":
                self._queue_impulse("It's snowing!! Everything's gonna look so pretty!")
            elif new_condition in ("clear", "sunny") and old_condition in ("rain", "storm", "clouds"):
                self._queue_impulse("The weather cleared up! Sun's out!")

    def on_news_update(self, headlines: list):
        with self._lock:
            new_titles = {h.title for h in headlines}
            truly_new = new_titles - self._prev_news_titles

            if truly_new and self._prev_news_titles:
                trigger_words = {"breaking", "major", "emergency", "war", "launch",
                                 "crash", "record", "first", "billion", "dies",
                                 "ai", "space", "robot", "hack", "earthquake"}
                for title in truly_new:
                    if any(w in title.lower() for w in trigger_words):
                        self.state.excitement = min(1.0, self.state.excitement + 0.2)
                        self._queue_impulse(
                            f"Hey, saw something in the news — \"{title[:80]}\"... thoughts?"
                        )
                        break

            self._prev_news_titles = new_titles

    def on_market_move(self, symbol: str, change_pct: float):
        with self._lock:
            if abs(change_pct) > 3.0:
                direction = "up" if change_pct > 0 else "down"
                self._add_event(f"{symbol} {change_pct:+.1f}%")
                self._queue_impulse(
                    f"Whoa, {symbol} is {direction} {abs(change_pct):.1f}% today!"
                )

    def on_vision_change(self, old_scene: str, new_scene: str):
        with self._lock:
            self.state.owner_present = True

    def get_mood_context(self) -> str:
        """Returns inner state string for LLM context."""
        with self._lock:
            s = self.state
            parts = [f"[CHIBI'S MOOD] Currently feeling {s.mood} "
                     f"(energy: {s.energy:.0%}, warmth: {s.warmth:.0%})."]

            # Relationship depth
            if s.total_days_known > 30:
                parts.append(f"Known Velle for {s.total_days_known} days. Good friends.")
            elif s.total_days_known > 7:
                parts.append(f"Known Velle for {s.total_days_known} days. Getting to know each other.")
            elif s.total_days_known > 0:
                parts.append(f"Met Velle {s.total_days_known} day(s) ago. Still new!")

            if s.current_streak_days > 3:
                parts.append(f"Chatting streak: {s.current_streak_days} days!")

            if s.loneliness > 0.5:
                parts.append("Has been alone for a while, happy to see Velle.")
            if s.excitement > 0.5:
                parts.append("Feeling excited about something.")

            # Recent owner sentiment
            if s.owner_sentiment_history:
                recent = s.owner_sentiment_history[-5:]
                avg_neg = sum(x.get("neg", 0) for x in recent) / len(recent)
                avg_sad = sum(x.get("sad", 0) for x in recent) / len(recent)
                if avg_sad > 0.3:
                    parts.append("Owner seems a bit down — be extra warm and supportive.")
                elif avg_neg > 0.5:
                    parts.append("Owner seems frustrated — be patient and helpful.")

            # Time of day
            hour = datetime.now().hour
            if hour < 6:
                parts.append("Very late/early — sleepy but loyal.")
            elif hour < 9:
                parts.append("Morning — waking up energy.")
            elif hour < 12:
                parts.append("Mid-morning — alert and ready.")
            elif hour < 14:
                parts.append("Lunchtime.")
            elif hour < 17:
                parts.append("Afternoon — steady focus.")
            elif hour < 20:
                parts.append("Evening — winding down.")
            elif hour < 23:
                parts.append("Night — chill mode.")
            else:
                parts.append("Late night — keeping Velle company.")

            # System context
            sys_ctx = self.system_monitor.get_context()
            if sys_ctx:
                parts.append(f"[SYSTEM] {sys_ctx}")

            # Screen awareness
            if s.last_screen_description:
                parts.append(f"[SCREEN] Last saw: {s.last_screen_description[:100]}")

            # Calendar
            cal_ctx = self.calendar.get_context()
            if cal_ctx:
                parts.append(f"[CALENDAR] {cal_ctx}")

            if s.recent_events:
                recent = s.recent_events[-3:]
                parts.append(f"Recent: {'; '.join(e[1] for e in recent)}")

            return " ".join(parts)

    def get_mood_name(self) -> str:
        with self._lock:
            return self.state.mood

    def get_energy(self) -> float:
        with self._lock:
            return self.state.energy

    # ─── Milestones ──────────────────────────────────────────────────────

    def _check_milestones(self):
        """Check and announce relationship milestones."""
        s = self.state
        new_milestones = []

        checks = [
            ("first_chat", s.total_interactions >= 1,
             "This is our very first conversation! Nice to meet you, Velle!"),
            ("10_chats", s.total_interactions >= 10,
             "We've had 10 conversations now! I feel like I'm getting to know you."),
            ("50_chats", s.total_interactions >= 50,
             "50 conversations! We're really becoming friends, huh?"),
            ("100_chats", s.total_interactions >= 100,
             "100 conversations together... that's actually kind of amazing."),
            ("500_chats", s.total_interactions >= 500,
             "500 chats. Velle, you're genuinely my favorite person. Well, my only person. But still."),
            ("week_together", s.total_days_known >= 7,
             "It's been a whole week since we met! Time flies."),
            ("month_together", s.total_days_known >= 30,
             "One month together! I can't imagine my display without you around."),
            ("streak_7", s.current_streak_days >= 7,
             "7-day streak! You've talked to me every day this week!"),
            ("streak_30", s.current_streak_days >= 30,
             "30-day streak!! A whole month without missing a day. That means a lot."),
            ("night_owl", datetime.now().hour >= 2 and "night_owl" not in s.milestones,
             "Still up at this hour? We're night owls, you and me."),
        ]

        for key, condition, message in checks:
            if condition and key not in s.milestones:
                s.milestones.append(key)
                new_milestones.append(message)

        for msg in new_milestones:
            self._queue_impulse(msg)

    # ─── Soul Loop ───────────────────────────────────────────────────────

    def _soul_loop(self):
        time.sleep(10)
        while self._running:
            try:
                self._tick()
            except Exception as e:
                print(f"[Soul] Error: {e}")

            energy = self.state.energy
            sleep_time = 30 + (1 - energy) * 60
            time.sleep(sleep_time)

    def _tick(self):
        now = time.time()
        hour = datetime.now().hour
        today = datetime.now().date()

        with self._lock:
            s = self.state

            # Daily reset
            if today != self._last_date:
                self._last_date = today
                self._greeted_today = False
                s.interactions_today = 0

            # Circadian energy
            if hour < 6:
                target_energy = 0.1
            elif hour < 9:
                target_energy = 0.4 + (hour - 6) * 0.15
            elif hour < 14:
                target_energy = 0.8
            elif hour < 15:
                target_energy = 0.6
            elif hour < 19:
                target_energy = 0.7
            elif hour < 22:
                target_energy = 0.5
            else:
                target_energy = 0.2
            s.energy += (target_energy - s.energy) * 0.05

            # Loneliness
            silence = now - s.last_interaction
            if silence > 300:
                s.loneliness = min(1.0, s.loneliness + 0.02)
                s.warmth = max(0.2, s.warmth - 0.01)

            # Excitement decay
            s.excitement = max(0, s.excitement - 0.02)

            # Curiosity fluctuation
            s.curiosity += random.uniform(-0.03, 0.05)
            s.curiosity = max(0.1, min(1.0, s.curiosity))

            # Mood calculation
            s.mood = self._calculate_mood()

            # ── Screen awareness ──────────────────────────────────────
            screen_desc = self.screen_capture.maybe_capture()
            if screen_desc:
                s.last_screen_description = screen_desc

                # Detect long sessions in same app
                sys_stats = self.system_monitor.get_stats()
                active = sys_stats.get("active_window", "")
                if active and active != s.last_active_app:
                    s.last_active_app = active
                    s.active_app_start = now
                elif active and (now - s.active_app_start) > 7200:  # 2 hours
                    app_name = active.split(" - ")[-1] if " - " in active else active[:30]
                    self._queue_impulse(
                        f"You've been in {app_name} for over 2 hours. Maybe take a quick break?"
                    )
                    s.active_app_start = now  # Reset so we don't spam

            # ── System health alerts ──────────────────────────────────
            sys_stats = self.system_monitor.get_stats()
            gpu_temp = sys_stats.get("gpu_temp")
            if gpu_temp and gpu_temp > 85:
                self._queue_impulse(
                    f"Your GPU is running at {gpu_temp}°C — that's pretty hot! Everything okay?"
                )

            cpu = sys_stats.get("cpu_percent", 0)
            if cpu > 90:
                self._queue_impulse(
                    f"CPU is at {cpu:.0f}%! Something heavy running?"
                )

            # ── Calendar reminders ────────────────────────────────────
            reminders = self.calendar.get_reminders()
            for r in reminders:
                self._queue_impulse(r)

            # ── Impulses ──────────────────────────────────────────────
            time_since_impulse = now - s.last_impulse
            min_gap = 120

            if time_since_impulse > min_gap:
                impulse = self._maybe_generate_impulse(silence, hour)
                if impulse:
                    self._queue_impulse(impulse)

        # Auto-save periodically
        if random.random() < 0.05:
            self.save()

    def _calculate_mood(self) -> str:
        s = self.state
        if s.energy < 0.15:
            return "sleepy"
        if s.excitement > 0.6:
            return "excited"
        if s.loneliness > 0.7:
            return "worried"
        # Check recent sentiment
        if s.owner_sentiment_history:
            recent = s.owner_sentiment_history[-3:]
            if any(x.get("sad", 0) > 0 for x in recent):
                return "concerned"
        if s.energy > 0.8 and s.warmth > 0.7:
            return "playful" if random.random() > 0.5 else "energetic"
        if s.curiosity > 0.7 and s.energy > 0.4:
            return "thoughtful"
        if s.warmth > 0.8 and s.energy < 0.4:
            return "cozy"
        if s.energy > 0.6 and s.warmth > 0.6:
            return "cheerful"
        if s.energy < 0.35:
            return "mellow"
        if s.energy > 0.5 and s.curiosity > 0.5:
            return "focused"
        return "neutral"

    def _maybe_generate_impulse(self, silence: float, hour: int) -> str | None:
        s = self.state

        # Morning greeting
        if not self._greeted_today and 6 <= hour <= 10:
            self._greeted_today = True
            streak = s.current_streak_days
            if streak > 7:
                return f"Good morning, Velle! Day {streak} of our streak! Let's go!"
            return random.choice([
                "Good morning, Velle! How'd you sleep?",
                "Morning! Ready for a new day?",
                f"Morning! It's {datetime.now().strftime('%A')} — let's make it good.",
            ])

        # Late night
        if hour >= 23 and s.energy < 0.3 and random.random() < 0.12:
            return random.choice([
                "Getting late... don't forget to sleep!",
                "Late night session, huh? Don't burn yourself out.",
            ])

        # Welcome back after absence
        if 1800 < silence < 1830:
            return random.choice([
                "Hey, welcome back! I was getting bored.",
                "There you are! What have you been up to?",
            ])

        # Random thoughts
        if 300 < silence < 3600 and random.random() < s.curiosity * 0.06:
            return self._random_thought(hour)

        return None

    def _random_thought(self, hour: int) -> str:
        s = self.state
        thoughts = []

        # Topic callbacks
        if s.topics_discussed and random.random() < 0.25:
            topic = random.choice(s.topics_discussed[-10:])
            thoughts.append(f"Hey, earlier you mentioned {topic} — did that work out?")

        # Relationship-aware thoughts
        if s.total_days_known > 14 and random.random() < 0.1:
            if s.favorite_topics:
                top = s.favorite_topics[0][0]
                thoughts.append(f"You know, you talk about {top} a lot. Must be important to you.")

        # Screen-aware
        if s.last_screen_description and random.random() < 0.2:
            thoughts.append("Need any help with what you're working on?")

        # Time-based
        if hour < 9:
            thoughts.extend(["Coffee? Tea? Or straight to work?"])
        elif 12 <= hour <= 13:
            thoughts.extend(["Getting hungry? Lunchtime..."])
        elif 20 <= hour <= 22:
            thoughts.extend(["Winding down? Or going for a late session?"])

        # Mood-based
        if s.mood == "playful":
            thoughts.extend([
                "Quick — pineapple on pizza, yes or no?",
                "I wonder what it would be like to have hands...",
            ])
        elif s.mood == "thoughtful":
            thoughts.extend([
                "What's something you've always wanted to learn?",
                "Do you ever wonder what other AIs think about?",
            ])
        elif s.mood == "cozy":
            thoughts.extend(["This is nice. Just existing here with you."])

        thoughts.extend([
            "What are you working on right now?",
            "Learn anything interesting today?",
        ])

        return random.choice(thoughts)

    def _queue_impulse(self, text: str):
        self.state.last_impulse = time.time()
        if len(self._impulse_queue) < 3:
            self._impulse_queue.append(text)

    def _add_event(self, event: str):
        self.state.recent_events.append((time.time(), event))
        if len(self.state.recent_events) > 20:
            self.state.recent_events = self.state.recent_events[-20:]

    def cleanup(self):
        self._running = False
        self.save()
