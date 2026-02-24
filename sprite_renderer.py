"""
Chibi Renderer — Procedurally draws the chibi avatar using Pygame primitives.
No external sprite sheets needed! Everything is drawn with circles, ellipses, and shapes.
Cyberpunk-themed with neon glow effects.
"""

import pygame
import math
from config import Config


class ChibiRenderer:
    def __init__(self, config: Config):
        self.config = config
        self.blink_timer = 0
        self.is_blinking = False

        # Precompute some values
        self.scale = config.chibi_scale

    def _glow_circle(self, surface, color, center, radius, glow_radius=None, alpha=60):
        """Draw a circle with a soft glow behind it."""
        if glow_radius is None:
            glow_radius = radius + 8

        # Glow layer
        glow_surf = pygame.Surface((glow_radius * 2 + 4, glow_radius * 2 + 4), pygame.SRCALPHA)
        glow_color = (*color[:3], alpha)
        pygame.draw.circle(glow_surf, glow_color,
                           (glow_radius + 2, glow_radius + 2), glow_radius)
        surface.blit(glow_surf,
                     (center[0] - glow_radius - 2, center[1] - glow_radius - 2))

        # Solid circle
        pygame.draw.circle(surface, color, center, radius)

    def _draw_body(self, surface, cx, cy, t, state_name):
        """Draw the small chibi body."""
        s = self.scale
        # Body (small trapezoid-ish rectangle)
        body_color = (30, 30, 60)
        body_w = int(50 * s)
        body_h = int(40 * s)
        body_rect = pygame.Rect(cx - body_w // 2, cy, body_w, body_h)
        pygame.draw.rect(surface, body_color, body_rect, border_radius=8)

        # Neon trim on body
        trim_color = self.config.neon_primary
        pygame.draw.rect(surface, trim_color, body_rect, width=2, border_radius=8)

        # Circuit pattern on body
        line_y = cy + body_h // 3
        pygame.draw.line(surface, (*trim_color, ), (cx - 15, line_y), (cx + 15, line_y), 1)
        pygame.draw.circle(surface, trim_color, (cx, line_y), 3)

        # Arms (small ovals to the sides)
        arm_color = (40, 40, 70)
        # Left arm
        arm_surf = pygame.Surface((20, 30), pygame.SRCALPHA)
        pygame.draw.ellipse(arm_surf, arm_color, (0, 0, 16, 28))
        pygame.draw.ellipse(arm_surf, trim_color, (0, 0, 16, 28), 1)

        # Arm wave animation when happy
        left_angle = 0
        right_angle = 0
        if state_name == "HAPPY":
            left_angle = math.sin(t * 8) * 15
            right_angle = -math.sin(t * 8) * 15
        elif state_name == "SPEAKING":
            left_angle = math.sin(t * 3) * 5
            right_angle = -math.sin(t * 3 + 1) * 5

        # Left arm
        la = pygame.transform.rotate(arm_surf, left_angle)
        surface.blit(la, (cx - body_w // 2 - 12, cy + 5))
        # Right arm
        ra = pygame.transform.rotate(arm_surf, right_angle)
        surface.blit(ra, (cx + body_w // 2 - 4, cy + 5))

        # Legs (two small stumps)
        leg_color = (25, 25, 50)
        leg_w = int(14 * s)
        leg_h = int(16 * s)
        # Left leg
        pygame.draw.rect(surface, leg_color,
                         (cx - 16, cy + body_h - 2, leg_w, leg_h), border_radius=4)
        pygame.draw.rect(surface, trim_color,
                         (cx - 16, cy + body_h - 2, leg_w, leg_h), width=1, border_radius=4)
        # Right leg
        pygame.draw.rect(surface, leg_color,
                         (cx + 4, cy + body_h - 2, leg_w, leg_h), border_radius=4)
        pygame.draw.rect(surface, trim_color,
                         (cx + 4, cy + body_h - 2, leg_w, leg_h), width=1, border_radius=4)

    def _draw_head(self, surface, cx, cy, t, state_name, state_timer):
        """Draw the oversized chibi head."""
        s = self.scale

        head_radius = int(55 * s)

        # Head tilt
        tilt = 0
        if state_name == "THINKING":
            tilt = math.sin(t * 1.5) * 4
        elif state_name == "CONFUSED":
            tilt = math.sin(t * 3) * 6
        elif state_name == "SLEEPING":
            tilt = 8

        # Head shadow/glow
        glow_surf = pygame.Surface((head_radius * 3, head_radius * 3), pygame.SRCALPHA)
        pygame.draw.circle(glow_surf, (*self.config.neon_primary, 15),
                           (head_radius * 3 // 2, head_radius * 3 // 2), head_radius + 12)
        surface.blit(glow_surf,
                     (cx - head_radius * 3 // 2 + int(tilt), cy - head_radius * 3 // 2))

        # Main head circle
        head_color = (45, 42, 58)
        head_cx = cx + int(tilt)
        pygame.draw.circle(surface, head_color, (head_cx, cy), head_radius)

        # Head outline glow
        pygame.draw.circle(surface, self.config.neon_primary,
                           (head_cx, cy), head_radius, width=2)

        # Hair (spiky top)
        hair_color = (20, 20, 45)
        hair_points_left = [
            (head_cx - 35, cy - head_radius + 15),
            (head_cx - 50, cy - head_radius - 20),
            (head_cx - 20, cy - head_radius + 5),
        ]
        hair_points_mid = [
            (head_cx - 15, cy - head_radius + 5),
            (head_cx, cy - head_radius - 30),
            (head_cx + 15, cy - head_radius + 5),
        ]
        hair_points_right = [
            (head_cx + 20, cy - head_radius + 5),
            (head_cx + 50, cy - head_radius - 15),
            (head_cx + 35, cy - head_radius + 15),
        ]

        for pts in [hair_points_left, hair_points_mid, hair_points_right]:
            pygame.draw.polygon(surface, hair_color, pts)
            pygame.draw.polygon(surface, self.config.neon_secondary, pts, width=1)

        # ── Eyes ─────────────────────────────────────────────────────────
        eye_y = cy - 5
        left_eye_x = head_cx - 22
        right_eye_x = head_cx + 22
        eye_radius = int(14 * s)

        # Blink logic
        self.blink_timer += 1 / 30  # approximate dt
        if not self.is_blinking and self.blink_timer > self.config.chibi_blink_interval:
            self.is_blinking = True
            self.blink_timer = 0
        if self.is_blinking and self.blink_timer > self.config.chibi_blink_duration:
            self.is_blinking = False
            self.blink_timer = 0

        if state_name == "SLEEPING":
            # Closed eyes — two curved lines
            for ex in [left_eye_x, right_eye_x]:
                pygame.draw.arc(surface, self.config.neon_primary,
                                (ex - 10, eye_y - 5, 20, 14),
                                math.pi * 0.1, math.pi * 0.9, 2)
            # Zzz
            font = pygame.font.SysFont("monospace", 16)
            zzz_offset = math.sin(t * 2) * 5
            for i, char in enumerate("Zzz"):
                z_surf = font.render(char, True, self.config.neon_accent)
                surface.blit(z_surf, (head_cx + 40 + i * 12,
                                      cy - 50 - i * 14 + zzz_offset))

        elif self.is_blinking:
            # Blink — horizontal lines
            for ex in [left_eye_x, right_eye_x]:
                pygame.draw.line(surface, self.config.neon_primary,
                                 (ex - 10, eye_y), (ex + 10, eye_y), 2)
        else:
            # Normal eyes
            for ex in [left_eye_x, right_eye_x]:
                # White of eye
                pygame.draw.circle(surface, (220, 220, 240), (ex, eye_y), eye_radius)

                # Iris
                iris_color = self.config.neon_primary
                if state_name == "HAPPY":
                    iris_color = self.config.neon_warning
                elif state_name == "CONFUSED":
                    iris_color = self.config.neon_secondary
                elif state_name == "THINKING":
                    iris_color = self.config.neon_accent

                pygame.draw.circle(surface, iris_color, (ex, eye_y), eye_radius - 4)

                # Pupil
                pupil_offset_x = 0
                pupil_offset_y = 0
                if state_name == "THINKING":
                    pupil_offset_x = int(math.sin(t * 2) * 3)
                    pupil_offset_y = int(math.cos(t * 2) * 2) - 2

                pygame.draw.circle(surface, (10, 10, 20),
                                   (ex + pupil_offset_x, eye_y + pupil_offset_y),
                                   eye_radius - 8)

                # Highlight/shine
                pygame.draw.circle(surface, (255, 255, 255),
                                   (ex - 4 + pupil_offset_x, eye_y - 4 + pupil_offset_y), 4)
                pygame.draw.circle(surface, (255, 255, 255),
                                   (ex + 3 + pupil_offset_x, eye_y + 2 + pupil_offset_y), 2)

            # Happy sparkle eyes
            if state_name == "HAPPY":
                for ex in [left_eye_x, right_eye_x]:
                    # Star sparkle
                    spark_size = 4 + math.sin(t * 6) * 2
                    for angle in range(0, 360, 45):
                        rad = math.radians(angle)
                        sx = ex + math.cos(rad) * spark_size * 2
                        sy = eye_y + math.sin(rad) * spark_size * 2
                        pygame.draw.circle(surface, (255, 255, 200),
                                           (int(sx), int(sy)), max(1, int(spark_size * 0.4)))

        # ── Mouth ────────────────────────────────────────────────────────
        mouth_y = cy + 18

        if state_name == "HAPPY":
            # Big smile — arc
            pygame.draw.arc(surface, self.config.neon_primary,
                            (head_cx - 16, mouth_y - 8, 32, 20),
                            math.pi * 1.1, math.pi * 1.9, 2)
        elif state_name == "SPEAKING":
            # Animated mouth — opens and closes
            mouth_open = abs(math.sin(t * 8)) * 8
            pygame.draw.ellipse(surface, (30, 10, 40),
                                (head_cx - 8, mouth_y - 2,
                                 16, max(4, int(mouth_open + 4))))
            pygame.draw.ellipse(surface, self.config.neon_primary,
                                (head_cx - 8, mouth_y - 2,
                                 16, max(4, int(mouth_open + 4))), 1)
        elif state_name == "CONFUSED":
            # Wavy mouth
            points = []
            for i in range(12):
                px = head_cx - 10 + i * 2
                py = mouth_y + math.sin(t * 4 + i * 0.8) * 3
                points.append((px, py))
            if len(points) > 1:
                pygame.draw.lines(surface, self.config.neon_secondary, False, points, 2)
        elif state_name == "THINKING":
            # Small 'o' mouth
            pygame.draw.circle(surface, (30, 10, 40), (head_cx, mouth_y + 2), 5)
            pygame.draw.circle(surface, self.config.neon_accent, (head_cx, mouth_y + 2), 5, 1)
        elif state_name == "SLEEPING":
            # Gentle curved line
            pygame.draw.arc(surface, self.config.neon_primary,
                            (head_cx - 10, mouth_y - 4, 20, 12),
                            math.pi * 1.1, math.pi * 1.9, 1)
        else:
            # Idle — small smile
            pygame.draw.arc(surface, self.config.neon_primary,
                            (head_cx - 12, mouth_y - 4, 24, 14),
                            math.pi * 1.15, math.pi * 1.85, 2)

        # ── Blush (always present, stronger when happy) ──────────────────
        blush_alpha = 25
        if state_name == "HAPPY":
            blush_alpha = 50
        elif state_name == "SPEAKING":
            blush_alpha = 35

        blush_surf = pygame.Surface((24, 14), pygame.SRCALPHA)
        pygame.draw.ellipse(blush_surf, (255, 100, 130, blush_alpha), (0, 0, 24, 14))

        surface.blit(blush_surf, (left_eye_x - 16, eye_y + 12))
        surface.blit(blush_surf, (right_eye_x - 8, eye_y + 12))

        # ── Antenna / accessory ──────────────────────────────────────────
        antenna_base = (head_cx + 5, cy - head_radius + 5)
        antenna_tip = (head_cx + 15, cy - head_radius - 25 + math.sin(t * 3) * 5)
        pygame.draw.line(surface, (60, 60, 80), antenna_base, antenna_tip, 2)

        # Glowing orb on antenna
        orb_pulse = 0.5 + 0.5 * math.sin(t * 4)
        orb_color = (
            int(self.config.neon_primary[0] * orb_pulse),
            int(self.config.neon_primary[1] * orb_pulse),
            int(self.config.neon_primary[2] * orb_pulse),
        )
        self._glow_circle(surface, orb_color,
                          (int(antenna_tip[0]), int(antenna_tip[1])), 4, 10,
                          alpha=int(40 * orb_pulse))

    def draw(self, surface, cx, cy, state, state_timer, t):
        """
        Main draw call. Renders the full chibi character.
        cx, cy = center position for the character
        """
        state_name = state.name

        # Idle bob animation
        bob_offset = 0
        if state_name == "IDLE":
            bob_offset = math.sin(t * self.config.chibi_bob_speed) * self.config.chibi_bob_amount
        elif state_name == "HAPPY":
            bob_offset = abs(math.sin(t * 6)) * 8  # Bouncy!
        elif state_name == "THINKING":
            bob_offset = math.sin(t * 1.5) * 3
        elif state_name == "SLEEPING":
            bob_offset = math.sin(t * 0.8) * 4

        draw_cy = cy + int(bob_offset)

        # Character shadow
        shadow_surf = pygame.Surface((100, 20), pygame.SRCALPHA)
        shadow_alpha = max(20, 40 - abs(int(bob_offset)))
        pygame.draw.ellipse(shadow_surf, (0, 0, 0, shadow_alpha), (0, 0, 100, 20))
        surface.blit(shadow_surf, (cx - 50, cy + 80))

        # Draw body first (behind head)
        self._draw_body(surface, cx, draw_cy, t, state_name)

        # Draw head (overlapping body — chibi style!)
        head_cy = draw_cy - 45
        self._draw_head(surface, cx, head_cy, t, state_name, state_timer)

        # ── Thinking dots ────────────────────────────────────────────────
        if state_name == "THINKING":
            for i in range(3):
                dot_alpha = abs(math.sin(t * 3 + i * 1.2))
                dot_size = int(3 + dot_alpha * 4)
                dot_x = cx + 50 + i * 16
                dot_y = head_cy - 30 - i * 12
                color = (
                    int(self.config.neon_accent[0] * dot_alpha),
                    int(self.config.neon_accent[1] * dot_alpha),
                    int(self.config.neon_accent[2] * dot_alpha),
                )
                self._glow_circle(surface, color, (dot_x, dot_y), dot_size, dot_size + 6,
                                  alpha=int(30 * dot_alpha))

        # ── Listening indicator — pulsing rings ──────────────────────────
        if state_name == "LISTENING":
            for i in range(3):
                ring_progress = (t * 1.5 + i * 0.4) % 1.0
                ring_radius = int(70 + ring_progress * 50)
                ring_alpha = int(80 * (1 - ring_progress))
                ring_surf = pygame.Surface(
                    (ring_radius * 2 + 4, ring_radius * 2 + 4), pygame.SRCALPHA
                )
                ring_color = (*self.config.neon_secondary, ring_alpha)
                pygame.draw.circle(
                    ring_surf, ring_color,
                    (ring_radius + 2, ring_radius + 2), ring_radius, width=2
                )
                surface.blit(ring_surf,
                             (cx - ring_radius - 2, draw_cy - 30 - ring_radius - 2))
