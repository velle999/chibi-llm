"""
Chibi's speech bubble — the typewriter text over her head.

Its own module because two things draw it: the kiosk window (main.py) and the
desktop buddy (buddy.py), which runs in a separate process and must not import
main.py and everything main.py imports. One bubble, so the two cannot drift
into different looks.
"""

import textwrap

import pygame

from config import Config


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
        # Bumped for every new thing said, so a reader in another process can
        # tell "she said it again" from "the same words are still up".
        self.serial = 0
        self._layout_key = None
        self._layout = None
        self._drawable = {}         # char -> does the font have it

    def init_font(self):
        self.font = pygame.font.SysFont("monospace", self.config.bubble_font_size)

    def set_text(self, text: str):
        # A streamed reply arrives as the same text growing a chunk at a time.
        # Starting again from the first letter on every chunk meant the bubble
        # kept blanking and re-typing its opening words until the stream ended;
        # carry on from where the typing had got to instead.
        if (self.visible and self.target_text and text != self.target_text
                and text.startswith(self.target_text)):
            self.target_text = text
            return
        self.serial += 1
        self.target_text = text
        self.char_index = 0
        self.text = ""
        self.visible = True

    def hide(self):
        self.visible = False
        self.text = ""
        self.target_text = ""

    @property
    def fully_typed(self) -> bool:
        return self.char_index >= len(self.target_text)

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

    # The tail hangs this far below the box. Its tip is ON row TAIL, so the
    # surface is TAIL + 1 rows taller than the box.
    TAIL = 12

    def _lines(self):
        """(line surfaces, box width, box height) for the text typed so far,
        or None. Cached per text, since size() and render() both need it."""
        if not self.text:
            return None
        key = (self.text, self.config.bubble_max_width, self.config.bubble_font_size)
        if key == self._layout_key:
            return self._layout
        if not self.font:
            self.init_font()

        max_w = self.config.bubble_max_width
        wrapped = textwrap.wrap(self._drawable_text(self.text),
                                width=max_w // (self.config.bubble_font_size * 0.6))
        layout = None
        if wrapped:
            line_surfs = [self.font.render(line, True, self.config.bubble_text_color) for line in wrapped]
            total_h = sum(s.get_height() for s in line_surfs) + 8 * len(line_surfs)
            max_line_w = max(s.get_width() for s in line_surfs)
            pad = 16
            layout = (line_surfs, max_line_w + pad * 2, total_h + pad * 2)
        self._layout_key, self._layout = key, layout
        return layout

    def _drawable_text(self, text):
        """The text without the characters the font cannot draw. The prompt
        asks for :3-style emoticons, but a model still puts emoji in, and the
        monospace font draws each one as an empty box."""
        out = []
        for c in text:
            if ord(c) < 128:
                out.append(c)
                continue
            ok = self._drawable.get(c)
            if ok is None:
                metrics = self.font.metrics(c)
                ok = self._drawable[c] = bool(metrics) and metrics[0] is not None
            if ok:
                out.append(c)
        return "".join(out)

    def size(self):
        """(width, height) of what render() would return, tail included."""
        layout = self._lines()
        if self.alpha <= 0 or layout is None:
            return None
        return layout[1], layout[2] + self.TAIL + 1

    def render(self, tail_dx=0):
        """The bubble on a surface of its own, tail included, or None when
        there is nothing to show. The tail's tip is at the bottom, tail_dx
        from the centre — for a bubble pushed sideways to stay on screen that
        still has to point at who is talking."""
        layout = self._lines()
        if self.alpha <= 0 or layout is None:
            return None
        line_surfs, bw, bh = layout
        pad = 16

        surf = pygame.Surface((bw, bh + self.TAIL + 1), pygame.SRCALPHA)
        bg = (*self.config.bubble_bg_color, int(self.alpha * 0.85))
        pygame.draw.rect(surf, bg, (0, 0, bw, bh), border_radius=12)

        # Border glow
        border_color = (*self.config.neon_primary, int(self.alpha * 0.6))
        pygame.draw.rect(surf, border_color, (0, 0, bw, bh), width=2, border_radius=12)

        # Draw text
        y_offset = pad
        for ls in line_surfs:
            surf.blit(ls, (pad, y_offset))
            y_offset += ls.get_height() + 8

        # Speech tail, kept clear of the rounded corners
        tx = int(max(20, min(bw - 20, bw // 2 + tail_dx)))
        pygame.draw.polygon(surf, bg, [(tx - 8, bh), (tx + 8, bh), (tx, bh + self.TAIL)])
        return surf

    def draw(self, surface, cx, top_y):
        surf = self.render()
        if surf is None:
            return
        # The box's bottom edge sits 20 px above top_y, its tail hanging 12 px
        # below that — where the kiosk has always drawn it.
        bh = surf.get_height() - self.TAIL - 1
        surface.blit(surf, (cx - surf.get_width() // 2, top_y - bh - 20))
