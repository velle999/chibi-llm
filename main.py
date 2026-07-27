#!/usr/bin/env python3
"""
CHIBI LLM AVATAR — Pygame client for Raspberry Pi 4
Connects to a remote LLM server (Ollama/llama.cpp) on your PC.
Displays a cute chibi avatar that reacts to conversation state.
"""

import pygame
import sys
import math
import time
import threading
import json
import re
import difflib
import textwrap
from enum import Enum, auto

# Line-buffer stdout/stderr so logs flush promptly to ~/chibi.log on the Pi
# (Python block-buffers when stdout is redirected to a file, which otherwise
# hides the most recent prints — including tracebacks — until a 4KB block fills).
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass
from dataclasses import dataclass, field

from llm_client import LLMClient
from sprite_renderer import ChibiRenderer
from voice_input import VoiceInput
from voice_output import VoiceOutput
from data_feeds import DataFeedManager
from hud_overlay import HUDOverlay
from memory import PersistentMemory
from soul import Soul
from thoth import ThothCorpus
from secfeed import SecFeed
from vision import Vision, is_vision_request
from alarm import (AlarmManager, is_alarm_request, is_dismiss_word,
                   is_snooze_word, parse_alarm_time, parse_alarm_repeat,
                   align_to_repeat_days, describe_repeat_days)
from config import Config

# Whisper-tiny frequently mishears the spoken name "Horus". Any of these single
# words spoken alone is treated as the "horus" entry trigger. (Exit is handled
# separately and stays strict so a misheard word can't drop you out of a dream.)
_HORUS_SOUNDALIKES = {
    "horus", "horace", "horis", "hosur", "horse", "hoarse", "chorus",
    "taurus", "torus", "porous", "poorest", "boris", "morris", "norris",
    "hummus", "hours", "horror", "florist", "forrest", "forest",
}


def _sounds_like_horus(word: str) -> bool:
    """True if a transcribed word is "horus" or a likely Whisper-tiny mishear.

    Backed by the curated set above plus a fuzzy fallback, so close variants
    are caught without listing every one — but a word still has to *resemble*
    "horus", which is what keeps ambient "<x> mode" room noise (TV, "sleep
    mode", ...) from re-triggering Horus mode.
    """
    if word in _HORUS_SOUNDALIKES:
        return True
    return len(word) >= 4 and difflib.SequenceMatcher(None, word, "horus").ratio() >= 0.7


# Whisper-tiny mishears the wake name "Chibi" almost as much as "Horus". These
# are the common variants; the fuzzy fallback catches the rest. Used to decide
# whether a voice line is actually addressed to Chibi (vs. ambient TV chatter).
_CHIBI_SOUNDALIKES = {
    "chibi", "chiby", "chibby", "chibbi", "chiba", "chibe", "cheeby", "cheaby",
    "cheebi", "shibby", "shibi", "shibby", "chevy", "chibbe", "tibby", "chimi",
    "chippy", "hibi", "kibbe", "chebi",
}


def _sounds_like_chibi(word: str) -> bool:
    """True if a transcribed word is "chibi" or a likely Whisper-tiny mishear.

    This is the wake-word check: a voice line only reaches the LLM if it names
    Chibi (or arrives inside the open conversation window). The fuzzy fallback
    still requires the word to *resemble* "chibi", so random room/TV words
    don't slip through.
    """
    if word in _CHIBI_SOUNDALIKES:
        return True
    return len(word) >= 4 and difflib.SequenceMatcher(None, word, "chibi").ratio() >= 0.72

# ─── Avatar States ───────────────────────────────────────────────────────────

class AvatarState(Enum):
    IDLE = auto()
    LISTENING = auto()
    THINKING = auto()
    SPEAKING = auto()
    HAPPY = auto()
    CONFUSED = auto()
    SLEEPING = auto()
    ALARM = auto()

# ─── Particle System ────────────────────────────────────────────────────────

@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    color: tuple
    size: float

class ParticleSystem:
    def __init__(self):
        self.particles: list[Particle] = []

    def emit(self, x, y, count=5, color=(0, 255, 255), spread=2.0, life=1.0, size=3):
        import random
        for _ in range(count):
            self.particles.append(Particle(
                x=x + random.uniform(-10, 10),
                y=y + random.uniform(-10, 10),
                vx=random.uniform(-spread, spread),
                vy=random.uniform(-spread * 1.5, -spread * 0.3),
                life=life,
                max_life=life,
                color=color,
                size=random.uniform(size * 0.5, size * 1.5),
            ))

    def update(self, dt):
        for p in self.particles:
            p.x += p.vx * dt * 60
            p.y += p.vy * dt * 60
            p.life -= dt
            p.vy -= 0.02 * dt * 60  # gentle float upward
        self.particles = [p for p in self.particles if p.life > 0]

    def draw(self, surface):
        for p in self.particles:
            alpha = max(0, p.life / p.max_life)
            r, g, b = p.color
            color = (r, g, b)
            size = max(1, int(p.size * alpha))
            pos = (int(p.x), int(p.y))
            # Glow effect
            if size > 2:
                glow_surf = pygame.Surface((size * 4, size * 4), pygame.SRCALPHA)
                glow_color = (r, g, b, int(40 * alpha))
                pygame.draw.circle(glow_surf, glow_color, (size * 2, size * 2), size * 2)
                surface.blit(glow_surf, (pos[0] - size * 2, pos[1] - size * 2))
            pygame.draw.circle(surface, color, pos, size)

# ─── Chat Bubble ─────────────────────────────────────────────────────────────

