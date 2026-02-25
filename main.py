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
import textwrap
from enum import Enum, auto
from dataclasses import dataclass, field

from llm_client import LLMClient
from sprite_renderer import ChibiRenderer
from voice_input import VoiceInput
from voice_output import VoiceOutput
from data_feeds import DataFeedManager
from hud_overlay import HUDOverlay
from memory import PersistentMemory
from vision import Vision, is_vision_request
from alarm import AlarmManager, is_alarm_request, is_dismiss_word, is_snooze_word, parse_alarm_time
from config import Config

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
        self.clock_font = pygame.font.SysFont("monospace", 22, bold=True)

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

        # Date under clock
        date_str = now.strftime("%a %b %d")
        date_surf = self.font.render(date_str, True, (80, 100, 120))
        surface.blit(date_surf, (14, 30))

        # Connection status dot (next to date)
        dot_color = (0, 255, 100) if connected else (255, 60, 60)
        status_text = f"● {state.name}"
        text_surf = self.font.render(status_text, True, dot_color)
        surface.blit(text_surf, (14, 46))

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
        hint = self.font.render("[F1] mic  [ESC] quit", True, (35, 35, 50))
        surface.blit(hint, (12, surface.get_height() - 18))

# ─── Main App ────────────────────────────────────────────────────────────────

