"""
Alarm System — Natural language alarm setting for Chibi.

Features:
  - Set alarms with natural language: "wake me up at 7am", "set alarm for 6:30"
  - Persistent storage — alarms survive restarts
  - Wake-up mode: Chibi speaks + visual alarm until dismissed
  - Dismiss by voice ("stop", "ok", "snooze") or keypress (any key / space)
  - Snooze support (5 min default)
  - Multiple alarms
  - LLM parses the time from natural language

Install: No extra deps (stdlib only)
"""

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, field


ALARM_FILE = os.path.expanduser("~/.chibi-alarms.json")

# ─── Alarm Trigger Detection ────────────────────────────────────────────────

ALARM_SET_TRIGGERS = [
    "set alarm", "set an alarm", "wake me", "alarm for", "alarm at",
    "remind me at", "wake up at", "get me up", "morning alarm",
    "set a timer for",  # will redirect to alarm if time-of-day mentioned
]

ALARM_CANCEL_TRIGGERS = [
    "cancel alarm", "delete alarm", "remove alarm", "clear alarm",
    "no alarm", "turn off alarm", "disable alarm",
]

ALARM_LIST_TRIGGERS = [
    "what alarms", "show alarms", "list alarms", "my alarms",
    "any alarms", "when is my alarm",
]

ALARM_DISMISS_WORDS = [
    "stop", "ok", "okay", "shut up", "enough", "i'm up",
    "im up", "i am up", "good morning", "thanks", "thank you",
    "dismiss", "turn off", "silence", "quiet", "alright",
]

SNOOZE_WORDS = [
    "snooze", "5 more minutes", "five more", "later", "not yet",
    "few more minutes",
]


def is_alarm_request(text: str) -> str | None:
    """
    Check if text is an alarm-related request.
    Returns: "set", "cancel", "list", or None
    """
    lower = text.lower().strip()
    for trigger in ALARM_SET_TRIGGERS:
        if trigger in lower:
            return "set"
    for trigger in ALARM_CANCEL_TRIGGERS:
        if trigger in lower:
            return "cancel"
    for trigger in ALARM_LIST_TRIGGERS:
        if trigger in lower:
            return "list"
    return None


def is_dismiss_word(text: str) -> bool:
    lower = text.lower().strip()
    return any(w in lower for w in ALARM_DISMISS_WORDS)


def is_snooze_word(text: str) -> bool:
    lower = text.lower().strip()
    return any(w in lower for w in SNOOZE_WORDS)


# ─── Time Parsing ────────────────────────────────────────────────────────────

def parse_alarm_time(text: str) -> datetime | None:
    """
    Parse natural language time into a datetime.
    Handles: "7am", "6:30", "7:00 AM", "in 30 minutes", "tomorrow at 8"
    Returns None if can't parse.
    """
    lower = text.lower().strip()
    now = datetime.now()

    # "in X minutes/hours" / "for X minutes/hours" (timer phrasing —
    # without the "for" variant, "set a timer for 20 minutes" fell through
    # to the bare-number branch and became an 8 PM alarm)
    m = re.search(r'\b(?:in|for)\s+(\d+)\s*(min|minute|hour|hr)', lower)
    if m:
        amount = int(m.group(1))
        unit = m.group(2)
        if 'hour' in unit or 'hr' in unit:
            return now + timedelta(hours=amount)
        else:
            return now + timedelta(minutes=amount)

    # Extract time patterns
    # "7:30 am", "7:30am", "7:30 PM", "7am", "7 am", "19:30"
    patterns = [
        r'(\d{1,2}):(\d{2})\s*(am|pm|a\.m\.|p\.m\.)',  # 7:30 am
        r'(\d{1,2}):(\d{2})',                            # 7:30 or 19:30
        r'(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)',            # 7am, 7 pm
    ]

    hour, minute = None, 0
    is_pm = None

    for pattern in patterns:
        match = re.search(pattern, lower)
        if match:
            groups = match.groups()
            if len(groups) == 3:  # h:mm am/pm
                hour = int(groups[0])
                minute = int(groups[1])
                is_pm = 'p' in groups[2].lower()
            elif len(groups) == 2:
                if groups[1] in ('am', 'pm', 'a.m.', 'p.m.'):  # 7am
                    hour = int(groups[0])
                    is_pm = 'p' in groups[1].lower()
                else:  # 7:30 (24h or ambiguous)
                    hour = int(groups[0])
                    minute = int(groups[1])
            break

    if hour is None:
        # Last resort: just find a bare number
        m = re.search(r'\b(\d{1,2})\b', lower)
        if m:
            hour = int(m.group(1))
            # Guess AM/PM based on context
            if 'morning' in lower or 'wake' in lower:
                is_pm = False
            elif 'evening' in lower or 'night' in lower or 'tonight' in lower:
                is_pm = True

    if hour is None:
        return None

    # Apply AM/PM
    if is_pm is not None:
        if is_pm and hour < 12:
            hour += 12
        elif not is_pm and hour == 12:
            hour = 0
    elif hour <= 6:
        # Ambiguous small numbers — probably PM for alarm context? No, for wake-up it's AM
        # If "wake" is in the text, keep as-is (AM)
        if 'wake' not in lower and 'morning' not in lower:
            hour += 12  # Assume PM for generic alarms

    # Build target time
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # If time already passed today, set for tomorrow
    if target <= now:
        # Check "tomorrow" explicitly
        if 'tomorrow' in lower:
            target += timedelta(days=1)
        elif target + timedelta(minutes=1) < now:
            # Already passed, assume tomorrow
            target += timedelta(days=1)

    return target


