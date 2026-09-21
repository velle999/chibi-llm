"""
Chibi's speech bubble — the typewriter text over her head.

Its own module because two things draw it: the kiosk window (main.py) and the
desktop buddy (buddy.py), which runs in a separate process and must not import
main.py and everything main.py imports. One bubble, so the two cannot drift
into different looks.

A reply can be longer than the space above her head (a story runs to dozens of
lines), so the caller passes the height it has room for. A bubble with more
lines than that shows as many as fit, follows the typing to the newest line,
and draws a scrollbar. In the kiosk it can be dragged or wheeled back through;
scrolling to the bottom resumes following.
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
        self._line_surfs = {}       # line text -> surface, visible lines only
        # First line shown when scrolled back; None follows the newest line.
        self.scroll_top = None
        # (first, shown, total, line height) from the last render, for scrolling.
        self._window_seen = None
        # Where draw() last put the box on screen, for hit tests. Kiosk only.
        self.rect = None
        self._drag = None           # (mode, start y, start first line)

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
        self.scroll_top = None
        self._drag = None

    def hide(self):
        self.visible = False
        self.text = ""
        self.target_text = ""
        self.scroll_top = None
        self._drag = None

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
    PAD = 16                # text inset from the box edge
    GAP = 8                 # space under each line
    MIN_LINES = 3           # never cap a bubble shorter than this
    BAR_W = 4               # scrollbar, drawn in the right padding

    def _lines(self):
        """(wrapped lines, box width, line height) for the text typed so far,
        or None. Cached per text, since size() and render() both need it.

        Lines are only measured here, not rendered: a story is dozens of lines
        and the text changes with every typed character, so render() draws
        just the lines that are on screen."""
        if not self.text:
            return None
        key = (self.text, self.config.bubble_max_width, self.config.bubble_font_size)
        if key == self._layout_key:
            return self._layout
        if not self.font:
            self.init_font()

        max_w = self.config.bubble_max_width
        width = max_w // (self.config.bubble_font_size * 0.6)
        # Each paragraph wraps on its own, with an empty line between, so a
        # story keeps its paragraphs instead of running together.
        wrapped = []
        for para in self._drawable_text(self.text).split("\n"):
            wrapped.extend(textwrap.wrap(para, width=width) or [""])
        while wrapped and not wrapped[0]:
            wrapped.pop(0)
        while wrapped and not wrapped[-1]:
            wrapped.pop()
        layout = None
        if wrapped:
            max_line_w = max(self.font.size(line)[0] for line in wrapped)
            layout = (wrapped, max_line_w + self.PAD * 2, self.font.get_height())
        self._layout_key, self._layout = key, layout
        return layout

    def _window(self, layout, max_height):
        """(first line, lines shown, total lines) for a surface no taller than
        max_height, tail included. None means no limit."""
        lines, _bw, line_h = layout
        total = len(lines)
        shown = total
        if max_height is not None:
            room = max_height - self.TAIL - 1 - self.PAD * 2
            shown = min(total, max(self.MIN_LINES, int(room // (line_h + self.GAP))))
        last_first = total - shown
        if self.scroll_top is None:
            first = last_first
        else:
            first = max(0, min(self.scroll_top, last_first))
        return first, shown, total

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

    def size(self, max_height=None):
        """(width, height) of what render() would return, tail included."""
        layout = self._lines()
        if self.alpha <= 0 or layout is None:
            return None
        _first, shown, _total = self._window(layout, max_height)
        bh = shown * (layout[2] + self.GAP) + self.PAD * 2
        return layout[1], bh + self.TAIL + 1

    def render(self, tail_dx=0, max_height=None):
        """The bubble on a surface of its own, tail included, or None when
        there is nothing to show. The tail's tip is at the bottom, tail_dx
        from the centre — for a bubble pushed sideways to stay on screen that
        still has to point at who is talking. max_height caps the surface,
        tail included; lines past it scroll."""
        layout = self._lines()
        if self.alpha <= 0 or layout is None:
            return None
        lines, bw, line_h = layout
        first, shown, total = self._window(layout, max_height)
        self._window_seen = (first, shown, total, line_h)
        pad = self.PAD
        bh = shown * (line_h + self.GAP) + pad * 2

        surf = pygame.Surface((bw, bh + self.TAIL + 1), pygame.SRCALPHA)
        bg = (*self.config.bubble_bg_color, int(self.alpha * 0.85))
        pygame.draw.rect(surf, bg, (0, 0, bw, bh), border_radius=12)

        # Border glow
        border_color = (*self.config.neon_primary, int(self.alpha * 0.6))
        pygame.draw.rect(surf, border_color, (0, 0, bw, bh), width=2, border_radius=12)

        # Draw the lines on screen, rendering only those not already held
        visible = lines[first:first + shown]
        cache = {}
        y_offset = pad
        for line in visible:
            if line:
                ls = self._line_surfs.get(line)
                if ls is None:
                    ls = self.font.render(line, True, self.config.bubble_text_color)
                cache[line] = ls
                surf.blit(ls, (pad, y_offset))
            y_offset += line_h + self.GAP
        self._line_surfs = cache

        # Scrollbar, only when there is more than fits
        if shown < total:
            track_top, track_h = 10, bh - 20
            thumb_h = max(16, round(track_h * shown / total))
            thumb_y = track_top + round((track_h - thumb_h) * first / (total - shown))
            bx = bw - pad // 2 - self.BAR_W // 2 - 1
            track = (*self.config.neon_primary, int(self.alpha * 0.15))
            thumb = (*self.config.neon_primary, int(self.alpha * 0.7))
            pygame.draw.rect(surf, track, (bx, track_top, self.BAR_W, track_h),
                             border_radius=2)
            pygame.draw.rect(surf, thumb, (bx, thumb_y, self.BAR_W, thumb_h),
                             border_radius=2)

        # Speech tail, kept clear of the rounded corners
        tx = int(max(20, min(bw - 20, bw // 2 + tail_dx)))
        pygame.draw.polygon(surf, bg, [(tx - 8, bh), (tx + 8, bh), (tx, bh + self.TAIL)])
        return surf

    # Gap kept between the top of the box and the top of the window.
    TOP_MARGIN = 8

    def draw(self, surface, cx, top_y):
        # The box's bottom edge sits 20 px above top_y, its tail hanging 12 px
        # below that — where the kiosk has always drawn it. Everything above
        # that, down to TOP_MARGIN, is the bubble's to use.
        room = top_y - 20 - self.TOP_MARGIN + self.TAIL + 1
        surf = self.render(max_height=room)
        if surf is None:
            self.rect = None
            return
        bh = surf.get_height() - self.TAIL - 1
        x, y = cx - surf.get_width() // 2, top_y - bh - 20
        surface.blit(surf, (x, y))
        self.rect = pygame.Rect(x, y, surf.get_width(), bh)

    # ── Scrolling back through a long reply (kiosk) ──────────────────────

    def _first_now(self):
        """The first line shown, counting scrolls since the last render."""
        _f, shown, total, _h = self._window_seen
        last_first = total - shown
        return last_first if self.scroll_top is None else min(self.scroll_top, last_first)

    def _set_first(self, first):
        if not self._window_seen:
            return
        _f, shown, total, _h = self._window_seen
        last_first = total - shown
        first = max(0, min(int(round(first)), last_first))
        # At the bottom it follows the typing again.
        self.scroll_top = None if first >= last_first else first

    def scroll_by(self, lines):
        if self._window_seen:
            self._set_first(self._first_now() + lines)

    def handle_event(self, event) -> bool:
        """Wheel, drag and scrollbar clicks on an overflowing bubble. Returns
        True when the event was the bubble's. Dragging the text moves it with
        the pointer (or finger); dragging on the scrollbar moves the thumb."""
        seen = self._window_seen
        overflowing = (self.visible and self.rect is not None
                       and seen is not None and seen[1] < seen[2])

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self._drag:
            self._drag = None
            return True
        if event.type == pygame.MOUSEMOTION and self._drag:
            if not overflowing:
                self._drag = None
                return False
            mode, y0, first0 = self._drag
            _f, shown, total, line_h = seen
            dy = event.pos[1] - y0
            if mode == "bar":
                track_h = self.rect.height - 20
                self._set_first(first0 + dy * total / max(1, track_h))
            else:
                self._set_first(first0 - dy / (line_h + self.GAP))
            return True
        if not overflowing:
            return False
        if event.type == pygame.MOUSEWHEEL:
            if self.rect.collidepoint(pygame.mouse.get_pos()):
                self.scroll_by(-event.y * 2)
                return True
            return False
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self.rect.collidepoint(event.pos)):
            _f, shown, total, _h = seen
            if event.pos[0] >= self.rect.right - self.PAD:
                # A click on the track puts the thumb's middle there.
                track_h = self.rect.height - 20
                frac = (event.pos[1] - self.rect.top - 10) / max(1, track_h)
                self._set_first(frac * total - shown / 2)
                self._drag = ("bar", event.pos[1], self._first_now())
            else:
                self._drag = ("text", event.pos[1], self._first_now())
            return True
        return False
