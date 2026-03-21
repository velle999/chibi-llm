"""
Chibi Renderer v3 — KAWAII ENHANCED EDITION
Now with: breathing animation, pulsing outline glow, natural blink timing,
wake-up transition (! pop), scale pulse, micro-animations per state.
"""

import pygame
import math
import random
from config import Config


class ChibiRenderer:
    def __init__(self, config: Config):
        self.config = config
        self.scale = config.chibi_scale
        self.floaties: list[dict] = []
        self.floaty_timer = 0

        # Blink system — randomized interval for natural feel
        self.blink_timer = 0
        self.is_blinking = False
        self._next_blink = random.uniform(2.5, 5.5)
        self._blink_stage = 0  # 0=open, 1=closing, 2=closed, 3=opening
        self._blink_progress = 0.0

        # Wake transition
        self.wake_transition = 0.0  # 0 = not waking, >0 = animating
        self._prev_state = "IDLE"
        self._wake_particles: list[dict] = []

        # Breathing (used in multiple states)
        self._breath_phase = 0.0

        # Outline glow pulse
        self._glow_pulse = 0.0

    # ─── Primitives ──────────────────────────────────────────────────────

    def _glow_circle(self, surface, color, center, radius, glow_radius=None, alpha=60):
        if glow_radius is None:
            glow_radius = radius + 8
        gs = pygame.Surface((glow_radius * 2 + 4, glow_radius * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(gs, (*color[:3], alpha), (glow_radius + 2, glow_radius + 2), glow_radius)
        surface.blit(gs, (center[0] - glow_radius - 2, center[1] - glow_radius - 2))
        pygame.draw.circle(surface, color, center, radius)

    def _draw_star(self, surface, cx, cy, size, color, rotation=0):
        points = []
        for i in range(8):
            angle = math.radians(i * 45 + rotation)
            r = size if i % 2 == 0 else size * 0.35
            points.append((cx + math.cos(angle) * r, cy + math.sin(angle) * r))
        if len(points) >= 3:
            pygame.draw.polygon(surface, color, points)

    def _draw_heart(self, surface, cx, cy, size, color, alpha=255):
        hs = pygame.Surface((int(size * 3), int(size * 3)), pygame.SRCALPHA)
        hcx, hcy = int(size * 1.5), int(size * 1.5)
        s = size
        pygame.draw.circle(hs, (*color, alpha), (hcx - int(s * 0.35), hcy - int(s * 0.15)), int(s * 0.5))
        pygame.draw.circle(hs, (*color, alpha), (hcx + int(s * 0.35), hcy - int(s * 0.15)), int(s * 0.5))
        tri = [(hcx - int(s * 0.8), hcy), (hcx + int(s * 0.8), hcy), (hcx, hcy + int(s * 0.9))]
        pygame.draw.polygon(hs, (*color, alpha), tri)
        surface.blit(hs, (cx - int(size * 1.5), cy - int(size * 1.5)))

    def _draw_exclamation(self, surface, cx, cy, size, color, alpha=255):
        """Draw a cute ! mark for wake-up pop."""
        es = pygame.Surface((int(size * 2), int(size * 4)), pygame.SRCALPHA)
        ecx, ecy = int(size), int(size * 2)
        # Bar
        bar_w = max(2, int(size * 0.5))
        bar_h = int(size * 2)
        pygame.draw.rect(es, (*color, alpha),
                         (ecx - bar_w // 2, ecy - bar_h, bar_w, bar_h),
                         border_radius=bar_w)
        # Dot
        pygame.draw.circle(es, (*color, alpha), (ecx, ecy + int(size * 0.5)), max(2, int(size * 0.35)))
        surface.blit(es, (cx - int(size), cy - int(size * 2)))

    # ─── Blink System ────────────────────────────────────────────────────

    def _update_blink(self, dt, state_name):
        """Advanced blink with closing/opening animation and random intervals."""
        # No blink during sleep or happy (those states override eyes)
        if state_name in ("SLEEPING", "HAPPY"):
            self._blink_stage = 0
            self._blink_progress = 0
            return

        self.blink_timer += dt

        if self._blink_stage == 0:  # Open — waiting for next blink
            if self.blink_timer >= self._next_blink:
                self._blink_stage = 1
                self._blink_progress = 0
                self.blink_timer = 0
                # Sometimes do a double-blink
                self._do_double = random.random() < 0.15
        elif self._blink_stage == 1:  # Closing
            self._blink_progress += dt * 12  # Fast close
            if self._blink_progress >= 1.0:
                self._blink_stage = 2
                self._blink_progress = 1.0
        elif self._blink_stage == 2:  # Closed — hold briefly
            self._blink_progress -= dt * 2  # Hold ~0.1s
            if self._blink_progress <= 0:
                self._blink_stage = 3
                self._blink_progress = 1.0
        elif self._blink_stage == 3:  # Opening
            self._blink_progress -= dt * 8  # Slightly slower open
            if self._blink_progress <= 0:
                self._blink_progress = 0
                if self._do_double:
                    self._do_double = False
                    self._blink_stage = 1  # Double blink
                else:
                    self._blink_stage = 0
                    # Randomize next blink interval
                    self._next_blink = random.uniform(2.5, 6.0)

    @property
    def _blink_amount(self) -> float:
        """0.0 = fully open, 1.0 = fully closed."""
        if self._blink_stage == 1:
            return self._blink_progress
        elif self._blink_stage == 2:
            return 1.0
        elif self._blink_stage == 3:
            return self._blink_progress
        return 0.0

    # ─── Wake Transition ─────────────────────────────────────────────────

    def _trigger_wake(self, cx, cy):
        """Spawn ! particle pop and start wake animation."""
        self.wake_transition = 1.0
        self._wake_particles = []
        # Burst of ! marks and stars
        for i in range(8):
            angle = random.uniform(0, math.pi * 2)
            speed = random.uniform(2, 5)
            self._wake_particles.append({
                'x': cx, 'y': cy - 60,
                'vx': math.cos(angle) * speed,
                'vy': math.sin(angle) * speed - 2,
                'life': 1.0,
                'type': random.choice(['!', 'star', 'star']),
                'size': random.uniform(5, 10),
                'color': random.choice([
                    self.config.neon_primary,
                    self.config.neon_warning,
                    (255, 255, 255),
                ]),
                'rot': random.uniform(0, 360),
            })

    def _update_wake(self, dt):
        if self.wake_transition > 0:
            self.wake_transition -= dt * 1.5
            if self.wake_transition < 0:
                self.wake_transition = 0

        new_wp = []
        for p in self._wake_particles:
            p['x'] += p['vx']
            p['y'] += p['vy']
            p['vy'] += 0.1  # Gravity
            p['life'] -= dt * 1.5
            p['rot'] += 180 * dt
            if p['life'] > 0:
                new_wp.append(p)
        self._wake_particles = new_wp

    def _draw_wake_particles(self, surface):
        for p in self._wake_particles:
            alpha = max(0, min(255, int(255 * p['life'])))
            size = max(1, int(p['size'] * p['life']))
            if p['type'] == '!':
                self._draw_exclamation(surface, int(p['x']), int(p['y']),
                                       size, p['color'], alpha)
            else:
                self._draw_star(surface, int(p['x']), int(p['y']),
                                size, p['color'], p['rot'])

    # ─── Floaties ────────────────────────────────────────────────────────

    def _update_floaties(self, cx, cy, state_name, t, dt):
        self.floaty_timer += dt
        spawn_rate = 0
        floaty_type = "star"
        color = self.config.neon_primary

        if state_name == "HAPPY":
            spawn_rate, floaty_type = 0.15, random.choice(["heart", "star", "star"])
            color = random.choice([(255, 150, 200), (255, 200, 100), (200, 150, 255)])
        elif state_name == "SPEAKING":
            spawn_rate, color = 0.4, self.config.neon_primary
        elif state_name == "IDLE":
            spawn_rate = 1.2
        elif state_name == "LISTENING":
            spawn_rate, floaty_type, color = 0.2, "note", self.config.neon_secondary
        elif state_name == "ALARM":
            spawn_rate, floaty_type = 0.1, random.choice(["star", "!"])
            color = random.choice([(255, 200, 50), (255, 150, 50), (255, 255, 200)])

        if self.floaty_timer > spawn_rate > 0:
            self.floaty_timer = 0
            self.floaties.append({
                'x': cx + random.uniform(-50, 50), 'y': cy - 30 + random.uniform(-20, 20),
                'vx': random.uniform(-0.5, 0.5), 'vy': random.uniform(-1.5, -0.5),
                'life': 1.0, 'type': floaty_type, 'size': random.uniform(3, 7),
                'color': color, 'rot': random.uniform(0, 360), 'rot_speed': random.uniform(-90, 90),
            })

        new = []
        for f in self.floaties:
            f['x'] += f['vx']; f['y'] += f['vy']; f['life'] -= dt * 0.6
            f['rot'] += f['rot_speed'] * dt; f['vy'] -= 0.01
            if f['life'] > 0:
                new.append(f)
        self.floaties = new[:40]

    def _draw_floaties(self, surface):
        for f in self.floaties:
            alpha = max(0, min(255, int(255 * f['life'])))
            size = max(1, int(f['size'] * f['life']))
            color = f['color'][:3]
            if f['type'] == 'heart':
                self._draw_heart(surface, int(f['x']), int(f['y']), size, color, alpha)
            elif f['type'] == 'star':
                self._draw_star(surface, int(f['x']), int(f['y']), size, color, f['rot'])
            elif f['type'] == '!':
                self._draw_exclamation(surface, int(f['x']), int(f['y']), size, color, alpha)
            elif f['type'] == 'note':
                ns = pygame.Surface((12, 12), pygame.SRCALPHA)
                pygame.draw.circle(ns, (*color, alpha), (4, 8), 3)
                pygame.draw.line(ns, (*color, alpha), (7, 8), (7, 1), 2)
                surface.blit(ns, (int(f['x']), int(f['y'])))

    # ─── Body ────────────────────────────────────────────────────────────

    def _draw_body(self, surface, cx, cy, t, state_name, breath):
        s = self.scale
        body_w, body_h = int(44 * s), int(32 * s)

        # Breathing scale on body
        breath_scale = 1.0 + breath * 0.02
        bw = int(body_w * breath_scale)
        bh = int(body_h * breath_scale)

        trim = self.config.neon_primary
        # Pulsing outline glow
        glow_alpha = int(180 + 75 * math.sin(t * 2.5))
        outline_color = (trim[0], trim[1], trim[2], glow_alpha)

        bs = pygame.Surface((bw + 8, bh + 8), pygame.SRCALPHA)
        # Glow outline (drawn bigger behind)
        glow_expand = int(2 + math.sin(t * 2.5) * 1.5)
        pygame.draw.ellipse(bs, (*trim, int(30 + 20 * math.sin(t * 2.5))),
                            (4 - glow_expand, 4 - glow_expand, bw + glow_expand * 2, bh + glow_expand * 2))
        # Solid body
        pygame.draw.ellipse(bs, (50, 45, 75), (4, 4, bw, bh))
        pygame.draw.ellipse(bs, trim, (4, 4, bw, bh), 2)

        # Bow
        bow_r = max(2, int(4 * s))
        bow_y = int(12 * s)
        pygame.draw.circle(bs, self.config.neon_secondary, (bw // 2 + 4, bow_y), bow_r)
        pygame.draw.circle(bs, (255, 200, 230), (bw // 2 + 4, bow_y), max(1, int(2 * s)))

        # Heart
        self._draw_heart(bs, bw // 2 + 4, bh // 2 + 4, int(4 * s), trim, 120)
        surface.blit(bs, (cx - bw // 2 - 4, cy))

        # Arms
        arm_w, arm_h = int(14 * s), int(22 * s)
        la, ra = 0, 0
        if state_name == "HAPPY": la, ra = math.sin(t * 8) * 20, -math.sin(t * 8 + 0.5) * 20
        elif state_name == "SPEAKING": la, ra = math.sin(t * 3) * 8, -math.sin(t * 3 + 1) * 8
        elif state_name == "LISTENING": la, ra = math.sin(t * 2) * 5 + 10, -math.sin(t * 2) * 5 - 10
        elif state_name == "ALARM": la, ra = math.sin(t * 10) * 25, -math.sin(t * 10 + 0.3) * 25
        elif state_name == "SLEEPING": la, ra = 5, -5  # Arms at rest

        for side, angle in [(-1, la), (1, ra)]:
            arm_s = pygame.Surface((arm_w + 4, arm_h + 4), pygame.SRCALPHA)
            pygame.draw.ellipse(arm_s, (60, 55, 85), (2, 2, arm_w, arm_h))
            pygame.draw.ellipse(arm_s, trim, (2, 2, arm_w, arm_h), 1)
            rotated = pygame.transform.rotate(arm_s, angle)
            surface.blit(rotated, (cx + side * (bw // 2 + 4) - rotated.get_width() // 2, cy + 4))

        # Legs
        leg_r = int(8 * s)
        leg_y = cy + bh - 4
        for side, phase in [(-1, 0), (1, 1)]:
            bounce = abs(math.sin(t * 8 + phase)) * 3 * s if state_name == "HAPPY" else 0
            if state_name == "ALARM":
                bounce = abs(math.sin(t * 10 + phase)) * 5 * s
            lx, ly = cx + side * int(10 * s), leg_y + int(bounce)
            pygame.draw.circle(surface, (40, 38, 60), (lx, ly), leg_r)
            pygame.draw.circle(surface, trim, (lx, ly), leg_r, 1)
            pygame.draw.circle(surface, (80, 75, 110), (lx - int(2 * s), ly - int(2 * s)), max(1, int(2 * s)))

    # ─── Cat Ears ────────────────────────────────────────────────────────

    def _draw_cat_ears(self, surface, head_cx, cy, head_radius, t, state_name):
        s = self.scale
        ear_size = int(22 * s)
        wiggle = 0
        if state_name == "LISTENING": wiggle = math.sin(t * 6) * 4
        elif state_name == "HAPPY": wiggle = math.sin(t * 4) * 3
        elif state_name == "IDLE": wiggle = math.sin(t * 1.5) * 1.5
        elif state_name == "ALARM": wiggle = math.sin(t * 8) * 5
        # Wake pop — ears perk up
        if self.wake_transition > 0:
            wiggle += self.wake_transition * 8

        for side in [-1, 1]:
            ear_x = head_cx + side * int(35 * s)
            ear_y = cy - head_radius + int(5 * s)
            outer = [(ear_x, ear_y + ear_size),
                     (ear_x + side * ear_size * 0.6, ear_y - ear_size + wiggle * side),
                     (ear_x + side * ear_size * 0.1, ear_y)]
            pygame.draw.polygon(surface, (40, 38, 60), outer)
            pygame.draw.polygon(surface, self.config.neon_secondary, outer, 2)
            iscale = 0.55
            inner = [(ear_x + 2 * side, ear_y + ear_size - 5),
                     (ear_x + side * ear_size * 0.6 * iscale + 2 * side,
                      ear_y - ear_size * iscale + wiggle * side + 5),
                     (ear_x + side * ear_size * 0.1 * iscale + 2 * side, ear_y + 5)]
            pygame.draw.polygon(surface, (180, 100, 140, 120), inner)

    # ─── Head ────────────────────────────────────────────────────────────

    def _draw_head(self, surface, cx, cy, t, state_name, state_timer, breath):
        s = self.scale
        head_radius = int(62 * s)

        # Breathing affects head slightly
        breath_offset = breath * 1.5

        tilt = 0
        if state_name == "THINKING": tilt = math.sin(t * 1.5) * 5
        elif state_name == "CONFUSED": tilt = math.sin(t * 3) * 7
        elif state_name == "SLEEPING": tilt = 10 + math.sin(t * 0.5) * 2  # Gentle sway
        elif state_name == "HAPPY": tilt = math.sin(t * 4) * 2
        elif state_name == "ALARM": tilt = math.sin(t * 8) * 4
        head_cx = cx + int(tilt)

        # ── Glow (pulsing "alive" aura) ──────────────────────────────────
        glow_c = self.config.neon_primary
        if state_name == "HAPPY": glow_c = (255, 200, 100)
        elif state_name == "SLEEPING": glow_c = (100, 80, 200)
        elif state_name == "LISTENING": glow_c = self.config.neon_secondary
        elif state_name == "ALARM": glow_c = (255, 200, 50)

        # Pulsing glow intensity
        glow_base = 15
        glow_pulse = glow_base + int(8 * math.sin(t * 2.0))
        gs = pygame.Surface((head_radius * 3, head_radius * 3), pygame.SRCALPHA)
        pygame.draw.circle(gs, (*glow_c, glow_pulse),
                           (head_radius * 3 // 2, head_radius * 3 // 2), head_radius + 15)
        surface.blit(gs, (head_cx - head_radius * 3 // 2, cy - head_radius * 3 // 2))

        # ── Head shape ───────────────────────────────────────────────────
        head_w = head_radius * 2 + 4
        head_h = int(head_radius * 1.9)
        head_rect = (head_cx - head_radius - 2, int(cy - head_h // 2 + breath_offset),
                     head_w, head_h)
        pygame.draw.ellipse(surface, (55, 50, 72), head_rect)

        # Pulsing outline
        outline_alpha = int(200 + 55 * math.sin(t * 2.5))
        outline_surf = pygame.Surface((head_w + 8, head_h + 8), pygame.SRCALPHA)
        pygame.draw.ellipse(outline_surf, (*self.config.neon_primary, outline_alpha),
                            (4, 4, head_w, head_h), 2)
        surface.blit(outline_surf, (head_cx - head_radius - 6,
                                     int(cy - head_h // 2 + breath_offset - 4)))

        # Cat ears
        self._draw_cat_ears(surface, head_cx, cy + int(breath_offset), head_radius, t, state_name)

        # Hair
        hair_c = (35, 32, 55)
        for i in range(5):
            bx = head_cx - int(30 * s) + i * int(15 * s)
            pygame.draw.circle(surface, hair_c,
                               (bx, int(cy - head_h // 2 + 5 * s + breath_offset)),
                               int((18 + math.sin(i * 1.3) * 5) * s))
        for side in [-1, 1]:
            bang_x = head_cx + side * (head_radius - int(5 * s))
            for j in range(3):
                pygame.draw.circle(surface, hair_c,
                                   (bang_x, int(cy - 20 * s + j * 12 * s + breath_offset)),
                                   int((12 - j * 2) * s))
        # Hair shine
        shine_w, shine_h = int(30 * s), int(8 * s)
        pygame.draw.arc(surface, (100, 90, 140),
                        (head_cx - shine_w // 2,
                         int(cy - head_h // 2 + 8 * s + breath_offset),
                         shine_w, shine_h),
                        0, math.pi, 2)

        # ── Eyes ─────────────────────────────────────────────────────────
        eye_y = int(cy - 2 + breath_offset)
        lex, rex = head_cx - int(24 * s), head_cx + int(24 * s)
        er = int(16 * s)

        blink = self._blink_amount

        if state_name == "SLEEPING":
            # Kawaii closed eyes (^ ^) with gentle breathing movement
            for ex in [lex, rex]:
                pygame.draw.arc(surface, self.config.neon_primary,
                                (ex - int(12 * s), eye_y - int(8 * s), int(24 * s), int(16 * s)),
                                math.pi * 0.15, math.pi * 0.85, max(2, int(3 * s)))
            # Zzz
            font = pygame.font.SysFont("monospace", int(18 * s), bold=True)
            zoff = math.sin(t * 2) * 5 * s
            for i, ch in enumerate("Zzz"):
                alpha = int(200 - i * 40)
                z_s = font.render(ch, True, (*self.config.neon_accent, ))
                surface.blit(z_s, (head_cx + int(45 * s) + i * int(14 * s),
                                   eye_y - int(45 * s) - i * int(16 * s) + zoff))

        elif state_name == "HAPPY":
            # Happy closed eyes (n_n)
            for ex in [lex, rex]:
                pygame.draw.arc(surface, self.config.neon_primary,
                                (ex - int(12 * s), eye_y - int(6 * s), int(24 * s), int(16 * s)),
                                math.pi * 1.15, math.pi * 1.85, max(2, int(3 * s)))
                ss = (5 + math.sin(t * 6) * 2) * s
                self._draw_star(surface, ex + int(10 * s), eye_y - int(14 * s), ss, (255, 230, 150), t * 90)
                self._draw_star(surface, ex - int(8 * s), eye_y - int(12 * s), ss * 0.6, (255, 200, 255), -t * 120)

        elif blink > 0.7:
            # Nearly closed — horizontal line
            for ex in [lex, rex]:
                squeeze = int(er * 2.3 * (1 - blink))
                if squeeze < 3:
                    pygame.draw.line(surface, self.config.neon_primary,
                                     (ex - er, eye_y), (ex + er, eye_y), 2)
                else:
                    erect = (ex - er, eye_y - squeeze // 2, er * 2, max(3, squeeze))
                    pygame.draw.ellipse(surface, (235, 235, 245), erect)
                    pygame.draw.ellipse(surface, (30, 28, 45), erect, 2)

        else:
            # Full open eyes (with partial blink squish)
            squish = 1.0 - blink * 0.6  # Blink squishes the eye height
            for ex in [lex, rex]:
                ew = er * 2
                eh = int(er * 2.3 * squish)
                erect = (ex - er, eye_y - eh // 2, ew, eh)
                pygame.draw.ellipse(surface, (235, 235, 245), erect)

                iris_c = self.config.neon_primary
                if state_name == "CONFUSED": iris_c = self.config.neon_secondary
                elif state_name == "THINKING": iris_c = self.config.neon_accent
                elif state_name == "LISTENING": iris_c = (150, 200, 255)
                elif state_name == "ALARM": iris_c = (255, 200, 50)

                pox, poy = 0, 0
                if state_name == "THINKING":
                    pox, poy = int(math.sin(t * 2) * 4 * s), int(math.cos(t * 2) * 3 * s) - int(2 * s)

                icx, icy = ex + pox, eye_y + poy
                ir = er - max(1, int(2 * s))

                # Wake transition — eyes go wide
                if self.wake_transition > 0:
                    ir = int(ir * (1 + self.wake_transition * 0.3))

                pygame.draw.circle(surface, iris_c, (icx, icy), ir)
                pygame.draw.circle(surface, tuple(max(0, c - 40) for c in iris_c), (icx, icy), ir, max(2, int(3 * s)))
                pygame.draw.circle(surface, (8, 8, 18), (icx, icy), ir - max(2, int(5 * s)))

                # Star highlight
                self._draw_star(surface, icx - int(4 * s), icy - int(5 * s), 5 * s, (255, 255, 255), t * 30)
                pygame.draw.circle(surface, (255, 255, 255), (icx + int(4 * s), icy + int(3 * s)), max(1, int(3 * s)))
                pygame.draw.circle(surface, (200, 220, 255), (icx - int(2 * s), icy + int(5 * s)), max(1, int(s)))
                pygame.draw.ellipse(surface, (30, 28, 45), erect, 2)

            # Confused spirals
            if state_name == "CONFUSED":
                for ex in [lex, rex]:
                    for a in range(0, 720, 30):
                        rad = math.radians(a + t * 200)
                        r = ((8 + math.sin(t * 3) * 2) * (a / 720)) * s
                        pygame.draw.circle(surface, self.config.neon_secondary,
                                           (int(ex + math.cos(rad) * r), int(eye_y + math.sin(rad) * r)),
                                           max(1, int(s)))

        # ── Mouth ────────────────────────────────────────────────────────
        my = int(cy + 22 * s + breath_offset)

        if state_name == "HAPPY":
            w = int(20 * s)
            pts = [(head_cx - w, my), (head_cx - w // 3, my + int(8 * s)), (head_cx, my + int(2 * s)),
                   (head_cx + w // 3, my + int(8 * s)), (head_cx + w, my)]
            pygame.draw.lines(surface, self.config.neon_secondary, False, pts, 2)
            pygame.draw.line(surface, (220, 220, 235),
                             (head_cx + int(8 * s), my),
                             (head_cx + int(6 * s), my + int(5 * s)), 2)
        elif state_name == "SPEAKING":
            mo = abs(math.sin(t * 8)) * 10 * s
            mw, mh = int(16 * s), max(int(4 * s), int(mo + 4 * s))
            pygame.draw.ellipse(surface, (30, 15, 40), (head_cx - mw // 2, my - 2, mw, mh))
            if mh > int(8 * s):
                tw, th = int(8 * s), int(5 * s)
                pygame.draw.ellipse(surface, (200, 100, 120),
                                    (head_cx - tw // 2, my + mh - th - int(3 * s), tw, th))
            pygame.draw.ellipse(surface, self.config.neon_primary, (head_cx - mw // 2, my - 2, mw, mh), 2)
        elif state_name == "CONFUSED":
            pts = [(head_cx - int(14 * s) + int(i * 2 * s),
                    my + math.sin(t * 4 + i * 0.7) * 4 * s) for i in range(16)]
            if len(pts) > 1: pygame.draw.lines(surface, self.config.neon_secondary, False, pts, 2)
        elif state_name == "THINKING":
            r = int(6 * s)
            pygame.draw.circle(surface, (30, 15, 40), (head_cx + int(3 * s), my + int(3 * s)), r)
            pygame.draw.circle(surface, self.config.neon_accent, (head_cx + int(3 * s), my + int(3 * s)), r, 2)
        elif state_name == "SLEEPING":
            pygame.draw.arc(surface, self.config.neon_primary,
                            (head_cx - int(10 * s), my - 2, int(20 * s), int((10 + breath * 2) * s)),
                            math.pi * 1.1, math.pi * 1.9, 2)
            dy = my + int(6 * s) + abs(math.sin(t * 2)) * 4 * s
            pygame.draw.circle(surface, (150, 180, 220), (head_cx + int(8 * s), int(dy)), int(2 * s))
        elif state_name == "LISTENING":
            ow, oh = int(10 * s), int(8 * s)
            pygame.draw.ellipse(surface, (30, 15, 40), (head_cx - ow // 2, my, ow, oh))
            pygame.draw.ellipse(surface, self.config.neon_primary, (head_cx - ow // 2, my, ow, oh), 1)
        elif state_name == "ALARM":
            mo = abs(math.sin(t * 10)) * 12 * s
            mw, mh = int(20 * s), max(int(6 * s), int(mo + 6 * s))
            pygame.draw.ellipse(surface, (30, 15, 40), (head_cx - mw // 2, my - 2, mw, mh))
            pygame.draw.ellipse(surface, self.config.neon_warning, (head_cx - mw // 2, my - 2, mw, mh), 2)
        else:
            # Cat mouth :3
            cw = int(8 * s)
            pygame.draw.arc(surface, self.config.neon_primary,
                            (head_cx - cw - int(4 * s), my - int(3 * s), cw * 2, int(10 * s)),
                            math.pi * 1.1, math.pi * 1.9, 2)
            pygame.draw.arc(surface, self.config.neon_primary,
                            (head_cx - cw + int(4 * s), my - int(3 * s), cw * 2, int(10 * s)),
                            math.pi * 1.1, math.pi * 1.9, 2)

        # ── Blush ────────────────────────────────────────────────────────
        ba = 35
        pulse = 0
        if state_name == "HAPPY": ba, pulse = 70, math.sin(t * 4) * 10
        elif state_name == "SPEAKING": ba, pulse = 50, math.sin(t * 3) * 5
        elif state_name == "LISTENING": ba = 45
        elif state_name == "ALARM": ba, pulse = 60, math.sin(t * 6) * 8

        bw, bh = int((28 + pulse) * s), int((16 + pulse * 0.5) * s)
        blush = pygame.Surface((bw + 2, bh + 2), pygame.SRCALPHA)
        pygame.draw.ellipse(blush, (255, 120, 150, ba), (1, 1, bw, bh))

        for ex in [lex, rex]:
            bx, by = ex - bw // 2 - int(4 * s), eye_y + int(16 * s)
            surface.blit(blush, (bx, by))
            if ba > 40:
                for i in range(3):
                    lx = bx + int(6 * s) + i * int(6 * s)
                    pygame.draw.line(surface, (255, 150, 170),
                                     (lx, by + int(3 * s)),
                                     (lx + int(4 * s), by + int(9 * s)), max(1, int(s)))

        # ── Antenna ──────────────────────────────────────────────────────
        ant_tip_y = cy - head_radius * 0.9 - 30 * s + math.sin(t * 3) * 6 * s + breath_offset
        ant_tip_x = head_cx + int(8 * s)
        pygame.draw.line(surface, (80, 75, 110),
                         (int(head_cx - 2 * s), int(cy - head_radius * 0.9 + breath_offset)),
                         (int(ant_tip_x), int(ant_tip_y)), max(2, int(2 * s)))

        orb_c = self.config.neon_primary
        if state_name == "HAPPY": orb_c = (255, 220, 100)
        elif state_name == "LISTENING": orb_c = self.config.neon_secondary
        elif state_name == "ALARM": orb_c = (255, 200, 50)

        orb_size = (6 + math.sin(t * 5) * 2) * s
        self._draw_star(surface, int(ant_tip_x), int(ant_tip_y), orb_size, orb_c, t * 60)
        ga = int(30 + 20 * math.sin(t * 4))
        gr = int(12 * s)
        gsurf = pygame.Surface((gr * 2 + 6, gr * 2 + 6), pygame.SRCALPHA)
        pygame.draw.circle(gsurf, (*orb_c, ga), (gr + 3, gr + 3), gr)
        surface.blit(gsurf, (int(ant_tip_x) - gr - 3, int(ant_tip_y) - gr - 3))

    # ─── Main Draw ───────────────────────────────────────────────────────

    def draw(self, surface, cx, cy, state, state_timer, t):
        state_name = state.name
        dt = 1 / 30

        # Detect state transition for wake-up
        if self._prev_state == "SLEEPING" and state_name != "SLEEPING":
            self._trigger_wake(cx, cy)
        self._prev_state = state_name

        # Update systems
        self._update_blink(dt, state_name)
        self._update_wake(dt)

        # ── Breathing ────────────────────────────────────────────────────
        # Continuous sine wave — amplitude varies by state
        if state_name == "SLEEPING":
            # Deep slow breaths
            breath = math.sin(t * 1.2) * 1.0
        elif state_name == "IDLE":
            # Gentle subtle breathing
            breath = math.sin(t * 1.8) * 0.5
        elif state_name == "SPEAKING":
            breath = math.sin(t * 3.5) * 0.3
        elif state_name == "ALARM":
            # Rapid breathing
            breath = math.sin(t * 5) * 0.6
        else:
            breath = math.sin(t * 2.0) * 0.3

        # ── Bob + scale ──────────────────────────────────────────────────
        bob = 0
        if state_name == "IDLE":
            bob = math.sin(t * self.config.chibi_bob_speed) * self.config.chibi_bob_amount
        elif state_name == "HAPPY":
            bob = abs(math.sin(t * 6)) * 12
        elif state_name == "ALARM":
            bob = abs(math.sin(t * 10)) * 15
        elif state_name == "THINKING":
            bob = math.sin(t * 1.5) * 4
        elif state_name == "SLEEPING":
            # Slow breathing bob — synced with breath
            bob = breath * 5
        elif state_name == "SPEAKING":
            bob = math.sin(t * 3) * 3
        elif state_name == "LISTENING":
            bob = math.sin(t * 2.5) * 4

        # Wake pop — extra upward bounce
        if self.wake_transition > 0:
            bob -= self.wake_transition * 15

        dcy = cy + int(bob)
        self._update_floaties(cx, dcy, state_name, t, dt)

        # ── Shadow (reacts to height) ────────────────────────────────────
        sw = 90 + int(abs(bob) * 1.5)
        sa = max(15, 35 - abs(int(bob)))
        ss = pygame.Surface((sw, 18), pygame.SRCALPHA)
        pygame.draw.ellipse(ss, (0, 0, 0, sa), (0, 0, sw, 18))
        surface.blit(ss, (cx - sw // 2, cy + int(80 * self.scale)))

        # ── Draw character ───────────────────────────────────────────────
        self._draw_body(surface, cx, dcy, t, state_name, breath)
        self._draw_head(surface, cx, dcy - int(50 * self.scale), t, state_name, state_timer, breath)
        self._draw_floaties(surface)
        self._draw_wake_particles(surface)

        # ── State-specific overlays ──────────────────────────────────────
        if state_name == "THINKING":
            head_y = dcy - int(50 * self.scale)
            for i in range(3):
                da = abs(math.sin(t * 3 + i * 1.2))
                ds = int(4 + da * 5)
                self._draw_star(surface, cx + int(55 * self.scale) + i * int(18 * self.scale),
                                head_y - int(35 * self.scale) - i * int(14 * self.scale),
                                ds, (int(self.config.neon_accent[0] * da),
                                     int(self.config.neon_accent[1] * da),
                                     int(self.config.neon_accent[2] * da)), t * 120 + i * 40)

        if state_name == "LISTENING":
            for i in range(3):
                rp = (t * 1.5 + i * 0.4) % 1.0
                rr = int((75 + rp * 50) * self.scale)
                ra = int(70 * (1 - rp))
                rs = pygame.Surface((rr * 2 + 4, rr * 2 + 4), pygame.SRCALPHA)
                pygame.draw.circle(rs, (*self.config.neon_secondary, ra), (rr + 2, rr + 2), rr, width=2)
                surface.blit(rs, (cx - rr - 2, dcy - int(30 * self.scale) - rr - 2))
