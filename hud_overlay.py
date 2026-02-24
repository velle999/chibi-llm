"""
HUD Overlay — Renders weather + market data on the Pygame display.
Cyberpunk-styled with neon accents, scrolling ticker, and weather icons.
"""

import pygame
import math
import time
from data_feeds import WeatherData, MarketData, MarketTicker
from config import Config


class WeatherOverlay:
    """Draws current weather in the top-right corner."""

    def __init__(self, config: Config):
        self.config = config
        self.font_large = None
        self.font_small = None
        self._weather_icons = {}

    def _init_fonts(self):
        if not self.font_large:
            self.font_large = pygame.font.SysFont("monospace", 28, bold=True)
            self.font_small = pygame.font.SysFont("monospace", 12)

    def _get_weather_symbol(self, condition: str) -> str:
        """Map weather condition to unicode/ASCII art symbol."""
        symbols = {
            "clear": "☀",
            "sunny": "☀",
            "clouds": "☁",
            "overcast": "☁",
            "rain": "🌧",
            "drizzle": "🌦",
            "shower": "🌧",
            "snow": "❄",
            "sleet": "🌨",
            "storm": "⚡",
            "thunderstorm": "⚡",
            "mist": "🌫",
            "fog": "🌫",
        }
        return symbols.get(condition.lower(), "?")

    def draw(self, surface, weather: WeatherData, t: float):
        if not weather.city:
            return

        self._init_fonts()

        w = surface.get_width()
        pad = 10
        box_w = 160
        box_h = 90
        bx = w - box_w - pad
        by = 28

        # Background panel
        panel = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (8, 8, 25, 180), (0, 0, box_w, box_h), border_radius=8)

        # Border — color shifts with weather mood
        mood = weather.mood
        if mood == "happy":
            border_color = (*self.config.neon_warning, 120)
        elif mood == "cozy":
            border_color = (80, 140, 255, 120)
        elif mood == "alert":
            flash = int(128 + 127 * math.sin(t * 4))
            border_color = (255, flash, 0, 150)
        else:
            border_color = (*self.config.neon_primary, 80)

        pygame.draw.rect(panel, border_color, (0, 0, box_w, box_h), width=1, border_radius=8)

        # Temperature (big)
        temp_text = f"{weather.temperature:.0f}°"
        temp_surf = self.font_large.render(temp_text, True, (230, 240, 255))
        panel.blit(temp_surf, (12, 8))

        # Weather symbol
        symbol = self._get_weather_symbol(weather.condition)
        sym_surf = self.font_large.render(symbol, True, (255, 255, 255))
        panel.blit(sym_surf, (box_w - sym_surf.get_width() - 12, 6))

        # Description
        desc = weather.description[:22]
        desc_surf = self.font_small.render(desc, True, (160, 180, 200))
        panel.blit(desc_surf, (12, 42))

        # Humidity + wind
        detail = f"💧{weather.humidity}%  🌬{weather.wind_speed:.0f}mph"
        detail_surf = self.font_small.render(detail, True, (120, 140, 160))
        panel.blit(detail_surf, (12, 58))

        # Updated time
        if weather.updated_at:
            upd = self.font_small.render(f"@{weather.updated_at}", True, (60, 70, 80))
            panel.blit(upd, (box_w - upd.get_width() - 8, box_h - 16))

        surface.blit(panel, (bx, by))


