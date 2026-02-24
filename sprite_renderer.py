"""
Chibi Renderer v2 — KAWAII EDITION
Procedurally draws an ultra-cute chibi avatar using Pygame primitives.
Bigger head-to-body ratio, rounder shapes, cat ear accessories,
sparkly star-pupil eyes, expressive mouth, animated cheek blush,
floating hearts, and lots of bounce.
"""

import pygame
import math
import random
from config import Config


class ChibiRenderer:
    def __init__(self, config: Config):
        self.config = config
        self.blink_timer = 0
        self.is_blinking = False
        self.scale = config.chibi_scale
        self.floaties: list[dict] = []
        self.floaty_timer = 0

    def _glow_circle(self, surface, color, center, radius, glow_radius=None, alpha=60):
        if glow_radius is None:
            glow_radius = radius + 8
        glow_surf = pygame.Surface((glow_radius * 2 + 4, glow_radius * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(glow_surf, (*color[:3], alpha),
                           (glow_radius + 2, glow_radius + 2), glow_radius)
        surface.blit(glow_surf, (center[0] - glow_radius - 2, center[1] - glow_radius - 2))
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
            if f['life'] > 0: new.append(f)
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
            elif f['type'] == 'note':
                ns = pygame.Surface((12, 12), pygame.SRCALPHA)
                pygame.draw.circle(ns, (*color, alpha), (4, 8), 3)
                pygame.draw.line(ns, (*color, alpha), (7, 8), (7, 1), 2)
                surface.blit(ns, (int(f['x']), int(f['y'])))

    def _draw_body(self, surface, cx, cy, t, state_name):
        s = self.scale
        body_w, body_h = int(44 * s), int(32 * s)
        trim = self.config.neon_primary

        # Rounded body
        bs = pygame.Surface((body_w + 4, body_h + 4), pygame.SRCALPHA)
        pygame.draw.ellipse(bs, (50, 45, 75), (2, 2, body_w, body_h))
        pygame.draw.ellipse(bs, trim, (2, 2, body_w, body_h), 2)

        # Bow detail
        pygame.draw.circle(bs, self.config.neon_secondary, (body_w // 2 + 2, 8), 4)
        pygame.draw.circle(bs, (255, 200, 230), (body_w // 2 + 2, 8), 2)

        # Circuit heart
        self._draw_heart(bs, body_w // 2 + 2, body_h // 2 + 2, 4, trim, 120)
        surface.blit(bs, (cx - body_w // 2 - 2, cy))

        # Arms
        arm_w, arm_h = int(14 * s), int(22 * s)
        la, ra = 0, 0
        if state_name == "HAPPY":
            la, ra = math.sin(t * 8) * 20, -math.sin(t * 8 + 0.5) * 20
        elif state_name == "SPEAKING":
            la, ra = math.sin(t * 3) * 8, -math.sin(t * 3 + 1) * 8
        elif state_name == "LISTENING":
            la, ra = math.sin(t * 2) * 5 + 10, -math.sin(t * 2) * 5 - 10

        for side, angle in [(-1, la), (1, ra)]:
            arm_s = pygame.Surface((arm_w + 4, arm_h + 4), pygame.SRCALPHA)
            pygame.draw.ellipse(arm_s, (60, 55, 85), (2, 2, arm_w, arm_h))
            pygame.draw.ellipse(arm_s, trim, (2, 2, arm_w, arm_h), 1)
            rotated = pygame.transform.rotate(arm_s, angle)
            surface.blit(rotated, (cx + side * (body_w // 2 + 4) - rotated.get_width() // 2, cy + 4))

        # Legs
        leg_r = int(8 * s)
        leg_y = cy + body_h - 4
        for side, phase in [(-1, 0), (1, 1)]:
            bounce = abs(math.sin(t * 8 + phase)) * 3 if state_name == "HAPPY" else 0
            lx, ly = cx + side * 10, leg_y + int(bounce)
            pygame.draw.circle(surface, (40, 38, 60), (lx, ly), leg_r)
            pygame.draw.circle(surface, trim, (lx, ly), leg_r, 1)
            pygame.draw.circle(surface, (80, 75, 110), (lx - 2, ly - 2), 2)

    def _draw_cat_ears(self, surface, head_cx, cy, head_radius, t, state_name):
        s = self.scale
        ear_size = int(22 * s)
        wiggle = 0
        if state_name == "LISTENING": wiggle = math.sin(t * 6) * 4
        elif state_name == "HAPPY": wiggle = math.sin(t * 4) * 3
        elif state_name == "IDLE": wiggle = math.sin(t * 1.5) * 1.5

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

    def _draw_head(self, surface, cx, cy, t, state_name, state_timer):
        s = self.scale
        head_radius = int(62 * s)

        tilt = 0
        if state_name == "THINKING": tilt = math.sin(t * 1.5) * 5
        elif state_name == "CONFUSED": tilt = math.sin(t * 3) * 7
        elif state_name == "SLEEPING": tilt = 10
        elif state_name == "HAPPY": tilt = math.sin(t * 4) * 2
        head_cx = cx + int(tilt)

        # Glow
        glow_c = self.config.neon_primary
        if state_name == "HAPPY": glow_c = (255, 200, 100)
        elif state_name == "SLEEPING": glow_c = (100, 80, 200)
        elif state_name == "LISTENING": glow_c = self.config.neon_secondary

        gs = pygame.Surface((head_radius * 3, head_radius * 3), pygame.SRCALPHA)
        pygame.draw.circle(gs, (*glow_c, 18), (head_radius * 3 // 2, head_radius * 3 // 2), head_radius + 15)
        surface.blit(gs, (head_cx - head_radius * 3 // 2, cy - head_radius * 3 // 2))

        # Head (slightly squished oval)
        head_w = head_radius * 2 + 4
        head_h = int(head_radius * 1.9)
        head_rect = (head_cx - head_radius - 2, cy - head_h // 2, head_w, head_h)
        pygame.draw.ellipse(surface, (55, 50, 72), head_rect)
        pygame.draw.ellipse(surface, self.config.neon_primary, head_rect, 2)

        # Cat ears
        self._draw_cat_ears(surface, head_cx, cy, head_radius, t, state_name)

        # Hair bangs
        hair_c = (35, 32, 55)
        for i in range(5):
            bx = head_cx - 30 + i * 15
            pygame.draw.circle(surface, hair_c, (bx, cy - head_h // 2 + 5), int(18 + math.sin(i * 1.3) * 5))
        for side in [-1, 1]:
            bang_x = head_cx + side * (head_radius - 5)
            for j in range(3):
                pygame.draw.circle(surface, hair_c, (bang_x, cy - 20 + j * 12), 12 - j * 2)
        # Hair shine
        pygame.draw.arc(surface, (100, 90, 140), (head_cx - 15, cy - head_h // 2 + 8, 30, 8), 0, math.pi, 2)

        # ── Eyes ─────────────────────────────────────────────────────────
        eye_y = cy - 2
        lex, rex = head_cx - int(24 * s), head_cx + int(24 * s)
        er = int(16 * s)

        self.blink_timer += 1 / 30
        if not self.is_blinking and self.blink_timer > self.config.chibi_blink_interval:
            self.is_blinking = True; self.blink_timer = 0
        if self.is_blinking and self.blink_timer > self.config.chibi_blink_duration:
            self.is_blinking = False; self.blink_timer = 0

        if state_name == "SLEEPING":
            for ex in [lex, rex]:
                pygame.draw.arc(surface, self.config.neon_primary, (ex - 12, eye_y - 8, 24, 16),
                                math.pi * 0.15, math.pi * 0.85, 3)
            font = pygame.font.SysFont("monospace", 18, bold=True)
            zoff = math.sin(t * 2) * 5
            for i, ch in enumerate("Zzz"):
                surface.blit(font.render(ch, True, self.config.neon_accent),
                             (head_cx + 45 + i * 14, cy - 55 - i * 16 + zoff))

        elif state_name == "HAPPY":
            for ex in [lex, rex]:
                pygame.draw.arc(surface, self.config.neon_primary, (ex - 12, eye_y - 6, 24, 16),
                                math.pi * 1.15, math.pi * 1.85, 3)
                ss = 5 + math.sin(t * 6) * 2
                self._draw_star(surface, ex + 10, eye_y - 14, ss, (255, 230, 150), t * 90)
                self._draw_star(surface, ex - 8, eye_y - 12, ss * 0.6, (255, 200, 255), -t * 120)

        elif self.is_blinking:
            for ex in [lex, rex]:
                pygame.draw.arc(surface, self.config.neon_primary, (ex - 10, eye_y - 3, 20, 8),
                                math.pi * 0.1, math.pi * 0.9, 2)
        else:
            for ex in [lex, rex]:
                ew, eh = er * 2, int(er * 2.3)
                erect = (ex - er, eye_y - eh // 2, ew, eh)
                pygame.draw.ellipse(surface, (235, 235, 245), erect)

                iris_c = self.config.neon_primary
                if state_name == "CONFUSED": iris_c = self.config.neon_secondary
                elif state_name == "THINKING": iris_c = self.config.neon_accent
                elif state_name == "LISTENING": iris_c = (150, 200, 255)

                pox, poy = 0, 0
                if state_name == "THINKING":
                    pox, poy = int(math.sin(t * 2) * 4), int(math.cos(t * 2) * 3) - 2

                icx, icy = ex + pox, eye_y + poy
                ir = er - 2
                pygame.draw.circle(surface, iris_c, (icx, icy), ir)
                pygame.draw.circle(surface, tuple(max(0, c - 40) for c in iris_c), (icx, icy), ir, 3)
                pygame.draw.circle(surface, (8, 8, 18), (icx, icy), ir - 5)

                # Star highlight!
                self._draw_star(surface, icx - 4, icy - 5, 5, (255, 255, 255), t * 30)
                pygame.draw.circle(surface, (255, 255, 255), (icx + 4, icy + 3), 3)
                pygame.draw.circle(surface, (200, 220, 255), (icx - 2, icy + 5), 1)
                pygame.draw.ellipse(surface, (30, 28, 45), erect, 2)

            if state_name == "CONFUSED":
                for ex in [lex, rex]:
                    for a in range(0, 720, 30):
                        rad = math.radians(a + t * 200)
                        r = (8 + math.sin(t * 3) * 2) * (a / 720)
                        pygame.draw.circle(surface, self.config.neon_secondary,
                                           (int(ex + math.cos(rad) * r), int(eye_y + math.sin(rad) * r)), 1)

        # ── Mouth ────────────────────────────────────────────────────────
        my = cy + int(22 * s)

        if state_name == "HAPPY":
            w = 20
            pts = [(head_cx - w, my), (head_cx - w // 3, my + 8), (head_cx, my + 2),
                   (head_cx + w // 3, my + 8), (head_cx + w, my)]
            pygame.draw.lines(surface, self.config.neon_secondary, False, pts, 2)
            pygame.draw.line(surface, (220, 220, 235), (head_cx + 8, my), (head_cx + 6, my + 5), 2)
        elif state_name == "SPEAKING":
            mo = abs(math.sin(t * 8)) * 10
            mw, mh = 16, max(4, int(mo + 4))
            pygame.draw.ellipse(surface, (30, 15, 40), (head_cx - mw // 2, my - 2, mw, mh))
            if mh > 8:
                pygame.draw.ellipse(surface, (200, 100, 120), (head_cx - 4, my + mh - 8, 8, 5))
            pygame.draw.ellipse(surface, self.config.neon_primary, (head_cx - mw // 2, my - 2, mw, mh), 2)
        elif state_name == "CONFUSED":
            pts = [(head_cx - 14 + i * 2, my + math.sin(t * 4 + i * 0.7) * 4) for i in range(16)]
            if len(pts) > 1: pygame.draw.lines(surface, self.config.neon_secondary, False, pts, 2)
        elif state_name == "THINKING":
            pygame.draw.circle(surface, (30, 15, 40), (head_cx + 3, my + 3), 6)
            pygame.draw.circle(surface, self.config.neon_accent, (head_cx + 3, my + 3), 6, 2)
        elif state_name == "SLEEPING":
            pygame.draw.arc(surface, self.config.neon_primary, (head_cx - 10, my - 2, 20, 10),
                            math.pi * 1.1, math.pi * 1.9, 2)
            dy = my + 6 + abs(math.sin(t * 2)) * 4
            pygame.draw.circle(surface, (150, 180, 220), (head_cx + 8, int(dy)), 2)
        elif state_name == "LISTENING":
            pygame.draw.ellipse(surface, (30, 15, 40), (head_cx - 5, my, 10, 8))
            pygame.draw.ellipse(surface, self.config.neon_primary, (head_cx - 5, my, 10, 8), 1)
        else:
            # Cat mouth :3
            cw = 8
            pygame.draw.arc(surface, self.config.neon_primary,
                            (head_cx - cw - 4, my - 3, cw * 2, 10), math.pi * 1.1, math.pi * 1.9, 2)
            pygame.draw.arc(surface, self.config.neon_primary,
                            (head_cx - cw + 4, my - 3, cw * 2, 10), math.pi * 1.1, math.pi * 1.9, 2)

        # ── Blush cheeks ─────────────────────────────────────────────────
        ba = 35
        pulse = 0
        if state_name == "HAPPY": ba, pulse = 70, math.sin(t * 4) * 10
        elif state_name == "SPEAKING": ba, pulse = 50, math.sin(t * 3) * 5
        elif state_name == "LISTENING": ba = 45

        bw, bh = int(28 + pulse), int(16 + pulse * 0.5)
        blush = pygame.Surface((bw + 2, bh + 2), pygame.SRCALPHA)
        pygame.draw.ellipse(blush, (255, 120, 150, ba), (1, 1, bw, bh))

        for ex in [lex, rex]:
            bx, by = ex - bw // 2 - 4, eye_y + int(16 * s)
            surface.blit(blush, (bx, by))
            if ba > 40:
                for i in range(3):
                    lx = bx + 6 + i * 6
                    pygame.draw.line(surface, (255, 150, 170), (lx, by + 3), (lx + 4, by + 9), 1)

        # ── Antenna star ─────────────────────────────────────────────────
        ant_tip_y = cy - head_radius * 0.9 - 30 + math.sin(t * 3) * 6
        ant_tip_x = head_cx + 8
        pygame.draw.line(surface, (80, 75, 110),
                         (int(head_cx - 2), int(cy - head_radius * 0.9)),
                         (int(ant_tip_x), int(ant_tip_y)), 2)

        orb_c = self.config.neon_primary
        if state_name == "HAPPY": orb_c = (255, 220, 100)
        elif state_name == "LISTENING": orb_c = self.config.neon_secondary

        self._draw_star(surface, int(ant_tip_x), int(ant_tip_y),
                        6 + math.sin(t * 5) * 2, orb_c, t * 60)
        ga = int(30 + 20 * math.sin(t * 4))
        gsurf = pygame.Surface((30, 30), pygame.SRCALPHA)
        pygame.draw.circle(gsurf, (*orb_c, ga), (15, 15), 12)
        surface.blit(gsurf, (int(ant_tip_x) - 15, int(ant_tip_y) - 15))

    def draw(self, surface, cx, cy, state, state_timer, t):
        state_name = state.name
        dt = 1 / 30

        bob = 0
        if state_name == "IDLE": bob = math.sin(t * self.config.chibi_bob_speed) * self.config.chibi_bob_amount
        elif state_name == "HAPPY": bob = abs(math.sin(t * 6)) * 12
        elif state_name == "THINKING": bob = math.sin(t * 1.5) * 4
        elif state_name == "SLEEPING": bob = math.sin(t * 0.8) * 5
        elif state_name == "SPEAKING": bob = math.sin(t * 3) * 3
        elif state_name == "LISTENING": bob = math.sin(t * 2.5) * 4

        dcy = cy + int(bob)
        self._update_floaties(cx, dcy, state_name, t, dt)

        # Shadow
        sw = 90 + int(abs(bob) * 1.5)
        sa = max(15, 35 - abs(int(bob)))
        ss = pygame.Surface((sw, 18), pygame.SRCALPHA)
        pygame.draw.ellipse(ss, (0, 0, 0, sa), (0, 0, sw, 18))
        surface.blit(ss, (cx - sw // 2, cy + 80))

        self._draw_body(surface, cx, dcy, t, state_name)
        self._draw_head(surface, cx, dcy - 50, t, state_name, state_timer)
        self._draw_floaties(surface)

        if state_name == "THINKING":
            for i in range(3):
                da = abs(math.sin(t * 3 + i * 1.2))
                ds = int(4 + da * 5)
                self._draw_star(surface, cx + 55 + i * 18, dcy - 50 - 35 - i * 14,
                                ds, (int(self.config.neon_accent[0] * da),
                                     int(self.config.neon_accent[1] * da),
                                     int(self.config.neon_accent[2] * da)), t * 120 + i * 40)

        if state_name == "LISTENING":
            for i in range(3):
                rp = (t * 1.5 + i * 0.4) % 1.0
                rr = int(75 + rp * 50)
                ra = int(70 * (1 - rp))
                rs = pygame.Surface((rr * 2 + 4, rr * 2 + 4), pygame.SRCALPHA)
                pygame.draw.circle(rs, (*self.config.neon_secondary, ra), (rr + 2, rr + 2), rr, width=2)
                surface.blit(rs, (cx - rr - 2, dcy - 30 - rr - 2))
