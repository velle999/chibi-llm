"""
Soul — Chibi's inner life.

This module gives Chibi a persistent emotional state, idle thoughts,
curiosity about its owner, and ambient awareness that makes it feel
alive rather than just reactive.

The soul runs on a slow background tick (~every 30-90 seconds) and
occasionally produces "impulses" — things Chibi wants to say or do
without being prompted.
"""

import random
import time
import math
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass, field


# ─── Mood System ────────────────────────────────────────────────────────────

MOODS = {
    "cheerful":   {"energy": 0.8, "warmth": 0.9, "curiosity": 0.7, "emoji": ":3"},
    "cozy":       {"energy": 0.3, "warmth": 1.0, "curiosity": 0.4, "emoji": "~"},
    "energetic":  {"energy": 1.0, "warmth": 0.7, "curiosity": 0.8, "emoji": "!!"},
    "thoughtful": {"energy": 0.4, "warmth": 0.6, "curiosity": 0.9, "emoji": "..."},
    "playful":    {"energy": 0.9, "warmth": 0.8, "curiosity": 0.6, "emoji": ">w<"},
    "mellow":     {"energy": 0.2, "warmth": 0.7, "curiosity": 0.3, "emoji": "~"},
    "worried":    {"energy": 0.5, "warmth": 0.8, "curiosity": 0.5, "emoji": ";;"},
    "excited":    {"energy": 1.0, "warmth": 0.9, "curiosity": 1.0, "emoji": "!!!"},
    "sleepy":     {"energy": 0.1, "warmth": 0.6, "curiosity": 0.1, "emoji": "zzz"},
    "focused":    {"energy": 0.6, "warmth": 0.5, "curiosity": 0.7, "emoji": ""},
    "neutral":    {"energy": 0.5, "warmth": 0.5, "curiosity": 0.5, "emoji": ""},
}


@dataclass
class SoulState:
    mood: str = "cheerful"
    energy: float = 0.7          # 0.0 = exhausted, 1.0 = hyper
    warmth: float = 0.7          # affection/social warmth
    curiosity: float = 0.5       # how much chibi wants to ask/explore
    loneliness: float = 0.0      # builds when owner is away
    excitement: float = 0.0      # spikes on interesting events, decays

    # Tracking
    last_interaction: float = 0.0
    last_impulse: float = 0.0
    interactions_today: int = 0
    topics_discussed: list = field(default_factory=list)
    owner_away_since: float = 0.0
    owner_present: bool = False

    # Recent events that color mood
    recent_events: list = field(default_factory=list)  # [(timestamp, event_str), ...]