_DAY_NAMES = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def parse_alarm_repeat(text: str) -> list | None:
    """
    Detect a repeat spec in natural language.
    Returns a repeat_days list (0=Mon .. 6=Sun) or None for one-shot alarms.
    Handles: "every day/morning/night", "daily", "every weekday"/"weekdays",
    "weekends", "every monday" (etc).
    """
    lower = text.lower()
    if re.search(r"\bevery\s+(day|morning|night|evening)\b", lower) or "daily" in lower:
        return [0, 1, 2, 3, 4, 5, 6]
    if re.search(r"\b(every\s+weekday|weekdays)\b", lower):
        return [0, 1, 2, 3, 4]
    if re.search(r"\b(every\s+weekend|weekends)\b", lower):
        return [5, 6]
    m = re.search(r"\bevery\s+(monday|tuesday|wednesday|thursday|friday"
                  r"|saturday|sunday)s?\b", lower)
    if m:
        return [_DAY_NAMES[m.group(1)]]
    return None


def align_to_repeat_days(target: datetime, repeat_days: list) -> datetime:
    """Push the first firing forward to the next day in repeat_days
    (e.g. 'wake me at 7 every weekday' said on Saturday → Monday 7am)."""
    if not repeat_days or target.weekday() in repeat_days:
        return target
    for i in range(1, 8):
        cand = target + timedelta(days=i)
        if cand.weekday() in repeat_days:
            return cand
    return target


def describe_repeat_days(days: list) -> str:
    """Human-readable repeat spec for confirmations."""
    d = sorted(set(days))
    if d == [0, 1, 2, 3, 4, 5, 6]:
        return "every day"
    if d == [0, 1, 2, 3, 4]:
        return "weekdays"
    if d == [5, 6]:
        return "weekends"
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return "every " + ", ".join(names[i] for i in d)


# ─── Alarm Data ──────────────────────────────────────────────────────────────

@dataclass
class Alarm:
    time: str           # ISO format
    label: str = ""
    enabled: bool = True
    repeating: bool = False
    repeat_days: list = field(default_factory=list)  # 0=Mon, 6=Sun

    @property
    def datetime(self) -> datetime:
        return datetime.fromisoformat(self.time)

    @property
    def time_str(self) -> str:
        return self.datetime.strftime("%I:%M %p")

    def to_dict(self) -> dict:
        return {
            "time": self.time,
            "label": self.label,
            "enabled": self.enabled,
            "repeating": self.repeating,
            "repeat_days": self.repeat_days,
        }

    @staticmethod
    def from_dict(d: dict) -> 'Alarm':
        return Alarm(**d)


# ─── Alarm Manager ───────────────────────────────────────────────────────────