class ChatBubble:
    def __init__(self, config: Config):
        self.config = config
        self.text = ""
        self.target_text = ""
        self.char_index = 0
        self.char_timer = 0
        self.visible = False
        self.alpha = 0
        self.font = None

    def init_font(self):
        self.font = pygame.font.SysFont("monospace", self.config.bubble_font_size)

    def set_text(self, text: str):
        self.target_text = text
        self.char_index = 0
        self.text = ""
        self.visible = True

    def hide(self):
        self.visible = False
        self.text = ""
        self.target_text = ""

    def update(self, dt):
        if self.visible:
            self.alpha = min(255, self.alpha + dt * 600)
            # Typewriter effect
            self.char_timer += dt
            if self.char_timer > 0.03 and self.char_index < len(self.target_text):
                self.char_index += 1
                self.text = self.target_text[:self.char_index]
                self.char_timer = 0
        else:
            self.alpha = max(0, self.alpha - dt * 400)

    def draw(self, surface, cx, top_y):
        if self.alpha <= 0 or not self.text:
            return

        if not self.font:
            self.init_font()

        max_w = self.config.bubble_max_width
        wrapped = textwrap.wrap(self.text, width=max_w // (self.config.bubble_font_size * 0.6))
        if not wrapped:
            return

        line_surfs = [self.font.render(line, True, self.config.bubble_text_color) for line in wrapped]
        total_h = sum(s.get_height() for s in line_surfs) + 8 * len(line_surfs)
        max_line_w = max(s.get_width() for s in line_surfs)

        pad = 16
        bw = max_line_w + pad * 2
        bh = total_h + pad * 2

        bx = cx - bw // 2
        by = top_y - bh - 20

        # Bubble background
        bubble_surf = pygame.Surface((bw, bh), pygame.SRCALPHA)
        bg = (*self.config.bubble_bg_color, int(self.alpha * 0.85))
        pygame.draw.rect(bubble_surf, bg, (0, 0, bw, bh), border_radius=12)

        # Border glow
        border_color = (*self.config.neon_primary, int(self.alpha * 0.6))
        pygame.draw.rect(bubble_surf, border_color, (0, 0, bw, bh), width=2, border_radius=12)

        # Draw text
        y_offset = pad
        for ls in line_surfs:
            bubble_surf.blit(ls, (pad, y_offset))
            y_offset += ls.get_height() + 8

        surface.blit(bubble_surf, (bx, by))

        # Speech tail
        tail_points = [
            (cx - 8, by + bh),
            (cx + 8, by + bh),
            (cx, by + bh + 12),
        ]
        tail_surf = pygame.Surface((surface.get_width(), surface.get_height()), pygame.SRCALPHA)
        pygame.draw.polygon(tail_surf, bg, tail_points)
        surface.blit(tail_surf, (0, 0))

# ─── Input Box ───────────────────────────────────────────────────────────────

class InputBox:
    def __init__(self, config: Config):
        self.config = config
        self.text = ""
        self.active = True
        self.font = None
        self.cursor_visible = True
        self.cursor_timer = 0

    def init_font(self):
        self.font = pygame.font.SysFont("monospace", 18)

    def handle_event(self, event) -> str | None:
        """Returns the submitted text or None."""
        if event.type == pygame.KEYDOWN and self.active:
            if event.key == pygame.K_RETURN and self.text.strip():
                submitted = self.text.strip()
                self.text = ""
                return submitted
            elif event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.unicode and event.unicode.isprintable():
                self.text += event.unicode
        return None

    def update(self, dt):
        self.cursor_timer += dt
        if self.cursor_timer > 0.5:
            self.cursor_visible = not self.cursor_visible
            self.cursor_timer = 0

    def draw(self, surface):
        if not self.font:
            self.init_font()

        w = surface.get_width()
        h = 44
        y = surface.get_height() - h - 10
        x = 20
        box_w = w - 40

        # Background
        box_surf = pygame.Surface((box_w, h), pygame.SRCALPHA)
        pygame.draw.rect(box_surf, (10, 10, 30, 200), (0, 0, box_w, h), border_radius=8)
        pygame.draw.rect(box_surf, (*self.config.neon_primary, 120), (0, 0, box_w, h), width=1, border_radius=8)

        # Text
        display_text = self.text
        cursor = "▌" if self.cursor_visible else " "
        text_surf = self.font.render(f"> {display_text}{cursor}", True, self.config.neon_primary)

        # Clip text
        box_surf.blit(text_surf, (12, (h - text_surf.get_height()) // 2))
        surface.blit(box_surf, (x, y))

        # Hint
        if not self.text:
            hint = self.font.render("Type a message...", True, (60, 60, 80))
            surface.blit(hint, (x + 30, y + (h - hint.get_height()) // 2))

# ─── Status Bar ──────────────────────────────────────────────────────────────

class StatusBar:
    def __init__(self, config: Config):
        self.config = config
        self.status = "Disconnected"
        self.font = None
        self.clock_font = None

    def init_font(self):
        self.font = pygame.font.SysFont("monospace", 14)
        self.clock_font = pygame.font.SysFont(
            "monospace", getattr(self.config, "clock_font_size", 22), bold=True)

    def draw(self, surface, state: AvatarState, connected: bool,
             voice_in=None, voice_out=None):
        if not self.font:
            self.init_font()

        w = surface.get_width()
        from datetime import datetime
        now = datetime.now()

        # Clock (top-left, prominent)
        time_str = now.strftime("%I:%M %p")
        clock_surf = self.clock_font.render(time_str, True, self.config.neon_primary)
        surface.blit(clock_surf, (12, 6))
        clock_bottom = 6 + clock_surf.get_height()

        # Date under clock (anchored below the clock so larger clock sizes fit)
        date_str = now.strftime("%a %b %d")
        date_surf = self.font.render(date_str, True, (80, 100, 120))
        surface.blit(date_surf, (14, clock_bottom + 2))

        # Connection status dot (next to date)
        dot_color = (0, 255, 100) if connected else (255, 60, 60)
        status_text = f"● {state.name}"
        text_surf = self.font.render(status_text, True, dot_color)
        surface.blit(text_surf, (14, clock_bottom + 4 + date_surf.get_height()))

        # Voice indicators (center)
        voice_parts = []
        if voice_in:
            if voice_in.is_recording:
                voice_parts.append(("🎙 REC", (255, 80, 80)))
            elif voice_in.is_listening:
                voice_parts.append(("🎙 ON", (0, 255, 100)))
            else:
                voice_parts.append(("🎙 OFF", (100, 100, 100)))

        if voice_out and voice_out.is_speaking:
            voice_parts.append(("🔊", (0, 200, 255)))

        x_offset = w // 2 - 60
        for label, color in voice_parts:
            vs = self.font.render(label, True, color)
            surface.blit(vs, (x_offset, 8))
            x_offset += vs.get_width() + 16

        # Server info (top-right, below weather panel area)
        server_text = f"{self.config.llm_host}:{self.config.llm_port}"
        server_surf = self.font.render(server_text, True, (40, 45, 55))
        surface.blit(server_surf, (w - server_surf.get_width() - 12, 8))

        # Controls hint
        hint = self.font.render("[F1] mic  [F11] window  [ESC] quit", True, (35, 35, 50))
        surface.blit(hint, (12, surface.get_height() - 18))

# ─── Main App ────────────────────────────────────────────────────────────────

class ChibiAvatarApp:
    def __init__(self):
        self.config = Config()
        pygame.init()

        self.screen = self._init_display()
        pygame.display.set_caption("Chibi LLM Avatar")

        self.clock = pygame.time.Clock()
        self.running = True

        # State
        self.state = AvatarState.IDLE
        self.state_timer = 0
        self.last_interaction = time.time()
        # Rolling wake-word window: voice lines are only forwarded to the LLM
        # while now < _wake_until (opened by naming Chibi or by any typed/real
        # exchange). 0 = closed, so the very first voice line must say the name.
        self._wake_until = 0.0
        # Consecutive voice lines accepted *only* because the window was open
        # (never naming her). The window re-opens on every accepted exchange, so
        # without a cap one Whisper mishear of the TV starts a conversation that
        # sustains itself forever — each reply renews her permission to listen.
        # Reset by anything that really addresses her: her name, the wake word,
        # typed input, or a fresh impulse of her own.
        self._unaddressed_streak = 0

        # Components
        self.renderer = ChibiRenderer(self.config)
        self.particles = ParticleSystem()
        self.bubble = ChatBubble(self.config)
        self.input_box = InputBox(self.config)
        self.status_bar = StatusBar(self.config)
        self.llm = LLMClient(self.config)
        # Background ping so the status dot stays honest between messages
        self.llm.start_health_check()

        # Voice
        self.voice_in = None
        self.voice_out = None
        if self.config.voice_enabled:
            self.voice_out = VoiceOutput(
                voice=self.config.tts_voice,
                speed=self.config.tts_speed,
                pitch_semitones=self.config.tts_pitch_semitones,
            )
            self.voice_in = VoiceInput(
                model_size=self.config.stt_model,
                device="cpu",
                compute_type="int8",
                silence_threshold=getattr(self.config, "vad_silence_threshold", 1000),
                min_speech_duration=getattr(self.config, "vad_min_speech_duration", 0.6),
                oww_enabled=getattr(self.config, "oww_enabled", False),
                oww_model=getattr(self.config, "oww_model", ""),
                oww_threshold=getattr(self.config, "oww_threshold", 0.5),
                model_dir=getattr(self.config, "stt_model_dir", ""),
            )
            self.voice_in.start_listening()

        # Background
        self.bg_stars = self._generate_stars(80)
        self.scanline_surf = self._create_scanlines()

        # Data feeds + HUD
        self.feeds = DataFeedManager(self.config)
        self.hud = HUDOverlay(self.config)

        # Persistent memory
        self.memory = PersistentMemory()
        self.memory.start_conversation()
        self._message_count = 0

        # Soul — persistent mood, relationship arc, spontaneous impulses
        self.soul = None
        if getattr(self.config, "soul_enabled", True):
            self.soul = Soul(self.config)
            # Seed relationship stats from long-term memory on first run so an
            # old friendship isn't greeted with "our first conversation!"
            st = self.memory.stats
            self.soul.adopt_history(st.get("total_messages", 0),
                                    st.get("first_interaction") or "")
        self._soul_feed_timer = 0.0
        self._last_impulse_spoken = 0.0
        self._prev_weather_condition = ""
        self._prev_news_updated = ""
        self._market_alerts: dict[str, float] = {}

        # Dream journal sync with the peer chibi instance over the LAN
        self.dream_sync = None
        if getattr(self.config, "dream_sync_enabled", False):
            from dream_sync import DreamSync
            self.dream_sync = DreamSync(self.memory, self.config)
            self.dream_sync.start()

        # Thoth's reference corpus (correspondence lexicon + optional text RAG)
        self.thoth = ThothCorpus(config=self.config)

        # Vision
        self.vision = None
        if self.config.vision_enabled:
            self.vision = Vision(self.config)
            if self.vision.available:
                self.vision.start_awareness()
            else:
                self.vision = None

        # Weather effects
        self.weather_particles = []
        self.lightning_flash = 0

        # Alarm
        self.alarm = AlarmManager(self.config)
        self._alarm_speak_timer = 0

        # Horus / Thoth mode
        self.horus_mode = False
        self.horus_auto_triggered = False
        self._horus_check_timer = 0.0

        # Security / sentinel mode. The feed subscriber runs from startup, not
        # from mode entry, so that on entering the aspect there is already a
        # session's worth of verdicts to report rather than an empty feed.
        self.security_mode = False
        self.secfeed = None
        if getattr(self.config, "security_enabled", False):
            self.secfeed = SecFeed()
            self.secfeed.start()

        # Dream journal viewer (F2 overlay)
        self.dream_view_open = False
        self._dream_view_entries: list[dict] = []
        self.dream_view_index = 0      # selected entry in the list
        self._dream_detail = False     # True when drilled into one entry
        self._dream_scroll = 0         # line scroll offset in detail view

        # Conversation
        self.conversation: list[dict] = []
        self.response_text = ""
        self.is_generating = False
        # Timestamp of the last frame we were speaking — drives the half-duplex
        # echo cooldown so the mic doesn't transcribe Chibi's own TTS tail.
        self._last_spoke_at = 0.0

        # Auto-enter Horus mode if within the threshold hours. Must run AFTER
        # conversation/bubble/voice_out exist, since _enter_horus_mode uses them.
        self._check_horus_threshold()

    def _init_display(self):
        """Create the main surface, fullscreen on the chosen monitor.

        Plain set_mode(FULLSCREEN) always lands on SDL display 0 (the primary),
        which is why Chibi pops up on the main screen. We pick a target monitor
        and use its native resolution so the window fills it with no video
        mode-switch. config.display_index controls the choice (-1 = auto-detect
        the portrait monitor).
        """
        if not self.config.fullscreen:
            # RESIZABLE because a tiling Wayland compositor (synui) will size
            # this window to its layout the moment it maps, whatever we ask
            # for. Without the flag the surface and the window disagree.
            screen = pygame.display.set_mode(
                (self.config.window_width, self.config.window_height),
                pygame.RESIZABLE,
            )
            # Adopt the real surface size, exactly as the fullscreen path
            # below does. Skipping this was what left the starfield and the
            # avatar laid out in an 800x480 box in the top-left corner while
            # the ticker and input bar — which measure the surface itself —
            # correctly spanned the whole window.
            self._adopt_surface_size(screen)
            return screen

        try:
            sizes = pygame.display.get_desktop_sizes()
        except Exception:
            sizes = []

        target = self.config.display_index
        if target is None or target < 0:
            # Auto: first portrait monitor (taller than wide), else primary.
            target = next((i for i, (w, h) in enumerate(sizes) if h > w), 0)
        elif target >= len(sizes):
            print(f"[Display] display_index {target} out of range; "
                  f"{len(sizes)} monitor(s) detected — using 0")
            target = 0

        size = sizes[target] if target < len(sizes) else (
            self.config.window_width, self.config.window_height)

        if sizes:
            print(f"[Display] monitors={sizes} -> fullscreen on #{target} {size}")

        try:
            screen = pygame.display.set_mode(size, pygame.FULLSCREEN, display=target)
        except (TypeError, pygame.error) as e:
            # Older pygame without the display= kwarg, or target unavailable.
            print(f"[Display] targeted fullscreen failed ({e}); falling back to #0")
            screen = pygame.display.set_mode(size, pygame.FULLSCREEN)

        # Adopt the real surface size so all layout uses the monitor's geometry.
        self._adopt_surface_size(screen)
        return screen

    def _adopt_surface_size(self, screen):
        """Point config.window_* at the surface we actually got.

        Roughly forty layout sites read config.window_width/height rather than
        measuring the surface, so these two values ARE the layout. Any time the
        real surface changes size they have to follow, or everything that reads
        them draws to the old geometry while everything that measures the
        surface draws to the new one.
        """
        self.config.window_width, self.config.window_height = screen.get_size()

    def _extract_memories(self):
        """Ask the LLM to extract memorable facts from recent conversation."""
        try:
            prompt = self.memory.get_extraction_prompt(self.conversation)
            result = ""
            for chunk in self.llm.stream_chat(
                [{"role": "user", "content": prompt}],
                extra_system="You are a memory extraction assistant. Return ONLY valid JSON.",
                num_predict=512,  # JSON extraction needs room; not user-facing chat
            ):
                result += chunk
            self.memory.process_extraction(result)
        except Exception as e:
            print(f"[Memory] Extraction failed: {e}")
    def _check_horus_threshold(self):
        """Auto-enter Horus mode during threshold hours (default 5-8am).

        Called at startup AND about once a minute from update() — the app runs
        for weeks at a time, so a startup-only check would never fire. Once
        the window passes, the auto flag re-arms for the next dawn (a manual
        exit during the window stays exited until then).
        """
        from datetime import datetime
        hour = datetime.now().hour
        in_window = (self.config.horus_threshold_start <= hour
                     < self.config.horus_threshold_end)
        if in_window:
            if (not self.horus_auto_triggered and not self.horus_mode
                    and not self.is_generating):
                self._enter_horus_mode(auto=True)
        elif self.horus_auto_triggered:
            self.horus_auto_triggered = False

    def _enter_horus_mode(self, auto=False):
        """Activate Thoth aspect."""
        self.horus_mode = True
        if auto:
            self.horus_auto_triggered = True
        print("[Horus] Thoth mode activated.")
        if auto:
            # Threshold entry happens unprompted (often pre-dawn in a
            # bedroom) — switch silently; the aspect overlay shows the state.
            return
        opening = "The journal is open. Speak what needs to be recorded."
        self.conversation.append({"role": "assistant", "content": opening})
        self.bubble.set_text(opening)
        if self.voice_out:
            self.voice_out.speak(opening)

    def _exit_horus_mode(self):
        """Return to Chibi aspect."""
        self.horus_mode = False
        print("[Horus] Returning to Chibi mode.")
        closing = "Recorded. The eye closes. I'm Chibi again :3"
        self.conversation.append({"role": "assistant", "content": closing})
        self.bubble.set_text(closing)
        if self.voice_out:
            self.voice_out.speak(closing)

    # ── Security / sentinel aspect ───────────────────────────────────────
    def _enter_security_mode(self):
        """Activate the sentinel aspect and deliver the security overview."""
        self.security_mode = True
        # The two aspects are mutually exclusive: the scribe and the sentinel
        # have contradictory system prompts, and both would be injected.
        self.horus_mode = False
        print("[Security] Sentinel mode activated.")

        overview = (self.secfeed.overview() if self.secfeed
                    else "Security monitoring is disabled in my config.")
        opening = "Sentinel online. " + overview
        self.conversation.append({"role": "assistant", "content": opening})
        self.bubble.set_text(opening)
        if self.voice_out:
            self.voice_out.speak(opening)
        # Entering the aspect is itself an acknowledgement of whatever is
        # already queued, so don't immediately re-announce the same events.
        if self.secfeed:
            self.secfeed.drain_notable()

    def _exit_security_mode(self):
        """Return to Chibi aspect."""
        self.security_mode = False
        print("[Security] Sentinel standing down.")
        closing = "Sentinel offline. I'm Chibi again :3"
        self.conversation.append({"role": "assistant", "content": closing})
        self.bubble.set_text(closing)
        if self.voice_out:
            self.voice_out.speak(closing)

    def _check_security_triggers(self, text: str) -> bool:
        """Security-mode switch commands. True if the input was consumed.

        MUST be checked before _check_horus_triggers(): that one treats *any*
        short utterance ending in "mode" as a Horus entry (Whisper-tiny cannot
        reliably transcribe "Horus"), so "security mode" would otherwise open
        the dream journal instead of the sentinel.
        """
        if not self.secfeed:
            return False
        lower = text.lower().strip()

        if self.security_mode:
            cmd = lower.strip(" .,!?\"'")
            words = re.findall(r"[a-z']+", lower)
            is_short = len(words) <= 4
            if (any(p in lower for p in self.config.security_exit_phrases)
                    or cmd in ("exit", "quit", "done", "stop", "chibi")
                    or (is_short and any(_sounds_like_chibi(w) for w in words))):
                self._exit_security_mode()
                return True
            # A bare "status"/"overview" while already in the aspect re-reads
            # the live feed without a round-trip through the LLM.
            if cmd in ("status", "overview", "security status", "security overview",
                       "report", "sitrep"):
                summary = self.secfeed.overview()
                self.conversation.append({"role": "assistant", "content": summary})
                self.bubble.set_text(summary)
                if self.voice_out:
                    self.voice_out.speak(summary)
                self.secfeed.drain_notable()
                return True
            return False

        for phrase in self.config.security_entry_phrases:
            if phrase in lower:
                self._enter_security_mode()
                return True
        return False

    def _announce_security_events(self):
        """While the sentinel is up, speak new notable verdicts as they land."""
        if not (self.security_mode and self.secfeed
                and self.config.security_announce):
            return
        # Don't talk over an in-flight reply or another utterance.
        if self.is_generating or (self.voice_out and self.voice_out.busy):
            return
        events = self.secfeed.drain_notable()
        if not events:
            return
        # A burst of verdicts (a scan, a misbehaving process in a loop) must not
        # become a burst of speech — collapse it into one utterance.
        if len(events) == 1:
            msg = "Security event: " + events[0].describe()
        else:
            worst = max(events, key=lambda e: (e.verdict, e.threat))
            msg = (f"{len(events)} security events. "
                   f"Most severe: {worst.describe()}")
        self.conversation.append({"role": "assistant", "content": msg})
        self.bubble.set_text(msg)
        if self.voice_out:
            self.voice_out.speak(msg)

    # ── Dream journal viewer (F2) ────────────────────────────────────────
    def _open_dream_view(self):
        """Open the in-app dream history overlay (snapshot, newest first)."""
        self._dream_view_entries = list(reversed(self.memory.get_dream_entries()))
        self.dream_view_index = 0
        self._dream_detail = False
        self._dream_scroll = 0
        self.dream_view_open = True

    def _handle_dream_view_key(self, event):
        """Route keys while the dream overlay is open. Captures all input."""
        entries = self._dream_view_entries
        if self._dream_detail:
            if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE, pygame.K_LEFT):
                self._dream_detail = False
                self._dream_scroll = 0
            elif event.key in (pygame.K_DOWN, pygame.K_j):
                self._dream_scroll += 1
            elif event.key in (pygame.K_UP, pygame.K_k):
                self._dream_scroll = max(0, self._dream_scroll - 1)
            elif event.key == pygame.K_PAGEDOWN:
                self._dream_scroll += 12
            elif event.key == pygame.K_PAGEUP:
                self._dream_scroll = max(0, self._dream_scroll - 12)
            return
        # List navigation
        if event.key in (pygame.K_ESCAPE, pygame.K_F2):
            self.dream_view_open = False
        elif event.key in (pygame.K_DOWN, pygame.K_j):
            if entries:
                self.dream_view_index = min(len(entries) - 1, self.dream_view_index + 1)
        elif event.key in (pygame.K_UP, pygame.K_k):
            self.dream_view_index = max(0, self.dream_view_index - 1)
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_RIGHT):
            if entries:
                self._dream_detail = True
                self._dream_scroll = 0

    @staticmethod
    def _fmt_dream_ts(iso: str) -> str:
        """Format an ISO created_at into 'YYYY-MM-DD HH:MM' (best effort)."""
        try:
            from datetime import datetime
            return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            return (iso or "")[:16]

    @staticmethod
    def _wrap_text(text: str, font, max_width: int) -> list:
        """Word-wrap text to a pixel width; preserves blank lines."""
        lines = []
        for para in (text or "").split("\n"):
            if not para.strip():
                lines.append("")
                continue
            cur = ""
            for word in para.split(" "):
                trial = word if not cur else cur + " " + word
                if font.size(trial)[0] <= max_width:
                    cur = trial
                else:
                    if cur:
                        lines.append(cur)
                    cur = word
            if cur:
                lines.append(cur)
        return lines

    def _draw_dream_journal(self):
        """Full-screen overlay: list of dreams, or one dream's full text."""
        W, H = self.config.window_width, self.config.window_height
        gold = self.config.horus_gold
        if not hasattr(self, "_dj_title_font"):
            self._dj_title_font = pygame.font.SysFont("serif", 30, bold=True)
            self._dj_font = pygame.font.SysFont("monospace", 20)
            self._dj_small = pygame.font.SysFont("monospace", 15)

        # Dim backdrop
        panel = pygame.Surface((W, H), pygame.SRCALPHA)
        panel.fill((*self.config.horus_bg_color, 235))
        self.screen.blit(panel, (0, 0))
        pygame.draw.rect(self.screen, gold, (8, 8, W - 16, H - 16), width=2, border_radius=6)

        margin = 28
        entries = self._dream_view_entries

        title = self._dj_title_font.render("DREAM JOURNAL", True, gold)
        self.screen.blit(title, (W // 2 - title.get_width() // 2, 28))

        if not entries:
            empty = self._dj_font.render("No dreams recorded yet.", True, (200, 200, 210))
            self.screen.blit(empty, (W // 2 - empty.get_width() // 2, H // 2))
            hint = self._dj_small.render("Esc / F2 to close", True, (150, 150, 165))
            self.screen.blit(hint, (W // 2 - hint.get_width() // 2, H - 44))
            return

        idx = max(0, min(self.dream_view_index, len(entries) - 1))

        if self._dream_detail:
            # ── Detail view ──────────────────────────────────────────────
            e = entries[idx]
            hint = self._dj_small.render(
                "↑/↓ scroll · Esc back", True, (150, 150, 165))
            self.screen.blit(hint, (W // 2 - hint.get_width() // 2, H - 44))

            header = f"{self._fmt_dream_ts(e.get('created_at',''))}"
            tone = e.get("emotional_tone", "")
            if tone:
                header += f"   · tone: {tone}"
            hsurf = self._dj_font.render(header, True, gold)
            self.screen.blit(hsurf, (margin, 78))

            syms = e.get("symbols_flagged") or []
            top = 110
            if syms:
                ssurf = self._dj_small.render(
                    "symbols: " + ", ".join(str(s) for s in syms), True, (170, 180, 210))
                self.screen.blit(ssurf, (margin, top))
                top += 26

            body_top = top + 6
            line_h = self._dj_font.get_linesize()
            visible = (H - 60 - body_top) // line_h
            wrapped = self._wrap_text(e.get("text", ""), self._dj_font, W - 2 * margin)
            max_scroll = max(0, len(wrapped) - visible)
            self._dream_scroll = min(self._dream_scroll, max_scroll)
            for i, line in enumerate(wrapped[self._dream_scroll:self._dream_scroll + visible]):
                surf = self._dj_font.render(line, True, (225, 225, 235))
                self.screen.blit(surf, (margin, body_top + i * line_h))
            if max_scroll:
                pos = self._dj_small.render(
                    f"{self._dream_scroll + 1}-"
                    f"{min(self._dream_scroll + visible, len(wrapped))}/{len(wrapped)}",
                    True, (150, 150, 165))
                self.screen.blit(pos, (W - margin - pos.get_width(), 78))
            return

        # ── List view ────────────────────────────────────────────────────
        hint = self._dj_small.render(
            "↑/↓ select · Enter open · Esc/F2 close", True, (150, 150, 165))
        self.screen.blit(hint, (W // 2 - hint.get_width() // 2, H - 44))

        row_h = 64
        list_top = 86
        visible = (H - 70 - list_top) // row_h
        start = max(0, min(idx - visible // 2, len(entries) - visible))
        start = max(0, start)
        for row, e in enumerate(entries[start:start + visible]):
            ei = start + row
            y = list_top + row * row_h
            selected = (ei == idx)
            if selected:
                pygame.draw.rect(self.screen, (*gold, 40),
                                 (margin - 8, y - 4, W - 2 * (margin - 8), row_h - 6),
                                 border_radius=4)
                pygame.draw.rect(self.screen, gold,
                                 (margin - 8, y - 4, W - 2 * (margin - 8), row_h - 6),
                                 width=1, border_radius=4)
            meta = self._fmt_dream_ts(e.get("created_at", ""))
            tone = e.get("emotional_tone", "")
            if tone:
                meta += f"   · {tone}"
            mcol = gold if selected else (190, 175, 120)
            msurf = self._dj_small.render(meta, True, mcol)
            self.screen.blit(msurf, (margin, y))
            preview = (e.get("text", "") or "").replace("\n", " ")
            while preview and self._dj_font.size(preview)[0] > W - 2 * margin:
                preview = preview[:-2]
            if len(preview) < len((e.get("text", "") or "").replace("\n", " ")):
                preview = preview.rstrip() + "…"
            psurf = self._dj_font.render(preview, True,
                                         (235, 235, 245) if selected else (190, 190, 200))
            self.screen.blit(psurf, (margin, y + 24))

        # Scroll affordance
        count = self._dj_small.render(
            f"{idx + 1}/{len(entries)}", True, (150, 150, 165))
        self.screen.blit(count, (W - margin - count.get_width(), 56))

    def _check_horus_triggers(self, text: str) -> bool:
        """
        Check if user input is a Horus mode switch command.
        Returns True if the input was consumed as a command.
        """
        lower = text.lower().strip()
        if self.horus_mode:
            # Exit must be as forgiving as entry. Whisper-tiny garnishes spoken
            # commands with stray words ("TV wake up", "course mode", "okay
            # chibi"), so the old exact-whole-message match missed most real
            # exits — yet entry fires on any short "<x> mode". The one thing we
            # must NOT treat as an exit is Chibi's own dream interpretation
            # echoing back through the mic, but those are always long, so a short
            # word-count gate cleanly separates a user command from echo.
            # Whisper appends punctuation ("Exit." -> "exit."); strip it first.
            cmd = lower.strip(" .,!?\"'")
            words = re.findall(r"[a-z']+", lower)
            is_short = len(words) <= 4
            # Multi-word exit commands (e.g. "wake up") must be matched as a
            # SUBSTRING — the per-word check below can't see a two-word phrase,
            # and Whisper-tiny mangles the spoken name "Chibi" into "CB"/"baby",
            # so "wake up" is actually the most reliable exit signal. Also accept
            # chibi-mishears via the fuzzy matcher.
            multiword_exit = any(
                " " in ew and ew in lower for ew in self.config.horus_exit_words)
            if (cmd in self.config.horus_exit_words
                    or any(p in lower for p in self.config.horus_exit_phrases)
                    or (is_short and multiword_exit)
                    or (is_short and any(w in self.config.horus_exit_words
                                         for w in words))
                    or (is_short and any(_sounds_like_chibi(w) for w in words))
                    or (is_short and words and words[-1] == "mode")):
                self._exit_horus_mode()
                return True
            # While recording, don't let entry phrases swallow the dream text.
            return False
        # Not in Horus mode: entry phrases activate it.
        for phrase in self.config.horus_entry_phrases:
            if phrase in lower:
                self._enter_horus_mode(auto=False)
                return True
        # Whisper-tiny can't transcribe the proper noun "Horus" — it comes out a
        # different word almost every time (horse/chorus/course/forest/"the
        # highest"...), so no word-list can catch them all. But the *only* spoken
        # "<x> mode" command in Chibi is the Horus entry, so treat any short
        # utterance ending in "mode" as the trigger (excluding "chibi mode",
        # which is an exit phrase). Stray "<x> mode" noise can't spiral anymore
        # now that the mic is muted while Chibi speaks.
        words = re.findall(r"[a-z']+", lower)
        if words and words[-1] == "mode" and len(words) <= 3 and "chibi" not in words:
            self._enter_horus_mode(auto=False)
            return True
        # Bare name with no "mode" — still catch obvious single-word mishears.
        if any(_sounds_like_horus(w) for w in words) and len(words) <= 2:
            self._enter_horus_mode(auto=False)
            return True
        return False

    def _generate_stars(self, count):
        import random
        stars = []
        for _ in range(count):
            stars.append({
                'x': random.randint(0, self.config.window_width),
                'y': random.randint(0, self.config.window_height),
                'size': random.uniform(1, 3),
                'speed': random.uniform(0.2, 1.0),
                'phase': random.uniform(0, math.pi * 2),
            })
        return stars

    def _create_scanlines(self):
        surf = pygame.Surface(
            (self.config.window_width, self.config.window_height), pygame.SRCALPHA
        )
        for y in range(0, self.config.window_height, 3):
            pygame.draw.line(surf, (0, 0, 0, 25), (0, y), (self.config.window_width, y))
        return surf

    def set_state(self, new_state: AvatarState):
        if new_state != self.state:
            self.state = new_state
            self.state_timer = 0

    def _voice_is_addressed(self, text: str) -> bool:
        """Decide whether a voice transcription should reach Chibi.

        True if (a) we're mid-conversation — inside the rolling wake window
        opened by the last real exchange, (b) Horus/Thoth mode is active (a
        deliberate dictation session the user opted into), or (c) the line
        names Chibi (or a Whisper mishear of it). Everything else — the TV, a
        passing remark not directed at Chibi — is dropped. This is the primary
        guard against ambient-noise responses.
        """
        if self.alarm.is_ringing:
            return True  # any voice dismisses a ringing alarm (handled downstream)
        if self._voice_names_chibi(text):
            # Explicitly addressed — a real conversation is on. Window-only
            # accepts start counting from zero again.
            self._unaddressed_streak = 0
            return True
        if self.horus_mode or self.security_mode:
            return True
        if time.time() < self._wake_until:
            # Window-only accept. The window re-opens on every exchange, so cap
            # how long a chain of these can run without her name coming up —
            # a human names her now and then; the TV never does.
            cap = getattr(self.config, "wake_window_max_unaddressed", 4)
            if cap and self._unaddressed_streak >= cap:
                self._wake_until = 0.0
                self._unaddressed_streak = 0
                print("[Voice] Conversation window closed "
                      f"({cap} turns without being addressed) — say the name again")
                return False
            self._unaddressed_streak += 1
            return True
        return False

    def _voice_names_chibi(self, text: str) -> bool:
        """True if the line explicitly names Chibi or says the wake word."""
        # Wake word — configurable (default "computer"). Whisper-tiny can't
        # reliably transcribe "Chibi" (it comes out be/TV/CB/baby), so the spoken
        # trigger is a word the model actually hears. A substring match is safe
        # for a long, distinct word; the fuzzy pass catches minor mishears
        # ("computor", "computers") without matching unrelated room/TV speech.
        lower = text.lower()
        wake = getattr(self.config, "wake_word", "computer").lower().strip()
        if wake and wake in lower:
            return True
        words = re.findall(r"[a-z']+", lower)
        # Her actual name also wakes her — the soundalike set + fuzzy matcher
        # catch the ways Whisper-tiny mangles "Chibi" when it does come through.
        if any(_sounds_like_chibi(w) for w in words):
            return True
        return any(
            len(w) >= 4 and difflib.SequenceMatcher(None, w, wake).ratio() >= 0.8
            for w in words
        )

    def _open_wake_window(self):
        """(Re)open the conversation window so follow-ups don't need the name."""
        self._wake_until = time.time() + getattr(
            self.config, "wake_window_seconds", 22.0)

    _LIVE_DATA_KEYWORDS = (
        "weather", "temp", "temperature", "forecast", "rain", "snow", "storm",
        "sunny", "cloudy", "hot", "cold", "humid", "wind", "outside",
        "market", "stock", "stocks", "share", "shares", "price", "crypto",
        "bitcoin", "btc", "ethereum", "eth", "solana", "nasdaq", "dow", "s&p",
        "sp500", "ticker", "portfolio",
        "news", "headline", "headlines",
        "calendar", "schedule", "event", "events", "appointment", "meeting",
        "time", "clock", "date", "what day", "today", "tomorrow",
    )

    def _wants_live_data(self, text: str) -> bool:
        """True if the message is plausibly about weather / markets / news /
        calendar / time, so the live-data block is worth injecting. Matches on
        word boundaries so "sometimes"/"daytime" don't count as "time"."""
        t = text.lower()
        return any(re.search(r"\b" + re.escape(k) + r"\b", t)
                   for k in self._LIVE_DATA_KEYWORDS)

    def _notify_soul_of_feeds(self):
        """Let the soul react to weather flips, fresh news, and big market moves."""
        weather = self.feeds.get_weather()
        cond = weather.condition.lower()
        if cond and cond != "unknown":
            if self._prev_weather_condition and cond != self._prev_weather_condition:
                self.soul.on_weather_change(self._prev_weather_condition, cond, weather)
            self._prev_weather_condition = cond
        news = self.feeds.get_news()
        if news.updated_at and news.updated_at != self._prev_news_updated:
            self._prev_news_updated = news.updated_at
            self.soul.on_news_update(news.headlines)
        market = self.feeds.get_market()
        for tk in market.tickers + market.crypto:
            if abs(tk.change_pct) >= 7.0:
                last = self._market_alerts.get(tk.symbol, 0.0)
                if time.time() - last > 6 * 3600:  # one alert per symbol / 6h
                    self._market_alerts[tk.symbol] = time.time()
                    self.soul.on_market_move(tk.symbol, tk.change_pct)

    def _deliver_impulse(self, impulse: str):
        """Speak a soul impulse — Chibi pipes up on her own. Only called when
        idle, not in Thoth mode, and outside the min-interval throttle."""
        self._last_impulse_spoken = time.time()
        print(f"[Soul] Impulse: {impulse!r}")
        if self.state == AvatarState.SLEEPING:
            self.set_state(AvatarState.IDLE)
        self.conversation.append({"role": "assistant", "content": impulse})
        self.bubble.set_text(impulse)
        if self.voice_out:
            self.voice_out.speak(impulse)
        # the user can answer without the wake word — so a chain that already
        # hit the unaddressed cap must not swallow the answer to a fresh prompt.
        self._unaddressed_streak = 0
        self._open_wake_window()
        self.last_interaction = time.time()

    def send_message(self, text: str):
        """Send a message to the LLM in a background thread."""
        # Any accepted input (typed, voice-addressed, command) is a real
        # interaction — open the conversation window so immediate follow-ups
        # don't need the wake word again.
        self._open_wake_window()
        # ── Alarm dismiss/snooze while ringing ───────────────────────────
        if self.alarm.is_ringing:
            if is_snooze_word(text):
                self.alarm.snooze(5)
                self.bubble.set_text("Okay, 5 more minutes... zzz")
                if self.voice_out:
                    self.voice_out.speak_now("Okay, 5 more minutes.")
                self.set_state(AvatarState.SLEEPING)
                return
            # ANY other input while ringing = dismiss. HAPPY settles back to
            # IDLE from update() — no blocking sleep on the main thread.
            self.alarm.dismiss()
            self.bubble.set_text(f"Good morning {self.config.user_name}! Have a great day! :3")
            if self.voice_out:
                self.voice_out.speak_now(f"Good morning {self.config.user_name}! Have a great day!")
            self.set_state(AvatarState.HAPPY)
            self.last_interaction = time.time()
            return

        # ── Alarm commands ────────────────────────────────────────────────
        alarm_action = is_alarm_request(text)
        if alarm_action == "set":
            target = parse_alarm_time(text)
            if target:
                repeat_days = parse_alarm_repeat(text)
                if repeat_days:
                    target = align_to_repeat_days(target, repeat_days)
                alarm = self.alarm.add_alarm(target, repeat_days=repeat_days)
                if repeat_days:
                    reply = (f"Repeating alarm set for {alarm.time_str} "
                             f"({describe_repeat_days(repeat_days)})! "
                             "I'll wake you up :3")
                else:
                    reply = f"Alarm set for {alarm.time_str}! I'll wake you up :3"
                self.bubble.set_text(reply)
                if self.voice_out:
                    self.voice_out.speak(reply)
                self.set_state(AvatarState.HAPPY)
                self.last_interaction = time.time()
                return
            # Couldn't parse — fall through to LLM

        elif alarm_action == "cancel":
            removed = self.alarm.cancel_next()
            if removed:
                reply = f"Canceled alarm for {removed.time_str}."
            else:
                reply = "No alarms to cancel!"
            self.bubble.set_text(reply)
            if self.voice_out:
                self.voice_out.speak(reply)
            self.last_interaction = time.time()
            return

        elif alarm_action == "list":
            alarms = self.alarm.list_alarms()
            if alarms:
                times = ", ".join(a.time_str for a in alarms)
                reply = f"Your alarms: {times}"
            else:
                reply = "No alarms set!"
            self.bubble.set_text(reply)
            if self.voice_out:
                self.voice_out.speak(reply)
            self.last_interaction = time.time()
            return
        # ── Security mode trigger check ───────────────────────────────────
        # Before Horus: its fallback claims any short "<x> mode" utterance.
        if self._check_security_triggers(text):
            return
        # ── Horus mode trigger check ──────────────────────────────────────
        if self._check_horus_triggers(text):
            return
        # ── Normal message ────────────────────────────────────────────────
        self.conversation.append({"role": "user", "content": text})
        self.set_state(AvatarState.THINKING)
        self.bubble.hide()
        self.is_generating = True
        self.response_text = ""
        self.last_interaction = time.time()

        # Check if this is a vision request
        vision_request = self.vision and is_vision_request(text)

        thread = threading.Thread(
            target=self._generate_response,
            args=(vision_request,),
            daemon=True,
        )
        thread.start()

    # Sentence boundary for streaming TTS: terminal punctuation, optional
    # closing quote/bracket, then whitespace.
    _SENTENCE_END = re.compile(r"[.!?][\"')\]]*\s")

    def _speak_streamed(self, text: str, upto: int) -> int:
        """Queue newly completed sentences in text[upto:] for TTS.
        Returns the new high-water mark into `text`."""
        last_end = upto
        for m in self._SENTENCE_END.finditer(text, upto):
            last_end = m.end()
        if last_end > upto:
            segment = text[upto:last_end].strip()
            if segment:
                self.voice_out.speak(segment)
        return last_end

    def _generate_response(self, vision_request=False):
        """Background thread: stream response from LLM."""
        try:
            # ── Thoth: start the slow RAG fetch up front, concurrently ───────
            # Retrieval's query-embed is the one network hop on the critical
            # path, so kick it off now and let it run alongside the journal
            # write and the local prep below. We join it just before assembling
            # the scribe's prompt. Only the network retrieval is threaded — the
            # lexicon is local and stays synchronous so it's never lost if the
            # embed is slow. No-op (no thread) when RAG is disabled.
            thoth_thread = None
            thoth_passages = {"text": ""}
            dream_text = ""
            if self.horus_mode:
                dream_text = next(
                    (m["content"] for m in reversed(self.conversation)
                     if m["role"] == "user"), ""
                )
                if dream_text and self.thoth.rag is not None:
                    def _fetch_passages(t=dream_text):
                        try:
                            thoth_passages["text"] = self.thoth.retrieve(t)
                        except Exception as e:
                            print(f"[Thoth] retrieval failed ({e}); lexicon only.")
                    thoth_thread = threading.Thread(target=_fetch_passages, daemon=True)
                    thoth_thread.start()

            # Inject live data + memory context
            live_context = self.feeds.get_context()
            memory_context = self.memory.get_context()

            extra_system = ""
            if self.security_mode:
                # Re-read the feed at generation time, not at mode entry: the
                # answer must reflect the system as it is *now*, and the model
                # is told to report only what this block says.
                extra_system += self.config.security_system_prompt
                overview = (self.secfeed.overview() if self.secfeed
                            else "Security monitoring is disabled.")
                extra_system += "\n\n[SECURITY STATUS — live from synguard]\n" + overview
            if self.horus_mode:
                extra_system += self.config.horus_system_prompt
                extra_system += "\n\n" + memory_context
                # Past dreams stay in the journal (F2 viewer), not the prompt, so
                # the scribe focuses on the current account. Opt back in via config
                # to fold recent entries into context. Read BEFORE recording this
                # account so the current dream never appears in its own context.
                if getattr(self.config, "horus_inject_recent_dreams", False):
                    dream_ctx = self.memory.get_dream_context()
                    if dream_ctx:
                        extra_system += "\n\n" + dream_ctx
                # Record the account now, concurrently (memory.save is lock-guarded
                # + atomic). Done before generation so a recounted dream is never
                # lost to an LLM hiccup.
                if dream_text:
                    threading.Thread(target=self.memory.add_dream_entry,
                                     args=(dream_text,), daemon=True).start()
                    # Pull any entries the peer recorded while we were apart;
                    # our just-recorded one propagates back on the peer's next pull.
                    if self.dream_sync:
                        self.dream_sync.sync_soon()
                # Ground the scribe: the lexicon is local + instant; the RAG
                # passages were fetched in parallel above — join them here.
                lexicon = self.thoth.lookup(dream_text) if dream_text else ""
                if thoth_thread is not None:
                    thoth_thread.join(timeout=self.config.thoth_rag_timeout + 5)
                grounding = "\n\n".join(p for p in (lexicon, thoth_passages["text"]) if p)
                if grounding:
                    extra_system += "\n\n" + grounding
            elif memory_context:
                extra_system += "\n\n" + memory_context

            # Soul — mood / relationship context (Chibi aspect only; the
            # scribe stays out of Chibi's inner weather)
            if self.soul and not self.horus_mode and not self.security_mode:
                mood_ctx = self.soul.get_mood_context()
                if mood_ctx:
                    extra_system += "\n\n" + mood_ctx

            # Vision: if requested, capture and describe the scene
            if vision_request and self.vision:
                scene_desc = self.vision.describe_scene()
                if scene_desc:
                    extra_system += (
                        f"\n\n[VISION — what you currently see through your camera]\n"
                        f"{scene_desc}\n"
                        f"Use this to answer {self.config.user_name}'s question about what you see."
                    )
            elif self.vision and self.vision.last_description:
                # Passive awareness — background scene context
                extra_system += (
                    f"\n\n[BACKGROUND SCENE — do NOT mention unless relevant]\n"
                    f"Camera sees: {self.vision.last_description}"
                )

            # Only inject the live weather/market/time block when the latest
            # message is actually about it. Dumping it every turn is what made
            # Chibi regurgitate forecasts and tickers unprompted; gating it
            # removes the temptation entirely for off-topic messages.
            latest_user = next(
                (m["content"] for m in reversed(self.conversation)
                 if m["role"] == "user"), "")
            if (live_context and not self.horus_mode and not self.security_mode
                    and self._wants_live_data(latest_user)):
                extra_system += (
                    "\n\n--- BACKGROUND REFERENCE DATA (DO NOT mention unless asked) ---\n"
                    f"This data is available if {self.config.user_name} asks about weather, time, stocks, or crypto. "
                    "Do NOT volunteer this information. Only use it to answer relevant questions.\n"
                    + live_context
                )
                # Calendar events (via the soul's ICS monitor, if configured)
                if self.soul:
                    cal_ctx = self.soul.calendar.get_context()
                    if cal_ctx:
                        extra_system += "\n" + cal_ctx

            num_predict = (self.config.horus_num_predict if self.horus_mode
                           else self.config.llm_num_predict)

            # Pause the recorder for the whole generate+speak cycle. (The
            # muted flag in update() also guards this; stopping the recorder
            # is belt and braces.)
            if self.voice_in and self.voice_in.is_listening:
                self.voice_in.stop_listening()

            # Streaming TTS: queue each sentence for speech the moment it
            # completes instead of waiting for the full reply — perceived
            # latency drops to time-to-first-sentence.
            stream_tts = self.voice_out is not None
            spoken_upto = 0
            full_response = ""
            for chunk in self.llm.stream_chat(self.conversation,
                                              extra_system=extra_system,
                                              num_predict=num_predict):
                full_response += chunk
                self.response_text = full_response
                if self.state == AvatarState.THINKING:
                    self.set_state(AvatarState.SPEAKING)
                self.bubble.set_text(full_response)
                if stream_tts:
                    spoken_upto = self._speak_streamed(full_response, spoken_upto)

            # Speak the tail after the last sentence boundary. If num_predict
            # clipped the reply mid-sentence, drop the dangling fragment from
            # speech (the bubble still shows the full text).
            if stream_tts:
                tail = full_response[spoken_upto:].strip()
                if tail:
                    if re.search(r"[.!?][\"')\]]*$", tail) or spoken_upto == 0:
                        self.voice_out.speak(tail)
                    else:
                        print(f"[TTS] Skipped clipped tail: {tail[:60]!r}")

            self.conversation.append({"role": "assistant", "content": full_response})
            self.is_generating = False
            # Soul takes note of the exchange (mood shift, topics, milestones)
            if self.soul:
                self.soul.on_interaction(latest_user, full_response)
            # Keep the conversation window open for a beat after Chibi finishes
            # so the user's immediate follow-up doesn't need the wake word again.
            self._open_wake_window()
            # (the Horus journal entry was recorded up front, concurrently)
            # Track interaction
            self.memory.record_interaction()
            self._message_count += 1

            # Extract memories every 6 messages (in separate thread, non-blocking)
            if self._message_count % 6 == 0 and len(self.conversation) >= 4:
                threading.Thread(target=self._extract_memories, daemon=True).start()

            # (speech was already queued sentence-by-sentence during streaming)
            # Briefly show happy, then idle
            self.set_state(AvatarState.HAPPY)
            # Wait for TTS to finish with a hard timeout
            if self.voice_out:
                tts_wait_start = time.time()
                while self.voice_out.busy and (time.time() - tts_wait_start) < 30:
                    time.sleep(0.1)
                # Extra settle time so mic doesn't catch tail end of audio
                time.sleep(0.8)
            else:
                time.sleep(2.0)

            # Resume mic listening
            if self.voice_in and self.config.voice_enabled:
                # Drain any stale transcriptions
                while self.voice_in.get_transcription() is not None:
                    pass
                self.voice_in.start_listening()

            if not self.is_generating:
                self.set_state(AvatarState.IDLE)

        except Exception as e:
            print(f"[LLM] Error: {e}")
            if isinstance(e, ConnectionError):
                self.response_text = ("I can't reach my brain right now... "
                                      "is Ollama running on the PC?")
            else:
                self.response_text = f"[Error: {e}]"
            self.bubble.set_text(self.response_text)
            self.is_generating = False
            self.set_state(AvatarState.CONFUSED)
            time.sleep(3.0)
            if not self.is_generating:
                self.set_state(AvatarState.IDLE)

    def update(self, dt):
        self.state_timer += dt

        # Auto-Thoth threshold (~once a minute; also re-arms after the window)
        self._horus_check_timer += dt
        if self._horus_check_timer >= 60.0:
            self._horus_check_timer = 0.0
            self._check_horus_threshold()

        # Sentinel: narrate verdicts that landed since the last frame.
        self._announce_security_events()

        # ── Alarm ringing check ──────────────────────────────────────────
        if self.alarm.is_ringing and self.state != AvatarState.ALARM:
            self.set_state(AvatarState.ALARM)
            self._alarm_speak_timer = 0
            # Start mic so we can hear dismiss commands
            if self.voice_in and not self.voice_in.is_listening:
                self.voice_in.start_listening()

        if self.state == AvatarState.ALARM:
            if not self.alarm.is_ringing:
                # Alarm was dismissed
                self.set_state(AvatarState.IDLE)
            else:
                # Speak wake message every N seconds
                self._alarm_speak_timer += dt
                interval = self.config.alarm_speak_interval
                if self._alarm_speak_timer >= interval:
                    self._alarm_speak_timer = 0
                    msg = self.alarm.get_next_wake_message()
                    self.bubble.set_text(msg)

                    # Pause mic, speak, resume mic
                    if self.voice_in and self.voice_in.is_listening:
                        self.voice_in.stop_listening()
                    if self.voice_out:
                        self.voice_out.speak_now(msg)
                        # Wait for speech to finish
                        wait_start = time.time()
                        # Non-blocking-ish: don't freeze the main loop too long
                        # The actual wait happens over multiple update cycles
                    # Resume mic after a short delay (handled below)

                # Check voice for dismiss (only when not speaking)
                is_speaking = self.voice_out and self.voice_out.is_speaking if self.voice_out else False
                if not is_speaking:
                    if self.voice_in and not self.voice_in.is_listening:
                        # Drain stale then restart
                        while self.voice_in.get_transcription() is not None:
                            pass
                        self.voice_in.start_listening()

                    if self.voice_in:
                        transcription = self.voice_in.get_transcription()
                        if transcription:
                            if is_snooze_word(transcription):
                                self.alarm.snooze(5)
                                self.bubble.set_text("5 more minutes... zzz")
                                if self.voice_out:
                                    self.voice_out.speak_now("Okay, 5 more minutes.")
                                self.set_state(AvatarState.SLEEPING)
                            else:
                                # Any voice input = dismiss
                                self.alarm.dismiss()
                                self.bubble.set_text(f"Good morning {self.config.user_name}! :3")
                                if self.voice_out:
                                    self.voice_out.speak_now(f"Good morning {self.config.user_name}! Have a great day!")
                                self.set_state(AvatarState.HAPPY)
                                self.last_interaction = time.time()

                # Don't process normal mic/sleep logic during alarm
                return

        # ── Normal update logic ──────────────────────────────────────────
        # Poll voice input — BUT only when we're not speaking or generating
        is_speaking = self.voice_out and self.voice_out.is_speaking if self.voice_out else False
        if is_speaking:
            self._last_spoke_at = time.time()
        # Half-duplex echo guard: the mic (a USB cam beside the speaker) picks up
        # Chibi's own TTS, which Whisper would transcribe and feed back as fake
        # input — a runaway loop (it recites memory to itself). Mute the recorder
        # while speaking/generating and for a short cooldown after (the TTS tail
        # is captured a beat past is_speaking clearing), so that audio is dropped
        # at the source instead of looping back.
        echo_cooldown = getattr(self.config, "mic_echo_cooldown", 1.0)
        mic_safe = (not self.is_generating and not is_speaking
                    and time.time() - self._last_spoke_at > echo_cooldown)
        if self.voice_in:
            self.voice_in.muted = not mic_safe

        if self.voice_in and mic_safe:
            # Show listening state when mic is active
            if self.voice_in.is_recording and self.state == AvatarState.IDLE:
                self.set_state(AvatarState.LISTENING)
            elif not self.voice_in.is_recording and self.state == AvatarState.LISTENING:
                self.set_state(AvatarState.IDLE)

            transcription = self.voice_in.get_transcription()
            if transcription:
                if self._voice_is_addressed(transcription):
                    print(f"[Voice] Heard: {transcription!r}")
                    self.send_message(transcription)
                else:
                    # Not addressed and the conversation window is closed —
                    # almost always the TV / ambient chatter. Drop it silently.
                    print(f"[Voice] Ignored (not addressed): {transcription!r}")
        elif self.voice_in and not mic_safe:
            # Drain any transcriptions that came in while speaking (they're just echo)
            while self.voice_in.get_transcription() is not None:
                pass

        # HAPPY is transient — settle back to IDLE once speech is done
        # (the alarm-dismiss path relies on this instead of a blocking sleep).
        if (self.state == AvatarState.HAPPY and not self.is_generating
                and not (self.voice_out and self.voice_out.busy)
                and self.state_timer > 2.0):
            self.set_state(AvatarState.IDLE)

        # openWakeWord fired — open the conversation window, same as if the
        # wake word had been transcribed.
        if self.voice_in and self.voice_in.consume_wake_detection():
            print("[Voice] Wake word detected (openWakeWord)")
            self._unaddressed_streak = 0
            self._open_wake_window()
            if self.state == AvatarState.SLEEPING:
                self.set_state(AvatarState.IDLE)

        # ── Soul: feed observers + spontaneous impulses ──────────────────
        if self.soul:
            self._soul_feed_timer += dt
            if self._soul_feed_timer >= 10.0:
                self._soul_feed_timer = 0.0
                self._notify_soul_of_feeds()
            if (getattr(self.config, "impulses_enabled", True)
                    and not self.is_generating and not self.horus_mode
                    and not self.security_mode
                    and self.state in (AvatarState.IDLE, AvatarState.SLEEPING)
                    and not (self.voice_out and self.voice_out.busy)
                    and time.time() - self._last_impulse_spoken
                        > getattr(self.config, "impulse_min_interval", 300.0)):
                impulse = self.soul.get_impulse()
                if impulse:
                    self._deliver_impulse(impulse)

        # Auto-sleep after inactivity
        if (self.state == AvatarState.IDLE and
                time.time() - self.last_interaction > self.config.sleep_timeout):
            self.set_state(AvatarState.SLEEPING)

        # Wake from sleep on any input
        if self.state == AvatarState.SLEEPING and self.input_box.text:
            self.set_state(AvatarState.IDLE)
            self.last_interaction = time.time()

        # Emit particles based on state
        cx = self.config.window_width // 2
        cy = self.config.window_height // 2 - 20

        if self.state == AvatarState.THINKING and self.state_timer % 0.15 < dt:
            self.particles.emit(cx, cy - 60, count=2, color=self.config.neon_secondary, spread=1.5, life=0.8, size=2)

        if self.state == AvatarState.HAPPY and self.state_timer % 0.1 < dt:
            self.particles.emit(cx, cy - 40, count=3, color=(255, 200, 50), spread=3, life=1.2, size=2.5)

        if self.state == AvatarState.SPEAKING and self.state_timer % 0.25 < dt:
            self.particles.emit(cx, cy - 70, count=1, color=self.config.neon_primary, spread=1, life=0.6, size=2)

        self.particles.update(dt)
        self.bubble.update(dt)
        self.input_box.update(dt)

        # Weather-reactive particles
        weather = self.feeds.get_weather()
        w_cond = weather.condition.lower()
        import random

        if w_cond in ("rain", "drizzle", "shower") and random.random() < 0.4:
            # Rain drops falling
            rx = random.randint(0, self.config.window_width)
            self.weather_particles.append({
                'x': rx, 'y': 0,
                'vx': random.uniform(-0.5, 0.5),
                'vy': random.uniform(4, 8),
                'life': 1.0,
                'type': 'rain',
            })

        elif w_cond in ("snow", "sleet") and random.random() < 0.3:
            rx = random.randint(0, self.config.window_width)
            self.weather_particles.append({
                'x': rx, 'y': 0,
                'vx': random.uniform(-1, 1),
                'vy': random.uniform(0.5, 2),
                'life': 1.0,
                'type': 'snow',
                'size': random.uniform(2, 5),
            })

        elif w_cond in ("storm", "thunderstorm") and random.random() < 0.003:
            # Lightning flash
            self.lightning_flash = 0.15

        # Update weather particles
        new_wp = []
        for wp in self.weather_particles:
            wp['x'] += wp['vx']
            wp['y'] += wp['vy']
            wp['life'] -= dt * 0.5
            if wp['y'] < self.config.window_height and wp['life'] > 0:
                new_wp.append(wp)
        self.weather_particles = new_wp[:300]  # cap particle count

        # Update lightning
        if self.lightning_flash > 0:
            self.lightning_flash -= dt

    def draw_background(self, t):
        # The sentinel sheds the scene entirely — no stars, no neon grid, no
        # weather. A bare dark field, so the only thing moving on screen is the
        # security state itself. (Hence the early return: unlike Thoth below,
        # which keeps the ambience, this aspect deliberately skips it.)
        if self.security_mode:
            self.screen.fill(self.config.security_bg_color)
            return
        # In the Thoth aspect the neon void deepens to indigo and a vast,
        # faint Eye of Horus presides over the scene.
        if self.horus_mode:
            self.screen.fill(self.config.horus_bg_color)
            wm_size = int(self.config.window_height * 0.32)
            wm_alpha = int(22 + 8 * math.sin(t * 0.8))
            # Cache the eye watermark. Its thick arcs + a per-frame 490x428
            # surface alloc were the bulk of what pegged the Pi's CPU in Horus
            # mode, dropping the render below interactive fps (so voice "exit"
            # was never serviced). Draw it once at full alpha; blit each frame
            # with just the pulsing alpha.
            eye = getattr(self, "_horus_eye_surf", None)
            if eye is None:
                ew, eh = int(wm_size * 3.2), int(wm_size * 2.8)
                eye = pygame.Surface((ew, eh), pygame.SRCALPHA)
                self.renderer._draw_eye_of_horus(
                    eye, ew // 2, eh // 2, wm_size,
                    self.config.horus_gold, 255, glow=False,
                )
                self._horus_eye_surf = eye
            eye.set_alpha(wm_alpha)
            self.screen.blit(
                eye,
                (self.config.window_width // 2 - eye.get_width() // 2,
                 int(self.config.window_height * 0.40) - eye.get_height() // 2),
            )
        else:
            self.screen.fill(self.config.bg_color)

        # Lightning flash
        if self.lightning_flash > 0:
            flash_alpha = int(200 * (self.lightning_flash / 0.15))
            flash_surf = pygame.Surface(
                (self.config.window_width, self.config.window_height), pygame.SRCALPHA
            )
            flash_surf.fill((200, 200, 255, flash_alpha))
            self.screen.blit(flash_surf, (0, 0))

        # Animated stars (dimmed during rain/snow)
        weather = self.feeds.get_weather()
        star_dim = 0.3 if weather.condition.lower() in ("rain", "snow", "storm", "overcast") else 1.0

        for star in self.bg_stars:
            brightness = int((120 + 80 * math.sin(t * star['speed'] + star['phase'])) * star_dim)
            c = self.config.neon_primary
            color = (
                min(255, c[0] * brightness // 255),
                min(255, c[1] * brightness // 255),
                min(255, c[2] * brightness // 255),
            )
            size = max(1, int(star['size'] * (0.7 + 0.3 * math.sin(t * star['speed']))))
            pygame.draw.circle(self.screen, color, (star['x'], star['y']), size)

        # Subtle grid — static, so build it once and reuse. Rebuilding the
        # full-screen surface + 30+ draw.line calls every frame was a big chunk
        # of the per-frame render cost that starved the loop (badly enough in
        # Horus mode that voice input stopped being serviced).
        if getattr(self, "_grid_surf", None) is None:
            grid_alpha = 15
            gs = pygame.Surface(
                (self.config.window_width, self.config.window_height), pygame.SRCALPHA
            )
            for x in range(0, self.config.window_width, 40):
                pygame.draw.line(gs, (*self.config.neon_primary, grid_alpha), (x, 0), (x, self.config.window_height))
            for y in range(0, self.config.window_height, 40):
                pygame.draw.line(gs, (*self.config.neon_primary, grid_alpha), (0, y), (self.config.window_width, y))
            self._grid_surf = gs
        self.screen.blit(self._grid_surf, (0, 0))

        # Draw weather particles
        for wp in self.weather_particles:
            if wp['type'] == 'rain':
                alpha = int(150 * wp['life'])
                pygame.draw.line(
                    self.screen, (100, 150, 255),
                    (int(wp['x']), int(wp['y'])),
                    (int(wp['x'] + wp['vx'] * 2), int(wp['y'] + wp['vy'] * 2)),
                    1,
                )
            elif wp['type'] == 'snow':
                alpha = int(200 * wp['life'])
                size = max(1, int(wp.get('size', 3) * wp['life']))
                snow_surf = pygame.Surface((size * 2 + 2, size * 2 + 2), pygame.SRCALPHA)
                pygame.draw.circle(snow_surf, (220, 230, 255, alpha),
                                   (size + 1, size + 1), size)
                self.screen.blit(snow_surf, (int(wp['x']) - size, int(wp['y']) - size))

    # --- Window controls -------------------------------------------------
    #
    # Chibi normally comes up fullscreen, which under a Wayland compositor
    # means no titlebar and therefore no close button. ESC has always quit,
    # but nothing on screen said so and there was nothing to click. These draw
    # a real quit button plus a fullscreen toggle, so the app can be dropped
    # into a normal window and closed from its titlebar too.

    _WINCTL_SIZE = 26
    _WINCTL_MARGIN = 10

    def _window_control_rects(self):
        """Return (close_rect, restore_rect), laid out top-right."""
        size = self._WINCTL_SIZE
        m = self._WINCTL_MARGIN
        w = self.config.window_width
        close = pygame.Rect(w - m - size, m, size, size)
        restore = pygame.Rect(close.left - (size + 6), m, size, size)
        return close, restore

    def _draw_window_controls(self):
        close_rect, restore_rect = self._window_control_rects()
        if not hasattr(self, "_winctl_font"):
            self._winctl_font = pygame.font.SysFont("monospace", 16, bold=True)

        mouse = pygame.mouse.get_pos()
        for rect, glyph, hot in (
            (restore_rect, "□", (90, 190, 255)),
            (close_rect, "×", (255, 80, 110)),
        ):
            hovered = rect.collidepoint(mouse)
            bg = hot if hovered else (28, 28, 40)
            fg = (10, 10, 16) if hovered else hot
            pygame.draw.rect(self.screen, bg, rect, border_radius=5)
            pygame.draw.rect(self.screen, hot, rect, 1, border_radius=5)
            surf = self._winctl_font.render(glyph, True, fg)
            self.screen.blit(surf, surf.get_rect(center=rect.center))

    def _toggle_fullscreen(self):
        """Flip between fullscreen and a normal window.

        Windowed mode gives the compositor something to put a titlebar on, so
        the usual close button works. We rebuild the surface rather than using
        pygame.display.toggle_fullscreen(), which is unreliable under SDL's
        Wayland backend, and re-adopt the resulting size so layout follows.
        """
        self.config.fullscreen = not self.config.fullscreen
        try:
            self.screen = self._init_display()
        except pygame.error as e:
            print(f"[Display] fullscreen toggle failed: {e}")
            self.config.fullscreen = not self.config.fullscreen
            return
        self._adopt_surface_size(self.screen)

    def _handle_window_control_click(self, pos):
        """Return True if the click was consumed by a window control."""
        close_rect, restore_rect = self._window_control_rects()
        if close_rect.collidepoint(pos):
            self.running = False
            return True
        if restore_rect.collidepoint(pos):
            self._toggle_fullscreen()
            return True
        return False

    def run(self):
        while self.running:
            dt = self.clock.tick(self.config.target_fps) / 1000.0
            t = time.time()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    continue

                # A tiling compositor resizes us AFTER the window maps, so
                # adopting the size once in _init_display is not enough — the
                # configure that matters arrives here, a frame or two later.
                if event.type == pygame.VIDEORESIZE:
                    self._adopt_surface_size(pygame.display.get_surface())
                    continue

                # Window controls are drawn above every overlay, so they must
                # get first refusal on clicks — including while the dream
                # journal has input captured.
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self._handle_window_control_click(event.pos):
                        continue

                if event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                    self._toggle_fullscreen()
                    continue

                # Dream journal overlay captures all input while open.
                if self.dream_view_open:
                    if event.type == pygame.KEYDOWN:
                        self._handle_dream_view_key(event)
                    continue

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.running = False
                    elif event.key == pygame.K_F1:
                        # Toggle voice input
                        if self.voice_in:
                            if self.voice_in.is_listening:
                                self.voice_in.stop_listening()
                            else:
                                self.voice_in.start_listening()
                    elif event.key == pygame.K_F2:
                        # Open the dream journal viewer
                        self._open_dream_view()
                    elif self.state == AvatarState.ALARM:
                        # Any keypress dismisses alarm
                        self.alarm.dismiss()
                        self.bubble.set_text(f"Good morning {self.config.user_name}! :3")
                        if self.voice_out:
                            self.voice_out.speak_now(f"Good morning {self.config.user_name}!")
                        self.set_state(AvatarState.HAPPY)
                        self.last_interaction = time.time()

                submitted = self.input_box.handle_event(event)
                if submitted and not self.is_generating:
                    # Typed input is unmistakably the user — reset the
                    # window-only voice-accept chain along with sending.
                    self._unaddressed_streak = 0
                    self.send_message(submitted)

            self.update(dt)

            # Draw
            self.draw_background(t)

            cx = self.config.window_width // 2
            cy = self.config.window_height // 2 + 20

            # Draw chibi
            self.renderer.draw(self.screen, cx, cy, self.state, self.state_timer, t,
                               horus_mode=self.horus_mode)

            # Particles on top of chibi
            self.particles.draw(self.screen)

            # Chat bubble
            self.bubble.draw(self.screen, cx, cy - 100)

            # ── Alarm visual overlay ─────────────────────────────────────
            if self.state == AvatarState.ALARM:
                # Pulsing screen border
                pulse = abs(math.sin(t * 4))
                border_alpha = int(100 + 155 * pulse)
                border_color = (255, 200, 50)  # Warm amber

                border_surf = pygame.Surface(
                    (self.config.window_width, self.config.window_height), pygame.SRCALPHA
                )
                # Thick pulsing border
                bw = int(4 + pulse * 4)
                pygame.draw.rect(border_surf, (*border_color, border_alpha),
                                 (0, 0, self.config.window_width, self.config.window_height),
                                 width=bw, border_radius=4)
                self.screen.blit(border_surf, (0, 0))

                # Alarm text at top
                if not hasattr(self, '_alarm_font'):
                    self._alarm_font = pygame.font.SysFont("monospace", 28, bold=True)
                    self._alarm_font_sm = pygame.font.SysFont("monospace", 16)

                # Wobble the text
                wobble = math.sin(t * 6) * 3
                alarm_text = "WAKE UP!"
                at_surf = self._alarm_font.render(alarm_text, True, border_color)
                atx = self.config.window_width // 2 - at_surf.get_width() // 2
                self.screen.blit(at_surf, (atx, 60 + int(wobble)))

                # Sun emoji / hint
                hint = self._alarm_font_sm.render(
                    "Press any key or say something to dismiss", True, (180, 160, 100)
                )
                hx = self.config.window_width // 2 - hint.get_width() // 2
                self.screen.blit(hint, (hx, 92))

                # Subtle warm tint over the whole screen
                tint = pygame.Surface(
                    (self.config.window_width, self.config.window_height), pygame.SRCALPHA
                )
                tint.fill((255, 200, 50, int(15 * pulse)))
                self.screen.blit(tint, (0, 0))

            # ── Thoth aspect overlay ─────────────────────────────────────
            # A quiet gold vignette + sigil label. Alarm takes visual priority.
            if self.horus_mode and self.state != AvatarState.ALARM:
                if not hasattr(self, '_thoth_font'):
                    self._thoth_font = pygame.font.SysFont("serif", 22, bold=True)

                gold = self.config.horus_gold
                breath = 0.5 + 0.5 * math.sin(t * 1.2)

                vign = pygame.Surface(
                    (self.config.window_width, self.config.window_height), pygame.SRCALPHA
                )
                pygame.draw.rect(
                    vign, (*gold, int(50 + 40 * breath)),
                    (0, 0, self.config.window_width, self.config.window_height),
                    width=2, border_radius=4,
                )
                self.screen.blit(vign, (0, 0))

                label = self._thoth_font.render("— THOTH —", True, gold)
                label.set_alpha(int(150 + 80 * breath))
                lx = self.config.window_width // 2 - label.get_width() // 2
                self.screen.blit(label, (lx, 18))

            # ── Sentinel aspect overlay ──────────────────────────────────
            # Amber vignette, going red once synguard has actually blocked
            # something — the frame colour is real state, not decoration.
            if self.security_mode and self.state != AvatarState.ALARM:
                if not hasattr(self, '_sentinel_font'):
                    self._sentinel_font = pygame.font.SysFont("monospace", 20, bold=True)

                blocked = bool(self.secfeed and any(
                    e.notable for e in self.secfeed.recent(20)))
                hue = (self.config.security_red if blocked
                       else self.config.security_amber)
                # Blocked traffic pulses fast and urgently; a quiet system breathes.
                breath = 0.5 + 0.5 * math.sin(t * (4.0 if blocked else 1.2))

                vign = pygame.Surface(
                    (self.config.window_width, self.config.window_height), pygame.SRCALPHA
                )
                pygame.draw.rect(
                    vign, (*hue, int(50 + 40 * breath)),
                    (0, 0, self.config.window_width, self.config.window_height),
                    width=2, border_radius=4,
                )
                self.screen.blit(vign, (0, 0))

                text = "— SENTINEL —"
                if self.secfeed and not self.secfeed.available:
                    text = "— SENTINEL: NO FEED —"
                label = self._sentinel_font.render(text, True, hue)
                label.set_alpha(int(150 + 80 * breath))
                lx = self.config.window_width // 2 - label.get_width() // 2
                self.screen.blit(label, (lx, 18))

            # Scanlines overlay
            if self.config.scanlines:
                self.screen.blit(self.scanline_surf, (0, 0))

            # HUD — weather + market overlays
            self.hud.draw(
                self.screen,
                self.feeds.get_weather(),
                self.feeds.get_market(),
                t, dt,
            )

            # Camera PiP thumbnail (bottom-right corner)
            if self.vision and self.config.vision_pip:
                pip_w, pip_h = 120, 90
                # Decoding the JPEG every frame (cv2 imdecode+resize+cvtColor) was
                # a heavy chunk of the per-frame cost on the Pi. The camera only
                # refreshes a few times a second anyway, so decode at ~6 fps and
                # reuse the cached thumbnail surface in between.
                self._pip_decode_count = getattr(self, "_pip_decode_count", 0) + 1
                if self._pip_decode_count % 5 == 0 or not hasattr(self, "_pip_surf"):
                    frame_bytes = self.vision.get_frame_for_display()
                    if frame_bytes:
                        try:
                            import cv2
                            import numpy as np
                            nparr = np.frombuffer(frame_bytes, np.uint8)
                            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                            if img is not None:
                                img = cv2.resize(img, (pip_w, pip_h))
                                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                                self._pip_surf = pygame.image.frombuffer(
                                    img.tobytes(), (pip_w, pip_h), 'RGB'
                                )
                        except Exception:
                            pass  # Silent fail — PiP is optional eye candy
                pip_surf = getattr(self, "_pip_surf", None)
                if pip_surf is not None:
                    # Position: bottom-right, above input box
                    px = self.config.window_width - pip_w - 12
                    py = self.config.window_height - pip_h - 100
                    # Border
                    border_rect = pygame.Rect(px - 2, py - 2, pip_w + 4, pip_h + 4)
                    pygame.draw.rect(self.screen, self.config.neon_primary,
                                     border_rect, 1, border_radius=4)
                    self.screen.blit(pip_surf, (px, py))
                    # Label
                    if not hasattr(self, '_pip_font'):
                        self._pip_font = pygame.font.SysFont("monospace", 10)
                    cam_label = self._pip_font.render("CAM", True, self.config.neon_primary)
                    self.screen.blit(cam_label, (px + 2, py + 2))

            # UI
            self.status_bar.draw(self.screen, self.state, self.llm.connected,
                                 self.voice_in, self.voice_out)
            self.input_box.draw(self.screen)

            # Dream journal viewer sits on top of everything else.
            if self.dream_view_open:
                self._draw_dream_journal()

            # Window controls go above even the dream journal, so there is
            # always a visible way out.
            self._draw_window_controls()

            pygame.display.flip()

        pygame.quit()
        # Final memory extraction and save — skipped when the LLM is
        # unreachable, so quitting can't block on a long network timeout.
        if self.llm.connected and len(self.conversation) >= 2:
            print("[Memory] Extracting final memories...")
            self._extract_memories()
        self.memory.save()
        # Cleanup
        if self.soul:
            self.soul.cleanup()
        if self.dream_sync:
            self.dream_sync.stop()
        self.feeds.stop()
        self.alarm.stop()
        if self.vision:
            self.vision.stop()
        if self.secfeed:
            self.secfeed.stop()
        if self.voice_in:
            self.voice_in.cleanup()
        if self.voice_out:
            self.voice_out.cleanup()
        sys.exit()

# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = ChibiAvatarApp()
    app.run()