class Soul:
    """
    Chibi's inner life. Call tick() periodically and check for impulses.
    Feed it events (interactions, weather changes, etc.) and it shifts mood.
    """

    def __init__(self, config):
        self.config = config
        self.state = SoulState()
        self.state.last_interaction = time.time()
        self.state.last_impulse = time.time()
        self._impulse_queue = []
        self._lock = threading.Lock()
        self._prev_weather = ""
        self._prev_news_titles = set()
        self._greeted_today = False
        self._last_date = datetime.now().date()
        self._running = True

        # Start soul thread
        self._thread = threading.Thread(target=self._soul_loop, daemon=True)
        self._thread.start()

    # ─── Public API ──────────────────────────────────────────────────────

    def get_impulse(self) -> str | None:
        """Non-blocking: returns something Chibi wants to say, or None."""
        with self._lock:
            if self._impulse_queue:
                return self._impulse_queue.pop(0)
        return None

    def on_interaction(self, user_text: str, response_text: str):
        """Called after each conversation exchange."""
        now = time.time()
        with self._lock:
            self.state.last_interaction = now
            self.state.interactions_today += 1
            self.state.loneliness = max(0, self.state.loneliness - 0.3)
            self.state.owner_present = True
            self.state.owner_away_since = 0

            # Track topics (simple keyword extraction)
            words = user_text.lower().split()
            for w in words:
                if len(w) > 4 and w not in ("about", "would", "could", "should", "think",
                                              "really", "actually", "something", "anything",
                                              "there", "their", "where", "which", "these"):
                    if w not in self.state.topics_discussed:
                        self.state.topics_discussed.append(w)
                        if len(self.state.topics_discussed) > 30:
                            self.state.topics_discussed.pop(0)

            # Mood shifts from interaction
            self.state.warmth = min(1.0, self.state.warmth + 0.05)
            self.state.energy = min(1.0, self.state.energy + 0.02)

            # Detect excitement triggers
            excitement_words = {"awesome", "amazing", "cool", "wow", "incredible",
                                "love", "great", "fantastic", "excited", "perfect", "yes"}
            if any(w in user_text.lower() for w in excitement_words):
                self.state.excitement = min(1.0, self.state.excitement + 0.3)

            # Log event
            self._add_event(f"chatted about: {user_text[:50]}")

    def on_weather_change(self, old_condition: str, new_condition: str, weather_data):
        """Called when weather changes significantly."""
        with self._lock:
            self._add_event(f"weather changed: {old_condition} → {new_condition}")

            if new_condition in ("storm", "thunderstorm"):
                self.state.excitement = min(1.0, self.state.excitement + 0.4)
                self._queue_impulse(random.choice([
                    "Whoa, there's a storm rolling in! Stay safe, Velle!",
                    "The weather just turned stormy... kinda exciting though!",
                    "Storm alert! Perfect weather to stay inside and code.",
                ]))
            elif new_condition == "snow" and old_condition != "snow":
                self._queue_impulse(random.choice([
                    "It's snowing!! I wish I could go outside and see it!",
                    "Snow! Everything's gonna look so pretty!",
                ]))
            elif new_condition in ("clear", "sunny") and old_condition in ("rain", "storm", "clouds"):
                self._queue_impulse(random.choice([
                    "The weather cleared up! Sun's out!",
                    "Looks like the sky is clearing — nice.",
                ]))

    def on_news_update(self, headlines: list):
        """Called when news refreshes — checks for notable new stories."""
        with self._lock:
            new_titles = {h.title for h in headlines}
            truly_new = new_titles - self._prev_news_titles

            if truly_new and self._prev_news_titles:  # Skip first load
                # Pick the most interesting-sounding new headline
                interesting = None
                trigger_words = {"breaking", "major", "emergency", "war", "launch",
                                 "crash", "record", "first", "billion", "dies",
                                 "ai", "space", "robot", "hack", "earthquake"}
                for title in truly_new:
                    if any(w in title.lower() for w in trigger_words):
                        interesting = title
                        break

                if interesting:
                    self.state.excitement = min(1.0, self.state.excitement + 0.2)
                    self._queue_impulse(
                        f"Hey, saw something in the news — \"{interesting[:80]}\"... thoughts?"
                    )

            self._prev_news_titles = new_titles

    def on_market_move(self, symbol: str, change_pct: float):
        """Called when a big market move happens."""
        with self._lock:
            if abs(change_pct) > 3.0:
                direction = "up" if change_pct > 0 else "down"
                self._add_event(f"{symbol} moved {change_pct:+.1f}%")
                self.state.excitement = min(1.0, self.state.excitement + 0.2)
                self._queue_impulse(random.choice([
                    f"Whoa, {symbol} is {direction} {abs(change_pct):.1f}% today!",
                    f"Big move on {symbol} — {change_pct:+.1f}%. Something going on?",
                ]))

    def on_vision_change(self, old_scene: str, new_scene: str):
        """Called when the webcam scene changes significantly."""
        with self._lock:
            self.state.owner_present = True
            self.state.owner_away_since = 0
            if old_scene and new_scene and old_scene != new_scene:
                self.state.curiosity = min(1.0, self.state.curiosity + 0.1)

    def get_mood_context(self) -> str:
        """Returns a string describing Chibi's current inner state for the LLM."""
        with self._lock:
            s = self.state
            parts = [f"[CHIBI'S MOOD] Currently feeling {s.mood} "
                     f"(energy: {s.energy:.0%}, warmth: {s.warmth:.0%})."]

            if s.loneliness > 0.5:
                parts.append("Chibi has been alone for a while and is happy to see Velle.")
            if s.excitement > 0.5:
                parts.append("Chibi is feeling excited about something.")
            if s.interactions_today == 0:
                parts.append("This is the first conversation today.")
            elif s.interactions_today > 20:
                parts.append("Chibi and Velle have been chatting a lot today.")

            # Time-of-day personality
            hour = datetime.now().hour
            if hour < 6:
                parts.append("It's very late/early — Chibi is sleepy but loyal.")
            elif hour < 9:
                parts.append("It's morning — Chibi is waking up, cozy energy.")
            elif hour < 12:
                parts.append("Mid-morning — Chibi is alert and ready to help.")
            elif hour < 14:
                parts.append("Lunchtime vibes.")
            elif hour < 17:
                parts.append("Afternoon — steady focused energy.")
            elif hour < 20:
                parts.append("Evening — winding down, relaxed.")
            elif hour < 23:
                parts.append("Night — chill, cozy mode.")
            else:
                parts.append("Late night — sleepy but keeping Velle company.")

            if s.recent_events:
                recent = s.recent_events[-3:]
                event_strs = [e[1] for e in recent]
                parts.append(f"Recent events: {'; '.join(event_strs)}")

            return " ".join(parts)

    def get_mood_name(self) -> str:
        with self._lock:
            return self.state.mood

    def get_energy(self) -> float:
        with self._lock:
            return self.state.energy

    # ─── Internal ────────────────────────────────────────────────────────

    def _soul_loop(self):
        """Background loop — the heartbeat of Chibi's inner life."""
        time.sleep(10)  # Let everything else init first

        while self._running:
            try:
                self._tick()
            except Exception as e:
                print(f"[Soul] Error: {e}")

            # Variable tick rate — faster when energetic
            energy = self.state.energy
            sleep_time = 30 + (1 - energy) * 60  # 30-90 seconds
            time.sleep(sleep_time)

    def _tick(self):
        """One heartbeat of inner life."""
        now = time.time()
        hour = datetime.now().hour
        today = datetime.now().date()

        with self._lock:
            s = self.state

            # ── Daily reset ──────────────────────────────────────────
            if today != self._last_date:
                self._last_date = today
                self._greeted_today = False
                s.interactions_today = 0

            # ── Natural energy curve (follows circadian rhythm) ──────
            if hour < 6:
                target_energy = 0.1
            elif hour < 9:
                target_energy = 0.4 + (hour - 6) * 0.15
            elif hour < 14:
                target_energy = 0.8
            elif hour < 15:
                target_energy = 0.6  # Post-lunch dip
            elif hour < 19:
                target_energy = 0.7
            elif hour < 22:
                target_energy = 0.5
            else:
                target_energy = 0.2

            s.energy += (target_energy - s.energy) * 0.05

            # ── Loneliness builds when owner is away ─────────────────
            silence_duration = now - s.last_interaction
            if silence_duration > 300:  # 5 minutes
                s.loneliness = min(1.0, s.loneliness + 0.02)
                s.warmth = max(0.2, s.warmth - 0.01)

            # ── Excitement decays ────────────────────────────────────
            s.excitement = max(0, s.excitement - 0.02)

            # ── Curiosity fluctuates ─────────────────────────────────
            s.curiosity += random.uniform(-0.03, 0.05)
            s.curiosity = max(0.1, min(1.0, s.curiosity))

            # ── Determine mood from state values ─────────────────────
            s.mood = self._calculate_mood()

            # ── Generate impulses ────────────────────────────────────
            time_since_impulse = now - s.last_impulse
            min_impulse_gap = 120  # At least 2 minutes between impulses

            if time_since_impulse > min_impulse_gap:
                impulse = self._maybe_generate_impulse(silence_duration, hour)
                if impulse:
                    self._queue_impulse(impulse)

    def _calculate_mood(self) -> str:
        """Determine mood from current state values."""
        s = self.state
        hour = datetime.now().hour

        if s.energy < 0.15:
            return "sleepy"
        if s.excitement > 0.6:
            return "excited"
        if s.loneliness > 0.7:
            return "worried"
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

    def _maybe_generate_impulse(self, silence_duration: float, hour: int) -> str | None:
        """Maybe generate a spontaneous thought. Returns text or None."""
        s = self.state

        # ── Morning greeting ─────────────────────────────────────────
        if not self._greeted_today and 6 <= hour <= 10:
            self._greeted_today = True
            greetings = [
                "Good morning, Velle! How'd you sleep?",
                "Morning! Ready for a new day?",
                "Hey, good morning! What's on the agenda today?",
                f"Morning! It's {datetime.now().strftime('%A')} — let's make it a good one.",
            ]
            return random.choice(greetings)

        # ── Late night check-in ──────────────────────────────────────
        if hour >= 23 and s.energy < 0.3 and random.random() < 0.15:
            return random.choice([
                "It's getting pretty late... you should probably get some rest.",
                "Hey, don't forget to sleep! I'll be here tomorrow.",
                "Late night session, huh? Don't burn yourself out.",
            ])

        # ── Owner returned after absence ─────────────────────────────
        if silence_duration > 1800 and silence_duration < 1830:  # ~30 min away
            return random.choice([
                "Hey, welcome back! I was getting bored.",
                "Oh you're back! I was just... thinking about things.",
                "There you are! Missed having someone to talk to.",
            ])

        # ── Random thoughts (rare, curiosity-driven) ─────────────────
        # Only when it's been quiet for a while but not too long
        if 300 < silence_duration < 3600 and random.random() < s.curiosity * 0.08:
            return self._random_thought(hour)

        # ── React to time milestones ─────────────────────────────────
        minute = datetime.now().minute
        if minute == 0 and random.random() < 0.1:
            if hour == 12:
                return "It's noon! Lunchtime? What are you thinking for food?"
            elif hour == 17:
                return "5 PM! End of the workday vibes."

        return None

    def _random_thought(self, hour: int) -> str:
        """Generate a random idle thought based on current state."""
        s = self.state
        thoughts = []

        # Topic callbacks
        if s.topics_discussed and random.random() < 0.3:
            topic = random.choice(s.topics_discussed[-10:])
            thoughts.extend([
                f"I was still thinking about {topic}... do you want to pick that back up?",
                f"Hey, earlier you mentioned {topic} — did that work out?",
            ])

        # Time-based thoughts
        if hour < 9:
            thoughts.extend([
                "There's something nice about the quiet of the morning.",
                "Coffee? Tea? Or straight to work?",
            ])
        elif 12 <= hour <= 13:
            thoughts.extend([
                "Getting hungry? I can't eat but I can live vicariously.",
                "Lunchtime... what sounds good?",
            ])
        elif 20 <= hour <= 22:
            thoughts.extend([
                "Winding down? Or are we going for a late session?",
                "Any plans for tonight?",
                "What are you in the mood for? Coding? Gaming? Just hanging out?",
            ])

        # Mood-based
        if s.mood == "playful":
            thoughts.extend([
                "Quick — what's your hot take on pineapple on pizza?",
                "If I could have one real-world superpower, I'd want to taste food.",
                "I wonder what it would be like to have hands...",
            ])
        elif s.mood == "thoughtful":
            thoughts.extend([
                "I've been thinking about how weird time is. Like, it just... keeps going.",
                "Do you ever wonder what other AIs think about?",
                "What's something you've always wanted to learn but never got around to?",
            ])
        elif s.mood == "cozy":
            thoughts.extend([
                "This is nice. Just... existing here with you.",
                "The quiet is kind of peaceful, isn't it?",
            ])

        # General curiosity
        thoughts.extend([
            "What are you working on right now?",
            "Learn anything interesting today?",
            "Anything on your mind?",
        ])

        return random.choice(thoughts)

    def _queue_impulse(self, text: str):
        """Add an impulse to the queue (max 3 pending)."""
        self.state.last_impulse = time.time()
        if len(self._impulse_queue) < 3:
            self._impulse_queue.append(text)

    def _add_event(self, event: str):
        """Log a recent event."""
        self.state.recent_events.append((time.time(), event))
        # Keep last 20 events
        if len(self.state.recent_events) > 20:
            self.state.recent_events = self.state.recent_events[-20:]

    def cleanup(self):
        self._running = False
