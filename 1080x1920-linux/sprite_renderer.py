"""
Chibi Renderer v4 — MAXIMUM KAWAII EDITION
Upgrades from v3: bigger head ratio, cat tail, toe beans, whiskers, tiny fang,
hair clip, heart pupils (happy), fluffier ears, warmer body tones, more sparkles.
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

        # Tail physics
        self._tail_angle = 0.0
        self._tail_vel = 0.0

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

    def _draw_paw(self, surface, cx, cy, size, color, alpha=200):
        """Draw a tiny paw pad (toe beans!)."""
        ps = pygame.Surface((int(size * 3), int(size * 3)), pygame.SRCALPHA)
        pcx, pcy = int(size * 1.5), int(size * 1.5)
        s = size
        # Main pad
        pygame.draw.ellipse(ps, (*color, alpha),
                            (pcx - int(s * 0.5), pcy - int(s * 0.2), int(s), int(s * 0.7)))
        # Toe beans (3 little circles above the main pad)
        bean_r = max(1, int(s * 0.22))
        for i, offset in enumerate([-0.35, 0, 0.35]):
            bx = pcx + int(offset * s)
            by = pcy - int(s * 0.45)
            pygame.draw.circle(ps, (*color, alpha), (bx, by), bean_r)
        surface.blit(ps, (cx - int(size * 1.5), cy - int(size * 1.5)))

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
        # Burst of ! marks and stars and hearts
        for i in range(10):
            angle = random.uniform(0, math.pi * 2)
            speed = random.uniform(2, 5)
            self._wake_particles.append({
                'x': cx, 'y': cy - 60,
                'vx': math.cos(angle) * speed,
                'vy': math.sin(angle) * speed - 2,
                'life': 1.0,
                'type': random.choice(['!', 'star', 'star', 'heart']),
                'size': random.uniform(5, 10),
                'color': random.choice([
                    self.config.neon_primary,
                    self.config.neon_warning,
                    (255, 200, 230),
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
            elif p['type'] == 'heart':
                self._draw_heart(surface, int(p['x']), int(p['y']),
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
            spawn_rate, floaty_type = 0.12, random.choice(["heart", "heart", "star"])
            color = random.choice([(255, 150, 200), (255, 200, 100), (200, 150, 255), (255, 180, 220)])
        elif state_name == "SPEAKING":
            spawn_rate, color = 0.35, self.config.neon_primary
            floaty_type = random.choice(["star", "note"])
        elif state_name == "IDLE":
            spawn_rate = 0.9
            floaty_type = random.choice(["star", "heart", "star", "star"])
            color = random.choice([self.config.neon_primary, (255, 180, 220), (200, 200, 255)])
        elif state_name == "LISTENING":
            spawn_rate, floaty_type, color = 0.18, "note", self.config.neon_secondary
        elif state_name == "ALARM":
            spawn_rate, floaty_type = 0.1, random.choice(["star", "!"])
            color = random.choice([(255, 200, 50), (255, 150, 50), (255, 255, 200)])

        if self.floaty_timer > spawn_rate > 0:
            self.floaty_timer = 0
            self.floaties.append({
                'x': cx + random.uniform(-60, 60), 'y': cy - 30 + random.uniform(-20, 20),
                'vx': random.uniform(-0.5, 0.5), 'vy': random.uniform(-1.5, -0.5),
                'life': 1.0, 'type': floaty_type, 'size': random.uniform(3, 8),
                'color': color, 'rot': random.uniform(0, 360), 'rot_speed': random.uniform(-90, 90),
            })

        new = []
        for f in self.floaties:
            f['x'] += f['vx']; f['y'] += f['vy']; f['life'] -= dt * 0.5
            f['rot'] += f['rot_speed'] * dt; f['vy'] -= 0.01
            if f['life'] > 0:
                new.append(f)
        self.floaties = new[:50]

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

    # ─── Cat Tail ─────────────────────────────────────────────────────────

    def _update_tail(self, dt, state_name, t):
        """Springy tail physics — sways gently, reacts to state."""
        target = math.sin(t * 1.5) * 15  # gentle idle sway
        if state_name == "HAPPY":
            target = math.sin(t * 5) * 35
        elif state_name == "LISTENING":
            target = math.sin(t * 3) * 20
        elif state_name == "SLEEPING":
            target = math.sin(t * 0.6) * 8
        elif state_name == "ALARM":
            target = math.sin(t * 8) * 40
        elif state_name == "SPEAKING":
            target = math.sin(t * 2.5) * 18
        elif state_name == "THINKING":
            target = math.sin(t * 1.0) * 10 + 5

        # Spring physics
        spring = 6.0
        damping = 3.5
        self._tail_vel += (target - self._tail_angle) * spring * dt
        self._tail_vel *= max(0, 1.0 - damping * dt)
        self._tail_angle += self._tail_vel * dt

    def _draw_tail(self, surface, cx, cy, body_w, body_h, t, state_name):
        """Draw a curvy cat tail from the back of the body."""
        s = self.scale
        tail_base_x = cx + int(body_w * 0.45)
        tail_base_y = cy + int(body_h * 0.3)

        angle = self._tail_angle
        segments = 8
        seg_len = int(8 * s)
        prev_x, prev_y = tail_base_x, tail_base_y
        cur_angle = math.radians(-60 + angle * 0.3)

        # Tail color — warm purple-pink
        tail_c = (70, 60, 95)
        trim = self.config.neon_secondary

        points = [(prev_x, prev_y)]
        for i in range(segments):
            # Each segment curves more
            curve = math.radians(angle * (0.3 + i * 0.12))
            cur_angle += curve * 0.15
            nx = prev_x + int(math.cos(cur_angle) * seg_len)
            ny = prev_y + int(math.sin(cur_angle) * seg_len)
            points.append((nx, ny))
            prev_x, prev_y = nx, ny

        # Draw thick tail
        if len(points) >= 2:
            for i in range(len(points) - 1):
                thickness = max(2, int((segments - i) * s * 0.8))
                pygame.draw.line(surface, tail_c, points[i], points[i + 1], thickness)
            # Outline
            for i in range(len(points) - 1):
                thickness = max(1, int((segments - i) * s * 0.8) + 2)
                pygame.draw.line(surface, (*trim, 60), points[i], points[i + 1], 1)

        # Tail tip — fluffy ball
        tip_x, tip_y = points[-1]
        tip_r = max(3, int(4 * s))
        pygame.draw.circle(surface, tail_c, (tip_x, tip_y), tip_r)
        pygame.draw.circle(surface, trim, (tip_x, tip_y), tip_r, 1)
        # Tiny highlight on tip
        pygame.draw.circle(surface, (120, 100, 150), (tip_x - 1, tip_y - 1), max(1, int(2 * s)))

    # ─── Body ────────────────────────────────────────────────────────────

    def _draw_body(self, surface, cx, cy, t, state_name, breath):
        s = self.scale
        # Slightly smaller body for bigger head-to-body ratio
        body_w, body_h = int(40 * s), int(28 * s)

        # Breathing scale on body
        breath_scale = 1.0 + breath * 0.025
        bw = int(body_w * breath_scale)
        bh = int(body_h * breath_scale)

        # Warmer body color
        body_color = (65, 55, 85)
        trim = self.config.neon_primary

        # Pulsing outline glow
        glow_alpha = int(180 + 75 * math.sin(t * 2.5))

        bs = pygame.Surface((bw + 12, bh + 12), pygame.SRCALPHA)
        # Glow outline (drawn bigger behind)
        glow_expand = int(3 + math.sin(t * 2.5) * 2)
        pygame.draw.ellipse(bs, (*trim, int(25 + 20 * math.sin(t * 2.5))),
                            (6 - glow_expand, 6 - glow_expand, bw + glow_expand * 2, bh + glow_expand * 2))
        # Solid body
        pygame.draw.ellipse(bs, body_color, (6, 6, bw, bh))
        pygame.draw.ellipse(bs, trim, (6, 6, bw, bh), 2)

        # Bow — bigger and cuter with ribbon tails
        bow_cx = bw // 2 + 6
        bow_y = int(10 * s)
        bow_r = max(3, int(5 * s))
        # Left ribbon loop
        pygame.draw.ellipse(bs, self.config.neon_secondary,
                            (bow_cx - int(8 * s), bow_y - int(4 * s), int(8 * s), int(8 * s)))
        # Right ribbon loop
        pygame.draw.ellipse(bs, self.config.neon_secondary,
                            (bow_cx, bow_y - int(4 * s), int(8 * s), int(8 * s)))
        # Center knot
        pygame.draw.circle(bs, (255, 200, 230), (bow_cx, bow_y), max(2, int(3 * s)))
        # Ribbon tails
        for side in [-1, 1]:
            tail_x = bow_cx + side * int(4 * s)
            tail_pts = [
                (tail_x, bow_y + int(2 * s)),
                (tail_x + side * int(3 * s), bow_y + int(8 * s)),
                (tail_x + side * int(1 * s), bow_y + int(10 * s)),
            ]
            pygame.draw.lines(bs, self.config.neon_secondary, False, tail_pts, max(1, int(2 * s)))

        # Heart on body
        self._draw_heart(bs, bw // 2 + 6, bh // 2 + 6, int(4 * s), (255, 180, 220), 100)
        surface.blit(bs, (cx - bw // 2 - 6, cy))

        # Tail (behind body)
        self._draw_tail(surface, cx, cy, bw, bh, t, state_name)

        # Arms — rounder, with tiny paw pads at the tips
        arm_w, arm_h = int(12 * s), int(20 * s)
        la, ra = 0, 0
        if state_name == "HAPPY": la, ra = math.sin(t * 8) * 22, -math.sin(t * 8 + 0.5) * 22
        elif state_name == "SPEAKING": la, ra = math.sin(t * 3) * 8, -math.sin(t * 3 + 1) * 8
        elif state_name == "LISTENING": la, ra = math.sin(t * 2) * 5 + 12, -math.sin(t * 2) * 5 - 12
        elif state_name == "ALARM": la, ra = math.sin(t * 10) * 25, -math.sin(t * 10 + 0.3) * 25
        elif state_name == "SLEEPING": la, ra = 5, -5

        for side, angle in [(-1, la), (1, ra)]:
            arm_s = pygame.Surface((arm_w + 8, arm_h + 8), pygame.SRCALPHA)
            pygame.draw.ellipse(arm_s, body_color, (4, 4, arm_w, arm_h))
            pygame.draw.ellipse(arm_s, trim, (4, 4, arm_w, arm_h), 1)
            # Paw pad at tip
            paw_cx = arm_w // 2 + 4
            paw_cy = arm_h + 2
            self._draw_paw(arm_s, paw_cx, paw_cy, int(3 * s), (200, 140, 170))
            rotated = pygame.transform.rotate(arm_s, angle)
            surface.blit(rotated, (cx + side * (bw // 2 + 2) - rotated.get_width() // 2, cy + 2))

        # Legs — with toe beans!
        leg_r = int(9 * s)
        leg_y = cy + bh - 2
        for side, phase in [(-1, 0), (1, 1)]:
            bounce = abs(math.sin(t * 8 + phase)) * 4 * s if state_name == "HAPPY" else 0
            if state_name == "ALARM":
                bounce = abs(math.sin(t * 10 + phase)) * 5 * s
            lx, ly = cx + side * int(10 * s), leg_y + int(bounce)
            # Foot
            pygame.draw.circle(surface, body_color, (lx, ly), leg_r)
            pygame.draw.circle(surface, trim, (lx, ly), leg_r, 1)
            # Shoe shine
            pygame.draw.circle(surface, (95, 80, 120), (lx - int(2 * s), ly - int(2 * s)), max(1, int(2 * s)))
            # Toe beans on bottom of feet
            bean_color = (200, 140, 170)
            bean_r = max(1, int(2 * s))
            # Main pad
            pygame.draw.ellipse(surface, bean_color,
                                (lx - int(3 * s), ly + int(1 * s), int(6 * s), int(4 * s)))
            # Three tiny toe beans
            for bi in range(-1, 2):
                bx = lx + bi * int(2.5 * s)
                by = ly - int(1 * s)
                pygame.draw.circle(surface, bean_color, (bx, by), max(1, int(1.2 * s)))

    # ─── Cat Ears ────────────────────────────────────────────────────────

    def _draw_cat_ears(self, surface, head_cx, cy, head_radius, t, state_name):
        s = self.scale
        ear_size = int(25 * s)  # Bigger ears!
        wiggle = 0
        if state_name == "LISTENING": wiggle = math.sin(t * 6) * 5
        elif state_name == "HAPPY": wiggle = math.sin(t * 4) * 4
        elif state_name == "IDLE": wiggle = math.sin(t * 1.5) * 2
        elif state_name == "ALARM": wiggle = math.sin(t * 8) * 6
        # Wake pop — ears perk up
        if self.wake_transition > 0:
            wiggle += self.wake_transition * 10

        for side in [-1, 1]:
            ear_x = head_cx + side * int(38 * s)
            ear_y = cy - head_radius + int(3 * s)
            outer = [(ear_x, ear_y + ear_size),
                     (ear_x + side * ear_size * 0.65, ear_y - ear_size + wiggle * side),
                     (ear_x + side * ear_size * 0.1, ear_y)]
            pygame.draw.polygon(surface, (55, 48, 75), outer)
            pygame.draw.polygon(surface, self.config.neon_secondary, outer, 2)
            # Inner ear — pinker, bigger
            iscale = 0.6
            inner = [(ear_x + 2 * side, ear_y + ear_size - 4),
                     (ear_x + side * ear_size * 0.65 * iscale + 2 * side,
                      ear_y - ear_size * iscale + wiggle * side + 4),
                     (ear_x + side * ear_size * 0.1 * iscale + 2 * side, ear_y + 4)]
            pygame.draw.polygon(surface, (200, 120, 160, 140), inner)

            # Ear tuft — fluffy fur detail at base
            tuft_x = ear_x + side * int(2 * s)
            tuft_y = ear_y + ear_size - int(3 * s)
            for ti in range(3):
                tx = tuft_x + side * ti * int(3 * s)
                ty = tuft_y - ti * int(2 * s)
                tr = max(2, int((4 - ti) * s))
                pygame.draw.circle(surface, (55, 48, 75), (tx, ty), tr)

    # ─── Head ────────────────────────────────────────────────────────────

    def _draw_head(self, surface, cx, cy, t, state_name, state_timer, breath):
        s = self.scale
        head_radius = int(68 * s)  # Bigger head for cuter proportions!

        # Breathing affects head slightly
        breath_offset = breath * 1.5

        tilt = 0
        if state_name == "THINKING": tilt = math.sin(t * 1.5) * 5
        elif state_name == "CONFUSED": tilt = math.sin(t * 3) * 7
        elif state_name == "SLEEPING": tilt = 10 + math.sin(t * 0.5) * 2
        elif state_name == "HAPPY": tilt = math.sin(t * 4) * 3
        elif state_name == "ALARM": tilt = math.sin(t * 8) * 4
        head_cx = cx + int(tilt)

        # ── Glow (pulsing "alive" aura) ──────────────────────────────────
        glow_c = self.config.neon_primary
        if state_name == "HAPPY": glow_c = (255, 200, 100)
        elif state_name == "SLEEPING": glow_c = (100, 80, 200)
        elif state_name == "LISTENING": glow_c = self.config.neon_secondary
        elif state_name == "ALARM": glow_c = (255, 200, 50)

        # Pulsing glow intensity
        glow_base = 18
        glow_pulse = glow_base + int(10 * math.sin(t * 2.0))
        gs = pygame.Surface((head_radius * 3, head_radius * 3), pygame.SRCALPHA)
        pygame.draw.circle(gs, (*glow_c, glow_pulse),
                           (head_radius * 3 // 2, head_radius * 3 // 2), head_radius + 18)
        surface.blit(gs, (head_cx - head_radius * 3 // 2, cy - head_radius * 3 // 2))

        # ── Head shape — rounder ─────────────────────────────────────────
        head_w = head_radius * 2 + 4
        head_h = int(head_radius * 1.95)  # Rounder
        head_rect = (head_cx - head_radius - 2, int(cy - head_h // 2 + breath_offset),
                     head_w, head_h)
        pygame.draw.ellipse(surface, (65, 58, 82), head_rect)

        # Pulsing outline
        outline_alpha = int(200 + 55 * math.sin(t * 2.5))
        outline_surf = pygame.Surface((head_w + 8, head_h + 8), pygame.SRCALPHA)
        pygame.draw.ellipse(outline_surf, (*self.config.neon_primary, outline_alpha),
                            (4, 4, head_w, head_h), 2)
        surface.blit(outline_surf, (head_cx - head_radius - 6,
                                     int(cy - head_h // 2 + breath_offset - 4)))

        # Cat ears
        self._draw_cat_ears(surface, head_cx, cy + int(breath_offset), head_radius, t, state_name)

        # Hair — more volume
        hair_c = (40, 35, 60)
        for i in range(6):
            bx = head_cx - int(35 * s) + i * int(14 * s)
            pygame.draw.circle(surface, hair_c,
                               (bx, int(cy - head_h // 2 + 4 * s + breath_offset)),
                               int((20 + math.sin(i * 1.3) * 5) * s))
        for side in [-1, 1]:
            bang_x = head_cx + side * (head_radius - int(3 * s))
            for j in range(4):
                pygame.draw.circle(surface, hair_c,
                                   (bang_x, int(cy - 22 * s + j * 11 * s + breath_offset)),
                                   int((14 - j * 2) * s))

        # Hair shine — double arc for extra sparkle
        shine_w, shine_h = int(35 * s), int(10 * s)
        pygame.draw.arc(surface, (120, 105, 160),
                        (head_cx - shine_w // 2,
                         int(cy - head_h // 2 + 6 * s + breath_offset),
                         shine_w, shine_h),
                        0, math.pi, 2)
        pygame.draw.arc(surface, (100, 85, 140),
                        (head_cx - shine_w // 2 + int(5 * s),
                         int(cy - head_h // 2 + 10 * s + breath_offset),
                         int(20 * s), int(6 * s)),
                        0, math.pi, 1)

        # Hair clip — little star accessory!
        clip_x = head_cx - int(40 * s)
        clip_y = int(cy - head_h // 2 + 18 * s + breath_offset)
        clip_size = (4 + math.sin(t * 3) * 1) * s
        self._draw_star(surface, clip_x, clip_y, clip_size, (255, 230, 100), t * 45)
        # Glow around clip
        clip_gs = pygame.Surface((int(clip_size * 4), int(clip_size * 4)), pygame.SRCALPHA)
        pygame.draw.circle(clip_gs, (255, 230, 100, 30),
                           (int(clip_size * 2), int(clip_size * 2)), int(clip_size * 2))
        surface.blit(clip_gs, (clip_x - int(clip_size * 2), clip_y - int(clip_size * 2)))

        # ── Eyes — BIGGER, sparklier ─────────────────────────────────────
        eye_y = int(cy - 2 + breath_offset)
        lex, rex = head_cx - int(26 * s), head_cx + int(26 * s)
        er = int(18 * s)  # Bigger eyes!

        blink = self._blink_amount

        if state_name == "SLEEPING":
            # Kawaii closed eyes (^ ^) with gentle breathing movement
            for ex in [lex, rex]:
                pygame.draw.arc(surface, self.config.neon_primary,
                                (ex - int(14 * s), eye_y - int(9 * s), int(28 * s), int(18 * s)),
                                math.pi * 0.15, math.pi * 0.85, max(2, int(3 * s)))
            # Zzz — floating upward
            font = pygame.font.SysFont("monospace", int(18 * s), bold=True)
            zoff = math.sin(t * 2) * 5 * s
            for i, ch in enumerate("Zzz"):
                alpha = int(200 - i * 40)
                z_s = font.render(ch, True, (*self.config.neon_accent, ))
                surface.blit(z_s, (head_cx + int(50 * s) + i * int(14 * s),
                                   eye_y - int(50 * s) - i * int(16 * s) + zoff))

        elif state_name == "HAPPY":
            # Happy closed eyes (n_n) with heart sparkles
            for ex in [lex, rex]:
                pygame.draw.arc(surface, self.config.neon_primary,
                                (ex - int(14 * s), eye_y - int(7 * s), int(28 * s), int(18 * s)),
                                math.pi * 1.15, math.pi * 1.85, max(2, int(3 * s)))
                # Heart sparkles instead of just stars
                hs = (6 + math.sin(t * 6) * 2) * s
                self._draw_heart(surface, ex + int(12 * s), eye_y - int(16 * s),
                                 hs, (255, 180, 220), int(200 + 55 * math.sin(t * 8)))
                ss = (4 + math.sin(t * 7) * 1.5) * s
                self._draw_star(surface, ex - int(10 * s), eye_y - int(14 * s), ss, (255, 230, 150), -t * 120)

        elif blink > 0.7:
            # Nearly closed — horizontal line
            for ex in [lex, rex]:
                squeeze = int(er * 2.3 * (1 - blink))
                if squeeze < 3:
                    pygame.draw.line(surface, self.config.neon_primary,
                                     (ex - er, eye_y), (ex + er, eye_y), 2)
                else:
                    erect = (ex - er, eye_y - squeeze // 2, er * 2, max(3, squeeze))
                    pygame.draw.ellipse(surface, (240, 240, 250), erect)
                    pygame.draw.ellipse(surface, (30, 28, 45), erect, 2)

        else:
            # Full open eyes (with partial blink squish) — bigger & sparklier
            squish = 1.0 - blink * 0.6
            for ex in [lex, rex]:
                ew = er * 2
                eh = int(er * 2.4 * squish)
                erect = (ex - er, eye_y - eh // 2, ew, eh)
                pygame.draw.ellipse(surface, (240, 240, 252), erect)

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

                # Iris gradient — lighter outer ring, darker center
                pygame.draw.circle(surface, iris_c, (icx, icy), ir)
                # Darker ring
                darker = tuple(max(0, c - 35) for c in iris_c)
                pygame.draw.circle(surface, darker, (icx, icy), ir, max(2, int(3 * s)))
                # Lighter inner ring
                lighter = tuple(min(255, c + 30) for c in iris_c)
                inner_r = ir - max(2, int(4 * s))
                if inner_r > 2:
                    ring_surf = pygame.Surface((inner_r * 2 + 4, inner_r * 2 + 4), pygame.SRCALPHA)
                    pygame.draw.circle(ring_surf, (*lighter, 60), (inner_r + 2, inner_r + 2), inner_r, 1)
                    surface.blit(ring_surf, (icx - inner_r - 2, icy - inner_r - 2))
                # Pupil
                pygame.draw.circle(surface, (8, 8, 18), (icx, icy), ir - max(2, int(5 * s)))

                # Star highlight — bigger, more of them
                self._draw_star(surface, icx - int(5 * s), icy - int(6 * s),
                                6 * s, (255, 255, 255), t * 30)
                # Secondary highlight
                pygame.draw.circle(surface, (255, 255, 255),
                                   (icx + int(4 * s), icy + int(3 * s)), max(1, int(3.5 * s)))
                # Third tiny sparkle
                pygame.draw.circle(surface, (220, 235, 255),
                                   (icx - int(3 * s), icy + int(5 * s)), max(1, int(1.5 * s)))
                # Fourth sparkle — twinkling
                twinkle = abs(math.sin(t * 4 + ex * 0.01))
                if twinkle > 0.7:
                    self._draw_star(surface, icx + int(6 * s), icy - int(3 * s),
                                    2 * s * twinkle, (255, 255, 255), -t * 60)
                # Eye outline
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

        # ── Whiskers ─────────────────────────────────────────────────────
        whisker_alpha = 80
        whisker_c = (*self.config.neon_primary, whisker_alpha)
        whisker_len = int(22 * s)
        whisker_y = int(cy + 16 * s + breath_offset)
        for side in [-1, 1]:
            wx = head_cx + side * int(30 * s)
            for wi, angle_offset in enumerate([-12, 0, 12]):
                angle = math.radians(angle_offset + side * 10)
                end_x = wx + side * int(whisker_len * math.cos(angle))
                end_y = whisker_y + int(whisker_len * math.sin(angle))
                # Whisker sway
                sway = math.sin(t * 2 + wi * 0.5) * 2 * s
                ws = pygame.Surface((abs(end_x - wx) + 10, 20), pygame.SRCALPHA)
                pygame.draw.line(surface, whisker_c[:3],
                                 (wx, whisker_y + int(sway)),
                                 (end_x, end_y + int(sway)), 1)

        # ── Mouth ────────────────────────────────────────────────────────
        my = int(cy + 24 * s + breath_offset)

        if state_name == "HAPPY":
            w = int(22 * s)
            pts = [(head_cx - w, my), (head_cx - w // 3, my + int(10 * s)), (head_cx, my + int(3 * s)),
                   (head_cx + w // 3, my + int(10 * s)), (head_cx + w, my)]
            pygame.draw.lines(surface, self.config.neon_secondary, False, pts, max(2, int(2 * s)))
            # Little fang
            pygame.draw.line(surface, (220, 220, 240),
                             (head_cx + int(8 * s), my),
                             (head_cx + int(6 * s), my + int(6 * s)), 2)
        elif state_name == "SPEAKING":
            mo = abs(math.sin(t * 8)) * 10 * s
            mw, mh = int(16 * s), max(int(4 * s), int(mo + 4 * s))
            pygame.draw.ellipse(surface, (30, 15, 40), (head_cx - mw // 2, my - 2, mw, mh))
            if mh > int(8 * s):
                # Tongue
                tw, th = int(8 * s), int(5 * s)
                pygame.draw.ellipse(surface, (200, 100, 120),
                                    (head_cx - tw // 2, my + mh - th - int(3 * s), tw, th))
            pygame.draw.ellipse(surface, self.config.neon_primary, (head_cx - mw // 2, my - 2, mw, mh), 2)
            # Tiny fang on the side
            fang_x = head_cx + int(6 * s)
            pygame.draw.line(surface, (220, 220, 240),
                             (fang_x, my - 1), (fang_x - int(1 * s), my + int(4 * s)), 2)
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
            # Sleep bubble
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
            # Cat mouth :3 — with tiny fang!
            cw = int(9 * s)
            pygame.draw.arc(surface, self.config.neon_primary,
                            (head_cx - cw - int(4 * s), my - int(3 * s), cw * 2, int(10 * s)),
                            math.pi * 1.1, math.pi * 1.9, 2)
            pygame.draw.arc(surface, self.config.neon_primary,
                            (head_cx - cw + int(4 * s), my - int(3 * s), cw * 2, int(10 * s)),
                            math.pi * 1.1, math.pi * 1.9, 2)
            # Cute little fang
            fang_x = head_cx + int(2 * s)
            fang_y = my + int(1 * s)
            pygame.draw.polygon(surface, (230, 230, 245), [
                (fang_x, fang_y),
                (fang_x - int(2 * s), fang_y + int(5 * s)),
                (fang_x + int(2 * s), fang_y + int(5 * s)),
            ])

        # ── Blush — always visible, more prominent ──────────────────────
        ba = 45  # Higher base alpha — always blushing a bit
        pulse = 0
        if state_name == "HAPPY": ba, pulse = 80, math.sin(t * 4) * 12
        elif state_name == "SPEAKING": ba, pulse = 60, math.sin(t * 3) * 6
        elif state_name == "LISTENING": ba = 55
        elif state_name == "ALARM": ba, pulse = 65, math.sin(t * 6) * 8
        elif state_name == "IDLE": pulse = math.sin(t * 1.5) * 3

        bw, bh = int((30 + pulse) * s), int((18 + pulse * 0.5) * s)
        blush = pygame.Surface((bw + 2, bh + 2), pygame.SRCALPHA)
        pygame.draw.ellipse(blush, (255, 130, 160, ba), (1, 1, bw, bh))

        for ex in [lex, rex]:
            bx, by = ex - bw // 2 - int(4 * s), eye_y + int(18 * s)
            surface.blit(blush, (bx, by))
            # Diagonal hash lines (always visible for cuteness)
            line_alpha = min(255, ba + 30)
            for i in range(3):
                lx = bx + int(6 * s) + i * int(6 * s)
                pygame.draw.line(surface, (*((255, 160, 180)), ),
                                 (lx, by + int(3 * s)),
                                 (lx + int(4 * s), by + int(10 * s)), max(1, int(s)))

        # ── Antenna ──────────────────────────────────────────────────────
        ant_tip_y = cy - head_radius * 0.9 - 32 * s + math.sin(t * 3) * 7 * s + breath_offset
        ant_tip_x = head_cx + int(8 * s)
        # Curvy antenna stalk
        mid_x = int(head_cx + 3 * s)
        mid_y = int(cy - head_radius * 0.9 - 15 * s + breath_offset)
        pygame.draw.line(surface, (90, 80, 120),
                         (int(head_cx - 2 * s), int(cy - head_radius * 0.9 + breath_offset)),
                         (mid_x, mid_y), max(2, int(2 * s)))
        pygame.draw.line(surface, (90, 80, 120),
                         (mid_x, mid_y),
                         (int(ant_tip_x), int(ant_tip_y)), max(2, int(2 * s)))

        orb_c = self.config.neon_primary
        if state_name == "HAPPY": orb_c = (255, 220, 100)
        elif state_name == "LISTENING": orb_c = self.config.neon_secondary
        elif state_name == "ALARM": orb_c = (255, 200, 50)

        orb_size = (7 + math.sin(t * 5) * 2.5) * s
        self._draw_star(surface, int(ant_tip_x), int(ant_tip_y), orb_size, orb_c, t * 60)
        # Bigger glow
        ga = int(35 + 25 * math.sin(t * 4))
        gr = int(14 * s)
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
        self._update_tail(dt, state_name, t)

        # ── Breathing ────────────────────────────────────────────────────
        if state_name == "SLEEPING":
            breath = math.sin(t * 1.2) * 1.0
        elif state_name == "IDLE":
            breath = math.sin(t * 1.8) * 0.5
        elif state_name == "SPEAKING":
            breath = math.sin(t * 3.5) * 0.3
        elif state_name == "ALARM":
            breath = math.sin(t * 5) * 0.6
        else:
            breath = math.sin(t * 2.0) * 0.3

        # ── Bob + scale ──────────────────────────────────────────────────
        bob = 0
        if state_name == "IDLE":
            bob = math.sin(t * self.config.chibi_bob_speed) * self.config.chibi_bob_amount
        elif state_name == "HAPPY":
            bob = abs(math.sin(t * 6)) * 14
        elif state_name == "ALARM":
            bob = abs(math.sin(t * 10)) * 15
        elif state_name == "THINKING":
            bob = math.sin(t * 1.5) * 4
        elif state_name == "SLEEPING":
            bob = breath * 5
        elif state_name == "SPEAKING":
            bob = math.sin(t * 3) * 3
        elif state_name == "LISTENING":
            bob = math.sin(t * 2.5) * 5

        # Wake pop — extra upward bounce
        if self.wake_transition > 0:
            bob -= self.wake_transition * 18

        dcy = cy + int(bob)
        self._update_floaties(cx, dcy, state_name, t, dt)

        # ── Shadow (reacts to height) ────────────────────────────────────
        sw = 95 + int(abs(bob) * 1.5)
        sa = max(15, 35 - abs(int(bob)))
        ss = pygame.Surface((sw, 18), pygame.SRCALPHA)
        pygame.draw.ellipse(ss, (0, 0, 0, sa), (0, 0, sw, 18))
        surface.blit(ss, (cx - sw // 2, cy + int(80 * self.scale)))

        # ── Draw character ───────────────────────────────────────────────
        self._draw_body(surface, cx, dcy, t, state_name, breath)
        self._draw_head(surface, cx, dcy - int(45 * self.scale), t, state_name, state_timer, breath)
        self._draw_floaties(surface)
        self._draw_wake_particles(surface)

        # ── State-specific overlays ──────────────────────────────────────
        if state_name == "THINKING":
            head_y = dcy - int(45 * self.scale)
            for i in range(3):
                da = abs(math.sin(t * 3 + i * 1.2))
                ds = int(4 + da * 5)
                self._draw_star(surface, cx + int(60 * self.scale) + i * int(18 * self.scale),
                                head_y - int(40 * self.scale) - i * int(14 * self.scale),
                                ds, (int(self.config.neon_accent[0] * da),
                                     int(self.config.neon_accent[1] * da),
                                     int(self.config.neon_accent[2] * da)), t * 120 + i * 40)

        if state_name == "LISTENING":
            for i in range(3):
                rp = (t * 1.5 + i * 0.4) % 1.0
                rr = int((80 + rp * 55) * self.scale)
                ra = int(70 * (1 - rp))
                rs = pygame.Surface((rr * 2 + 4, rr * 2 + 4), pygame.SRCALPHA)
                pygame.draw.circle(rs, (*self.config.neon_secondary, ra), (rr + 2, rr + 2), rr, width=2)
                surface.blit(rs, (cx - rr - 2, dcy - int(30 * self.scale) - rr - 2))