class MarketTicker_Overlay:
    """Scrolling market ticker at the bottom of the screen."""

    def __init__(self, config: Config):
        self.config = config
        self.font = None
        self.scroll_x = 0
        self.ticker_width = 0
        self._cached_surface = None
        self._cached_data_hash = ""

    def _init_font(self):
        if not self.font:
            self.font = pygame.font.SysFont("monospace", 14, bold=True)

    def _build_ticker_surface(self, market: MarketData) -> pygame.Surface:
        """Build the full scrolling ticker as one wide surface."""
        self._init_font()

        items = []

        # Stocks
        for t in market.tickers:
            arrow = "▲" if t.direction == "up" else "▼" if t.direction == "down" else "●"
            color = ((0, 255, 120) if t.direction == "up"
                     else (255, 60, 80) if t.direction == "down"
                     else (150, 150, 150))
            text = f"  {t.symbol} ${t.price:,.2f} {arrow}{t.change_pct:+.1f}%  "
            items.append((text, color))

        # Crypto
        for c in market.crypto:
            arrow = "▲" if c.direction == "up" else "▼" if c.direction == "down" else "●"
            color = ((0, 255, 200) if c.direction == "up"
                     else (255, 80, 120) if c.direction == "down"
                     else (150, 150, 150))
            text = f"  {c.symbol} ${c.price:,.2f} {arrow}{c.change_pct:+.1f}%  "
            items.append((text, color))

        # Fear & Greed
        if market.fear_greed >= 0:
            fg = market.fear_greed
            if fg < 25:
                fg_color = (255, 50, 50)
            elif fg < 45:
                fg_color = (255, 160, 50)
            elif fg < 55:
                fg_color = (200, 200, 100)
            elif fg < 75:
                fg_color = (100, 255, 100)
            else:
                fg_color = (50, 255, 50)
            items.append((f"  F&G: {fg} ({market.fear_greed_label})  ", fg_color))

        # Market status
        if market.market_status != "unknown":
            status_color = (0, 255, 100) if market.market_status == "open" else (100, 100, 120)
            items.append((f"  MKT: {market.market_status.upper()}  ", status_color))

        if not items:
            return None

        # Separator
        sep = "  │  "

        # Calculate total width
        total_width = 0
        segments = []
        for text, color in items:
            surf = self.font.render(text, True, color)
            segments.append(surf)
            total_width += surf.get_width()
            sep_surf = self.font.render(sep, True, (40, 50, 60))
            segments.append(sep_surf)
            total_width += sep_surf.get_width()

        # Double it for seamless scrolling
        ticker_surf = pygame.Surface((total_width * 2, 22), pygame.SRCALPHA)
        x = 0
        for _ in range(2):
            for seg in segments:
                ticker_surf.blit(seg, (x, 2))
                x += seg.get_width()

        self.ticker_width = total_width
        return ticker_surf

    def draw(self, surface, market: MarketData, t: float, dt: float):
        if not market.tickers and not market.crypto:
            return

        w = surface.get_width()

        # Rebuild surface if data changed
        data_hash = f"{len(market.tickers)}_{len(market.crypto)}_{market.fear_greed}"
        if data_hash != self._cached_data_hash or self._cached_surface is None:
            self._cached_surface = self._build_ticker_surface(market)
            self._cached_data_hash = data_hash

        if self._cached_surface is None:
            return

        # Scroll
        scroll_speed = self.config.ticker_scroll_speed
        self.scroll_x -= scroll_speed * dt
        if self.ticker_width > 0 and abs(self.scroll_x) >= self.ticker_width:
            self.scroll_x = 0

        # Draw bar background
        bar_h = 26
        bar_y = surface.get_height() - 64  # above the input box
        bar_surf = pygame.Surface((w, bar_h), pygame.SRCALPHA)
        pygame.draw.rect(bar_surf, (5, 5, 18, 200), (0, 0, w, bar_h))
        # Top border line
        pygame.draw.line(bar_surf, (*self.config.neon_primary, 40),
                         (0, 0), (w, 0), 1)

        surface.blit(bar_surf, (0, bar_y))

        # Blit scrolling ticker with clip
        clip_rect = pygame.Rect(0, bar_y + 2, w, bar_h - 4)
        surface.set_clip(clip_rect)
        surface.blit(self._cached_surface, (int(self.scroll_x), bar_y + 2))
        surface.set_clip(None)


class MarketMiniPanel:
    """Small panel showing key metrics — top-left below status bar."""

    def __init__(self, config: Config):
        self.config = config
        self.font = None

    def _init_font(self):
        if not self.font:
            self.font = pygame.font.SysFont("monospace", 11)

    def draw(self, surface, market: MarketData, t: float):
        if not market.tickers and not market.crypto and market.fear_greed < 0:
            return

        self._init_font()

        pad = 10
        bx = pad
        by = 26
        line_h = 14
        lines = []

        # Top 3 tickers
        for tk in (market.tickers + market.crypto)[:4]:
            arrow = "▲" if tk.direction == "up" else "▼" if tk.direction == "down" else "─"
            color = ((0, 230, 120) if tk.direction == "up"
                     else (255, 70, 90) if tk.direction == "down"
                     else (130, 130, 140))
            lines.append((f"{tk.symbol:>5} {tk.price:>10,.2f} {arrow}{tk.change_pct:+.1f}%", color))

        # Fear & Greed compact
        if market.fear_greed >= 0:
            fg = market.fear_greed
            fg_color = ((255, 50, 50) if fg < 30
                        else (255, 180, 50) if fg < 50
                        else (100, 255, 100) if fg < 70
                        else (50, 255, 50))
            lines.append((f"  F&G {fg:>3} {market.fear_greed_label}", fg_color))

        if not lines:
            return

        box_h = len(lines) * line_h + 10
        box_w = 220

        panel = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
        pygame.draw.rect(panel, (8, 8, 25, 150), (0, 0, box_w, box_h), border_radius=6)
        pygame.draw.rect(panel, (*self.config.neon_primary, 50),
                         (0, 0, box_w, box_h), width=1, border_radius=6)

        y = 5
        for text, color in lines:
            ts = self.font.render(text, True, color)
            panel.blit(ts, (6, y))
            y += line_h

        surface.blit(panel, (bx, by))


class HUDOverlay:
    """Combines all HUD elements."""

    def __init__(self, config: Config):
        self.config = config
        self.weather_overlay = WeatherOverlay(config)
        self.ticker_overlay = MarketTicker_Overlay(config)
        self.mini_panel = MarketMiniPanel(config)

    def draw(self, surface, weather: WeatherData, market: MarketData, t: float, dt: float):
        if self.config.weather_enabled:
            self.weather_overlay.draw(surface, weather, t)

        if self.config.market_enabled:
            self.ticker_overlay.draw(surface, market, t, dt)
            # Only show mini panel if there's room (no weather taking the corner)
            if not self.config.weather_enabled:
                self.mini_panel.draw(surface, market, t)
