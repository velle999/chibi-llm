"""
Small drawn icons for the HUD: weather, humidity, wind, microphone, speaker.

These used to be emoji in the text (🌧 💧 🌬 🎙 🔊 …), and the monospace font
the HUD draws with has none of them — DejaVu Sans Mono stops short of the emoji
block, so each one came out as an empty box on every machine chibi runs on. A
colour-emoji font is not something to count on on a Pi either, and would not
suit the neon look if it were there. So they are drawn, the way the avatar is:
at four times the size and smoothed down, which is the only antialiasing
pygame.draw has.

Shared between the three copies; sizes come from the caller, which is where
the platform differences live.
"""

import math

import pygame

_SS = 4                     # supersampling factor
_cache = {}

SUN = (255, 210, 80)
CLOUD = (205, 218, 238)
CLOUD_DARK = (150, 162, 185)
RAIN = (100, 160, 255)
SNOW = (225, 235, 255)
BOLT = (255, 220, 60)
FOG = (170, 180, 195)

# Every condition data_feeds produces, plus OpenWeatherMap's "main" values.
_WEATHER = {
    "clear": "sun", "sunny": "sun",
    "clouds": "cloud", "overcast": "overcast",
    "rain": "rain", "shower": "rain",
    "drizzle": "drizzle",
    "snow": "snow",
    "sleet": "sleet",
    "storm": "storm", "thunderstorm": "storm", "squall": "storm", "tornado": "storm",
    "mist": "fog", "fog": "fog", "haze": "fog", "smoke": "fog",
    "dust": "fog", "sand": "fog", "ash": "fog",
}


def _canvas(size):
    s = size * _SS
    return pygame.Surface((s, s), pygame.SRCALPHA), s


def _finish(big, size):
    return pygame.transform.smoothscale(big, (size, size))