class AlarmManager:
    def __init__(self, config):
        self.config = config
        self.alarms: list[Alarm] = []
        self.is_ringing = False
        self.ring_start_time: float = 0
        self._dismiss_flag = False
        self._snooze_flag = False
        self._lock = threading.Lock()

        # Wake-up messages Chibi cycles through
        name = getattr(config, "user_name", "friend")
        self.wake_messages = [
            f"Good morning {name}! Time to wake up!",
            "Rise and shine! It's a new day!",
            f"Wakey wakey {name}! Come on, you got this!",
            "Hey sleepyhead! Time to get up!",
            "Good morning! The world is waiting for you!",
            f"{name}! It's morning time! Up up up!",
            "Rise and shine sunshine! Let's go!",
        ]
        self._wake_msg_index = 0

        # mtime of ALARM_FILE as we last saw it, so _reload_if_changed() can
        # tell someone else's write (synsh) from our own _save().
        self._file_mtime = 0.0

        self._load()
        try:
            self._file_mtime = os.path.getmtime(ALARM_FILE)
        except OSError:
            pass

        # Start alarm checker thread
        self._running = True
        self._thread = threading.Thread(target=self._check_loop, daemon=True)
        self._thread.start()

    def _load(self):
        if not os.path.exists(ALARM_FILE):
            return
        try:
            with open(ALARM_FILE, "r") as f:
                data = json.load(f)
            self.alarms = [Alarm.from_dict(a) for a in data.get("alarms", [])]
            # Remove past non-repeating alarms
            now = datetime.now()
            self.alarms = [a for a in self.alarms
                           if a.repeating or a.datetime > now]
            # Fast-forward repeating alarms whose time passed while we were
            # off — otherwise they sit in the past and never fire again.
            for a in self.alarms:
                if a.repeating and a.datetime <= now:
                    a.time = self._next_occurrence(a, after=now).isoformat()
            print(f"[Alarm] Loaded {len(self.alarms)} alarms")
        except Exception as e:
            print(f"[Alarm] Load error: {e}")

    def _save(self):
        try:
            data = {"alarms": [a.to_dict() for a in self.alarms]}
            tmp = ALARM_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, ALARM_FILE)
            # Record it, or _reload_if_changed() sees our own write as an
            # external one and reloads the file every second, forever.
            self._file_mtime = os.path.getmtime(ALARM_FILE)
        except Exception as e:
            print(f"[Alarm] Save error: {e}")

    def add_alarm(self, target_time: datetime, label: str = "",
                  repeat_days: list | None = None) -> Alarm:
        alarm = Alarm(
            time=target_time.isoformat(),
            label=label or f"Alarm at {target_time.strftime('%I:%M %p')}",
            repeating=bool(repeat_days),
            repeat_days=list(repeat_days) if repeat_days else [],
        )
        with self._lock:
            self.alarms.append(alarm)
        self._save()
        rep = f" (repeats: {describe_repeat_days(alarm.repeat_days)})" if alarm.repeating else ""
        print(f"[Alarm] Set for {alarm.time_str}{rep}")
        return alarm

    @staticmethod
    def _next_occurrence(alarm: Alarm, after: datetime | None = None) -> datetime:
        """Next datetime strictly after `after` (default now) that matches the
        alarm's time-of-day and repeat_days."""
        after = after or datetime.now()
        base = alarm.datetime
        days = alarm.repeat_days or list(range(7))
        cand = after.replace(hour=base.hour, minute=base.minute,
                             second=0, microsecond=0)
        for i in range(8):
            c = cand + timedelta(days=i)
            if c > after and c.weekday() in days:
                return c
        return cand + timedelta(days=1)

    def cancel_next(self) -> Alarm | None:
        with self._lock:
            if self.alarms:
                self.alarms.sort(key=lambda a: a.time)
                removed = self.alarms.pop(0)
                self._save()
                return removed
        return None

    def cancel_all(self):
        with self._lock:
            self.alarms.clear()
        self._save()

    def list_alarms(self) -> list[Alarm]:
        with self._lock:
            self.alarms.sort(key=lambda a: a.time)
            return list(self.alarms)

    def dismiss(self):
        self._dismiss_flag = True

    def snooze(self, minutes: int = 5):
        """Snooze — dismiss current ring and set a new alarm N minutes from now."""
        self._snooze_flag = True
        snooze_time = datetime.now() + timedelta(minutes=minutes)
        self.add_alarm(snooze_time, label=f"Snooze ({minutes}min)")
        print(f"[Alarm] Snoozed for {minutes} minutes")

    def get_next_wake_message(self) -> str:
        msg = self.wake_messages[self._wake_msg_index % len(self.wake_messages)]
        self._wake_msg_index += 1
        return msg

    def _reload_if_changed(self):
        """Pick up alarms set by someone else — synsh writes this same file.

        _load() only ran at startup, so `set alarm for 7:30am` in synsh went
        into ~/.chibi-alarms.json and was never seen by a Chibi that was already
        running: the alarm simply never rang.

        Our own _save() bumps the mtime too, so record it there as well —
        otherwise every save looks like an external change and we reload our own
        file once a second forever.
        """
        try:
            mtime = os.path.getmtime(ALARM_FILE)
        except OSError:
            return
        if mtime == self._file_mtime:
            return
        self._file_mtime = mtime
        with self._lock:
            self._load()
        print("[Alarm] reloaded — alarms changed on disk")

    def _check_loop(self):
        """Background thread checking if any alarm should fire."""
        while self._running:
            try:
                self._reload_if_changed()
                now = datetime.now()

                with self._lock:
                    triggered = None
                    for alarm in self.alarms:
                        if not alarm.enabled:
                            continue
                        # Fire if within 30 seconds of alarm time
                        diff = (alarm.datetime - now).total_seconds()
                        if -30 <= diff <= 0:
                            triggered = alarm
                            break

                if triggered and not self.is_ringing:
                    print(f"[Alarm] 🔔 RINGING: {triggered.label}")
                    self.is_ringing = True
                    self.ring_start_time = time.time()
                    self._dismiss_flag = False
                    self._snooze_flag = False
                    self._wake_msg_index = 0

                    # One-shot alarms are removed; repeating ones are
                    # rescheduled to their next matching day.
                    with self._lock:
                        if triggered in self.alarms:
                            if triggered.repeating and triggered.repeat_days:
                                triggered.time = self._next_occurrence(
                                    triggered).isoformat()
                            else:
                                self.alarms.remove(triggered)
                    self._save()

                # Auto-dismiss after 10 minutes of ringing
                if self.is_ringing:
                    if self._dismiss_flag or self._snooze_flag:
                        self.is_ringing = False
                        self._dismiss_flag = False
                        self._snooze_flag = False
                    elif time.time() - self.ring_start_time > 600:
                        print("[Alarm] Auto-dismissed after 10 minutes")
                        self.is_ringing = False

            except Exception as e:
                print(f"[Alarm] Check error: {e}")

            time.sleep(1)

    def stop(self):
        self._running = False