class ChibiAvatarApp:
    def __init__(self):
        self.config = Config()
        pygame.init()

        flags = 0
        if self.config.fullscreen:
            flags = pygame.FULLSCREEN

        self.screen = pygame.display.set_mode(
            (self.config.window_width, self.config.window_height), flags
        )
        pygame.display.set_caption("Chibi LLM Avatar")

        self.clock = pygame.time.Clock()
        self.running = True

        # State
        self.state = AvatarState.IDLE
        self.state_timer = 0
        self.last_interaction = time.time()

        # Components
        self.renderer = ChibiRenderer(self.config)
        self.particles = ParticleSystem()
        self.bubble = ChatBubble(self.config)
        self.input_box = InputBox(self.config)
        self.status_bar = StatusBar(self.config)
        self.llm = LLMClient(self.config)

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

        # Conversation
        self.conversation: list[dict] = []
        self.response_text = ""
        self.is_generating = False

    def _extract_memories(self):
        """Ask the LLM to extract memorable facts from recent conversation."""
        try:
            prompt = self.memory.get_extraction_prompt(self.conversation)
            result = ""
            for chunk in self.llm.stream_chat(
                [{"role": "user", "content": prompt}],
                extra_system="You are a memory extraction assistant. Return ONLY valid JSON."
            ):
                result += chunk
            self.memory.process_extraction(result)
        except Exception as e:
            print(f"[Memory] Extraction failed: {e}")

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

    def send_message(self, text: str):
        """Send a message to the LLM in a background thread."""
        # ── Alarm dismiss/snooze while ringing ───────────────────────────
        if self.alarm.is_ringing:
            if is_snooze_word(text):
                self.alarm.snooze(5)
                self.bubble.set_text("Okay, 5 more minutes... zzz")
                if self.voice_out:
                    self.voice_out.speak_now("Okay, 5 more minutes.")
                self.set_state(AvatarState.SLEEPING)
                return
            elif is_dismiss_word(text) or True:
                # ANY voice input while ringing = dismiss
                self.alarm.dismiss()
                self.bubble.set_text("Good morning Velle! Have a great day! :3")
                if self.voice_out:
                    self.voice_out.speak_now("Good morning Velle! Have a great day!")
                self.set_state(AvatarState.HAPPY)
                self.last_interaction = time.time()
                time.sleep(2)
                self.set_state(AvatarState.IDLE)
                return

        # ── Alarm commands ────────────────────────────────────────────────
        alarm_action = is_alarm_request(text)
        if alarm_action == "set":
            target = parse_alarm_time(text)
            if target:
                alarm = self.alarm.add_alarm(target)
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

    def _generate_response(self, vision_request=False):
        """Background thread: stream response from LLM."""
        try:
            # Inject live data + memory context
            live_context = self.feeds.get_context()
            memory_context = self.memory.get_context()

            extra_system = ""
            if memory_context:
                extra_system += "\n\n" + memory_context

            # Vision: if requested, capture and describe the scene
            if vision_request and self.vision:
                scene_desc = self.vision.describe_scene()
                if scene_desc:
                    extra_system += (
                        f"\n\n[VISION — what you currently see through your camera]\n"
                        f"{scene_desc}\n"
                        f"Use this to answer Velle's question about what you see."
                    )
            elif self.vision and self.vision.last_description:
                # Passive awareness — background scene context
                extra_system += (
                    f"\n\n[BACKGROUND SCENE — do NOT mention unless relevant]\n"
                    f"Camera sees: {self.vision.last_description}"
                )

            if live_context:
                extra_system += (
                    "\n\n--- BACKGROUND REFERENCE DATA (DO NOT mention unless asked) ---\n"
                    "This data is available if Velle asks about weather, time, stocks, or crypto. "
                    "Do NOT volunteer this information. Only use it to answer relevant questions.\n"
                    + live_context
                )

            full_response = ""
            for chunk in self.llm.stream_chat(self.conversation, extra_system=extra_system):
                full_response += chunk
                self.response_text = full_response
                if self.state == AvatarState.THINKING:
                    self.set_state(AvatarState.SPEAKING)
                    self.bubble.set_text(full_response)
                else:
                    self.bubble.set_text(full_response)

            self.conversation.append({"role": "assistant", "content": full_response})
            self.is_generating = False

            # Track interaction
            self.memory.record_interaction()
            self._message_count += 1

            # Extract memories every 6 messages (in separate thread, non-blocking)
            if self._message_count % 6 == 0 and len(self.conversation) >= 4:
                threading.Thread(target=self._extract_memories, daemon=True).start()

            # Pause mic before speaking to prevent feedback loop
            if self.voice_in and self.voice_in.is_listening:
                self.voice_in.stop_listening()

            # Speak the response
            if self.voice_out and full_response:
                self.voice_out.speak(full_response)

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
            self.response_text = f"[Error: {e}]"
            self.bubble.set_text(self.response_text)
            self.is_generating = False
            self.set_state(AvatarState.CONFUSED)
            time.sleep(3.0)
            if not self.is_generating:
                self.set_state(AvatarState.IDLE)

    def update(self, dt):
        self.state_timer += dt

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
                                self.bubble.set_text("Good morning Velle! :3")
                                if self.voice_out:
                                    self.voice_out.speak_now("Good morning Velle! Have a great day!")
                                self.set_state(AvatarState.HAPPY)
                                self.last_interaction = time.time()

                # Don't process normal mic/sleep logic during alarm
                return

        # ── Normal update logic ──────────────────────────────────────────
        # Poll voice input — BUT only when we're not speaking or generating
        is_speaking = self.voice_out and self.voice_out.is_speaking if self.voice_out else False
        mic_safe = not self.is_generating and not is_speaking

        if self.voice_in and mic_safe:
            # Show listening state when mic is active
            if self.voice_in.is_recording and self.state == AvatarState.IDLE:
                self.set_state(AvatarState.LISTENING)
            elif not self.voice_in.is_recording and self.state == AvatarState.LISTENING:
                self.set_state(AvatarState.IDLE)

            transcription = self.voice_in.get_transcription()
            if transcription:
                self.send_message(transcription)
        elif self.voice_in and not mic_safe:
            # Drain any transcriptions that came in while speaking (they're just echo)
            while self.voice_in.get_transcription() is not None:
                pass

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

        # Subtle grid
        grid_alpha = 15
        grid_surf = pygame.Surface(
            (self.config.window_width, self.config.window_height), pygame.SRCALPHA
        )
        for x in range(0, self.config.window_width, 40):
            pygame.draw.line(grid_surf, (*self.config.neon_primary, grid_alpha), (x, 0), (x, self.config.window_height))
        for y in range(0, self.config.window_height, 40):
            pygame.draw.line(grid_surf, (*self.config.neon_primary, grid_alpha), (0, y), (self.config.window_width, y))
        self.screen.blit(grid_surf, (0, 0))

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

    def run(self):
        while self.running:
            dt = self.clock.tick(self.config.target_fps) / 1000.0
            t = time.time()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.running = False
                    elif event.key == pygame.K_F1:
                        # Toggle voice input
                        if self.voice_in:
                            if self.voice_in.is_listening:
                                self.voice_in.stop_listening()
                            else:
                                self.voice_in.start_listening()
                    elif self.state == AvatarState.ALARM:
                        # Any keypress dismisses alarm
                        self.alarm.dismiss()
                        self.bubble.set_text("Good morning Velle! :3")
                        if self.voice_out:
                            self.voice_out.speak_now("Good morning Velle!")
                        self.set_state(AvatarState.HAPPY)
                        self.last_interaction = time.time()

                submitted = self.input_box.handle_event(event)
                if submitted and not self.is_generating:
                    self.send_message(submitted)

            self.update(dt)

            # Draw
            self.draw_background(t)

            cx = self.config.window_width // 2
            cy = self.config.window_height // 2 + 20

            # Draw chibi
            self.renderer.draw(self.screen, cx, cy, self.state, self.state_timer, t)

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
                frame_bytes = self.vision.get_frame_for_display()
                if frame_bytes:
                    try:
                        import cv2
                        import numpy as np
                        nparr = np.frombuffer(frame_bytes, np.uint8)
                        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                        if img is not None:
                            # Resize for PiP
                            pip_w, pip_h = 120, 90
                            img = cv2.resize(img, (pip_w, pip_h))
                            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                            pip_surf = pygame.image.frombuffer(
                                img.tobytes(), (pip_w, pip_h), 'RGB'
                            )
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
                    except Exception:
                        pass  # Silent fail — PiP is optional eye candy

            # UI
            self.status_bar.draw(self.screen, self.state, self.llm.connected,
                                 self.voice_in, self.voice_out)
            self.input_box.draw(self.screen)

            pygame.display.flip()

        pygame.quit()
        # Final memory extraction and save
        if len(self.conversation) >= 2:
            print("[Memory] Extracting final memories...")
            self._extract_memories()
        self.memory.save()
        # Cleanup
        self.feeds.stop()
        self.alarm.stop()
        if self.vision:
            self.vision.stop()
        if self.voice_in:
            self.voice_in.cleanup()
        if self.voice_out:
            self.voice_out.cleanup()
        sys.exit()

# ─── Entry Point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = ChibiAvatarApp()
    app.run()