def _line(surf, color, a, b, width):
    pygame.draw.line(surf, color, a, b, width)
    r = max(1, width // 2)                   # round the ends
    pygame.draw.circle(surf, color, a, r)
    pygame.draw.circle(surf, color, b, r)


# ── the pieces ──────────────────────────────────────────────────────────────

def _sun(surf, cx, cy, r, color=SUN):
    pygame.draw.circle(surf, color, (cx, cy), int(r * 0.55))
    w = max(2, int(r * 0.14))
    for i in range(8):
        a = i * math.pi / 4
        _line(surf, color,
              (int(cx + math.cos(a) * r * 0.75), int(cy + math.sin(a) * r * 0.75)),
              (int(cx + math.cos(a) * r), int(cy + math.sin(a) * r)), w)


def _cloud(surf, x, y, w, color=CLOUD):
    """A cloud w wide whose flat base is at y + 0.55w, left edge at x."""
    h = int(w * 0.55)
    base = y + h
    pygame.draw.rect(surf, color, (x, base - int(h * 0.45), w, int(h * 0.45)),
                     border_radius=int(h * 0.22))
    pygame.draw.circle(surf, color, (x + int(w * 0.30), base - int(h * 0.42)), int(h * 0.40))
    pygame.draw.circle(surf, color, (x + int(w * 0.58), base - int(h * 0.58)), int(h * 0.55))
    pygame.draw.circle(surf, color, (x + int(w * 0.80), base - int(h * 0.36)), int(h * 0.34))
    return base


def _drops(surf, xs, top, length, width, color=RAIN):
    for x in xs:
        _line(surf, color, (x, top), (x - length // 3, top + length), width)


def _flake(surf, cx, cy, r, width, color=SNOW):
    for i in range(3):
        a = i * math.pi / 3
        dx, dy = math.cos(a) * r, math.sin(a) * r
        _line(surf, color, (int(cx - dx), int(cy - dy)), (int(cx + dx), int(cy + dy)), width)


def _weather(kind, size):
    big, s = _canvas(size)
    lw = max(3, s // 18)                    # stroke width at the big size
    if kind == "sun":
        _sun(big, s // 2, s // 2, int(s * 0.44))
    elif kind in ("cloud", "overcast"):
        if kind == "overcast":
            _cloud(big, int(s * 0.22), int(s * 0.12), int(s * 0.74), CLOUD_DARK)
        _cloud(big, int(s * 0.04), int(s * 0.28), int(s * 0.80))
    elif kind in ("rain", "drizzle", "sleet", "snow", "storm"):
        if kind == "drizzle":
            # The sun behind the cloud's shoulder, and a smaller cloud so it
            # still shows at 30 px.
            _sun(big, int(s * 0.66), int(s * 0.28), int(s * 0.30))
            base = _cloud(big, int(s * 0.04), int(s * 0.20), int(s * 0.70))
        else:
            base = _cloud(big, int(s * 0.06), int(s * 0.08), int(s * 0.86),
                          CLOUD_DARK if kind == "storm" else CLOUD)
        top = base + s // 14
        fall = int(s * 0.26)
        if kind == "rain":
            _drops(big, [int(s * f) for f in (0.30, 0.52, 0.74)], top, fall, lw)
        elif kind == "drizzle":
            _drops(big, [int(s * f) for f in (0.28, 0.50)], top, fall * 2 // 3, lw)
        elif kind == "sleet":
            _drops(big, [int(s * 0.30), int(s * 0.72)], top, fall, lw)
            _flake(big, int(s * 0.50), top + fall // 2, int(s * 0.09), max(2, lw * 2 // 3))
        elif kind == "snow":
            for f in (0.28, 0.52, 0.76):
                _flake(big, int(s * f), top + fall // 2, int(s * 0.09), max(2, lw * 2 // 3))
        elif kind == "storm":
            cx = int(s * 0.52)
            pygame.draw.polygon(big, BOLT, [
                (cx + int(s * 0.06), top - s // 30), (cx - int(s * 0.12), top + int(s * 0.18)),
                (cx, top + int(s * 0.18)), (cx - int(s * 0.08), top + int(s * 0.36)),
                (cx + int(s * 0.14), top + int(s * 0.11)), (cx + int(s * 0.02), top + int(s * 0.11)),
            ])
    elif kind == "fog":
        for i, (x0, x1) in enumerate(((0.10, 0.80), (0.22, 0.92), (0.06, 0.70), (0.26, 0.88))):
            y = int(s * (0.26 + i * 0.16))
            _line(big, FOG, (int(s * x0), y), (int(s * x1), y), max(3, s // 12))
    return _finish(big, size)


def _glyph(name, size, color):
    big, s = _canvas(size)
    lw = max(3, s // 12)
    if name == "drop":
        cx, r = s // 2, int(s * 0.28)
        cy = int(s * 0.62)
        pygame.draw.circle(big, color, (cx, cy), r)
        pygame.draw.polygon(big, color, [(cx, int(s * 0.08)),
                                         (cx - int(r * 0.95), cy - int(r * 0.35)),
                                         (cx + int(r * 0.95), cy - int(r * 0.35))])
    elif name == "wind":
        # Three gusts, each ending in a curl.
        for y, x1, curl in ((0.30, 0.66, True), (0.52, 0.86, True), (0.74, 0.56, False)):
            yy, xx = int(s * y), int(s * x1)
            _line(big, color, (int(s * 0.08), yy), (xx, yy), lw)
            if curl:
                r = int(s * 0.10)
                pygame.draw.arc(big, color, (xx - r, yy - 2 * r, 2 * r, 2 * r),
                                -math.pi / 2, math.pi, lw)
    elif name == "mic":
        cx = s // 2
        pygame.draw.rect(big, color, (cx - int(s * 0.14), int(s * 0.06), int(s * 0.28), int(s * 0.50)),
                         border_radius=int(s * 0.14))
        r = int(s * 0.24)
        pygame.draw.arc(big, color, (cx - r, int(s * 0.56) - r - int(s * 0.06), 2 * r, 2 * r),
                        math.pi, 2 * math.pi, lw)
        _line(big, color, (cx, int(s * 0.74)), (cx, int(s * 0.88)), lw)
        _line(big, color, (cx - int(s * 0.16), int(s * 0.90)), (cx + int(s * 0.16), int(s * 0.90)), lw)
    elif name == "speaker":
        cy = s // 2
        pygame.draw.polygon(big, color, [
            (int(s * 0.08), cy - int(s * 0.14)), (int(s * 0.24), cy - int(s * 0.14)),
            (int(s * 0.46), cy - int(s * 0.32)), (int(s * 0.46), cy + int(s * 0.32)),
            (int(s * 0.24), cy + int(s * 0.14)), (int(s * 0.08), cy + int(s * 0.14)),
        ])
        for r in (0.20, 0.34):
            rr = int(s * r)
            pygame.draw.arc(big, color, (int(s * 0.46) - rr, cy - rr, 2 * rr, 2 * rr),
                            -math.pi / 3.2, math.pi / 3.2, lw)
    return _finish(big, size)


# ── the API ─────────────────────────────────────────────────────────────────

def weather(condition, size):
    """The icon for a weather condition, or None for one there is no picture
    of (the caller shows a "?" then)."""
    kind = _WEATHER.get((condition or "").lower())
    if kind is None or size <= 0:
        return None
    key = ("weather", kind, size)
    if key not in _cache:
        _cache[key] = _weather(kind, size)
    return _cache[key]


def glyph(name, size, color):
    """"drop", "wind", "mic" or "speaker", in one colour."""
    key = (name, size, tuple(color))
    if key not in _cache:
        _cache[key] = _glyph(name, max(1, size), tuple(color))
    return _cache[key]


def label(font, name, text, color, gap=None):
    """An icon followed by text, as one surface the height of the font — for
    the places that used to put an emoji at the front of a string."""
    text_surf = font.render(text, True, color) if text else None
    h = font.get_height()
    size = int(h * 0.82)
    gap = max(2, h // 6) if gap is None else gap
    icon = glyph(name, size, color)
    w = size + ((gap + text_surf.get_width()) if text_surf else 0)
    out = pygame.Surface((w, h), pygame.SRCALPHA)
    out.blit(icon, (0, (h - size) // 2))
    if text_surf:
        out.blit(text_surf, (size + gap, 0))
    return out
