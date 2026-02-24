"""
Data Feeds — Weather + Market data for the chibi avatar.
Fetches periodically in background threads and provides:
  1. Context injection for LLM (so the avatar "knows" what's happening)
  2. Structured data for visual overlays on the Pygame display

APIs used (all free, no key required for some):
  - OpenWeatherMap (free tier, needs API key)
  - wttr.in (no key needed, fallback)
  - Yahoo Finance via yfinance (no key)
  - CoinGecko (no key, crypto)
  - Fear & Greed index (no key)

Install:
    pip install yfinance requests --break-system-packages
"""

import json
import time
import threading
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ─── Data Containers ─────────────────────────────────────────────────────────

@dataclass
class WeatherData:
    temperature: float = 0.0        # °F or °C based on config
    feels_like: float = 0.0
    condition: str = "unknown"       # "clear", "clouds", "rain", "snow", "storm", etc.
    description: str = ""
    humidity: int = 0
    wind_speed: float = 0.0
    icon: str = ""                   # weather icon code
    city: str = ""
    sunrise: str = ""
    sunset: str = ""
    updated_at: str = ""

    @property
    def mood(self) -> str:
        """Map weather to avatar mood hint."""
        c = self.condition.lower()
        if c in ("clear", "sunny"):
            return "happy"
        elif c in ("clouds", "overcast", "mist", "fog"):
            return "neutral"
        elif c in ("rain", "drizzle", "shower"):
            return "cozy"
        elif c in ("snow", "sleet"):
            return "excited"
        elif c in ("storm", "thunderstorm", "tornado"):
            return "alert"
        return "neutral"

    def summary(self) -> str:
        if not self.city:
            return "Weather data unavailable."
        return (
            f"Weather in {self.city}: {self.description}, "
            f"{self.temperature:.0f}°F (feels like {self.feels_like:.0f}°F), "
            f"humidity {self.humidity}%, wind {self.wind_speed:.1f} mph. "
            f"Sunrise {self.sunrise}, sunset {self.sunset}."
        )


@dataclass
class MarketTicker:
    symbol: str = ""
    name: str = ""
    price: float = 0.0
    change: float = 0.0             # absolute change
    change_pct: float = 0.0         # percentage change
    direction: str = "flat"          # "up", "down", "flat"
    updated_at: str = ""


@dataclass
class MarketData:
    tickers: list = field(default_factory=list)
    crypto: list = field(default_factory=list)
    fear_greed: int = -1             # 0-100, -1 = unavailable
    fear_greed_label: str = ""       # "Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"
    market_status: str = "unknown"   # "open", "closed", "pre-market", "after-hours"
    updated_at: str = ""

    def summary(self) -> str:
        parts = []

        if self.tickers:
            ticker_strs = []
            for t in self.tickers[:5]:
                arrow = "↑" if t.direction == "up" else "↓" if t.direction == "down" else "→"
                ticker_strs.append(
                    f"{t.symbol}: ${t.price:,.2f} ({arrow}{t.change_pct:+.2f}%)"
                )
            parts.append("Markets: " + ", ".join(ticker_strs))

        if self.crypto:
            crypto_strs = []
            for c in self.crypto[:3]:
                arrow = "↑" if c.direction == "up" else "↓" if c.direction == "down" else "→"
                crypto_strs.append(
                    f"{c.symbol}: ${c.price:,.2f} ({arrow}{c.change_pct:+.2f}%)"
                )
            parts.append("Crypto: " + ", ".join(crypto_strs))

        if self.fear_greed >= 0:
            parts.append(f"Fear & Greed Index: {self.fear_greed}/100 ({self.fear_greed_label})")

        if self.market_status != "unknown":
            parts.append(f"Market is {self.market_status}.")

        return " ".join(parts) if parts else "Market data unavailable."


# ─── Fetchers ────────────────────────────────────────────────────────────────

def fetch_weather_owm(api_key: str, city: str, units: str = "imperial") -> WeatherData:
    """Fetch weather from OpenWeatherMap (requires free API key)."""
    data = WeatherData()
    try:
        url = (
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?q={urllib.request.quote(city)}&appid={api_key}&units={units}"
        )
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            j = json.loads(resp.read().decode())

        data.city = j.get("name", city)
        data.temperature = j["main"]["temp"]
        data.feels_like = j["main"]["feels_like"]
        data.humidity = j["main"]["humidity"]
        data.wind_speed = j["wind"]["speed"]

        weather = j["weather"][0] if j.get("weather") else {}
        data.condition = weather.get("main", "unknown")
        data.description = weather.get("description", "")
        data.icon = weather.get("icon", "")

        # Sunrise/sunset
        if "sys" in j:
            tz_offset = j.get("timezone", 0)
            if j["sys"].get("sunrise"):
                sr = datetime.fromtimestamp(j["sys"]["sunrise"] + tz_offset, tz=timezone.utc)
                data.sunrise = sr.strftime("%I:%M %p")
            if j["sys"].get("sunset"):
                ss = datetime.fromtimestamp(j["sys"]["sunset"] + tz_offset, tz=timezone.utc)
                data.sunset = ss.strftime("%I:%M %p")

        data.updated_at = datetime.now().strftime("%H:%M")

    except Exception as e:
        print(f"[Weather] OWM error: {e}")

    return data


def fetch_weather_wttr(city: str) -> WeatherData:
    """Fetch weather from wttr.in (no API key needed)."""
    data = WeatherData()
    try:
        url = f"https://wttr.in/{urllib.request.quote(city)}?format=j1"
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "chibi-avatar/1.0")
        with urllib.request.urlopen(req, timeout=10) as resp:
            j = json.loads(resp.read().decode())

        current = j.get("current_condition", [{}])[0]
        data.city = city
        data.temperature = float(current.get("temp_F", 0))
        data.feels_like = float(current.get("FeelsLikeF", 0))
        data.humidity = int(current.get("humidity", 0))
        data.wind_speed = float(current.get("windspeedMiles", 0))
        data.description = current.get("weatherDesc", [{}])[0].get("value", "")
        data.condition = _map_wttr_condition(current.get("weatherCode", ""))
        data.updated_at = datetime.now().strftime("%H:%M")

        # Sunrise/sunset from astronomy
        astro = j.get("weather", [{}])[0].get("astronomy", [{}])[0]
        data.sunrise = astro.get("sunrise", "")
        data.sunset = astro.get("sunset", "")

    except Exception as e:
        print(f"[Weather] wttr.in error: {e}")

    return data


def _map_wttr_condition(code: str) -> str:
    """Map wttr.in weather codes to simple conditions."""
    code = str(code)
    mapping = {
        "113": "clear", "116": "clouds", "119": "clouds", "122": "overcast",
        "143": "mist", "176": "rain", "179": "snow", "182": "sleet",
        "185": "drizzle", "200": "storm", "227": "snow", "230": "snow",
        "248": "fog", "260": "fog", "263": "drizzle", "266": "drizzle",
        "281": "rain", "284": "rain", "293": "rain", "296": "rain",
        "299": "rain", "302": "rain", "305": "rain", "308": "rain",
        "311": "rain", "314": "rain", "317": "sleet", "320": "snow",
        "323": "snow", "326": "snow", "329": "snow", "332": "snow",
        "335": "snow", "338": "snow", "350": "sleet", "353": "rain",
        "356": "rain", "359": "rain", "362": "sleet", "365": "sleet",
        "368": "snow", "371": "snow", "374": "sleet", "377": "sleet",
        "386": "storm", "389": "storm", "392": "storm", "395": "snow",
    }
    return mapping.get(code, "unknown")


def fetch_market_yfinance(symbols: list[str]) -> list[MarketTicker]:
    """Fetch stock data using yfinance."""
    tickers = []
    try:
        import yfinance as yf
        data = yf.download(
            " ".join(symbols),
            period="2d",
            group_by="ticker",
            progress=False,
            threads=True,
        )

        for sym in symbols:
            try:
                if len(symbols) == 1:
                    df = data
                else:
                    df = data[sym]

                if df.empty or len(df) < 2:
                    continue

                current = float(df["Close"].iloc[-1])
                previous = float(df["Close"].iloc[-2])
                change = current - previous
                change_pct = (change / previous) * 100 if previous else 0

                t = MarketTicker(
                    symbol=sym,
                    price=current,
                    change=change,
                    change_pct=change_pct,
                    direction="up" if change > 0.01 else "down" if change < -0.01 else "flat",
                    updated_at=datetime.now().strftime("%H:%M"),
                )
                tickers.append(t)
            except Exception:
                continue

    except ImportError:
        print("[Market] yfinance not installed. Run: pip install yfinance --break-system-packages")
    except Exception as e:
        print(f"[Market] yfinance error: {e}")

    return tickers


def fetch_crypto_coingecko(coin_ids: list[str]) -> list[MarketTicker]:
    """Fetch crypto prices from CoinGecko (no API key)."""
    tickers = []
    try:
        ids_str = ",".join(coin_ids)
        url = (
            f"https://api.coingecko.com/api/v3/simple/price"
            f"?ids={ids_str}&vs_currencies=usd"
            f"&include_24hr_change=true"
        )
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "chibi-avatar/1.0")
        with urllib.request.urlopen(req, timeout=10) as resp:
            j = json.loads(resp.read().decode())

        symbol_map = {
            "bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL",
            "dogecoin": "DOGE", "cardano": "ADA", "ripple": "XRP",
        }

        for coin_id in coin_ids:
            if coin_id in j:
                price = j[coin_id].get("usd", 0)
                change_pct = j[coin_id].get("usd_24h_change", 0) or 0

                t = MarketTicker(
                    symbol=symbol_map.get(coin_id, coin_id.upper()),
                    name=coin_id,
                    price=price,
                    change_pct=change_pct,
                    direction="up" if change_pct > 0.1 else "down" if change_pct < -0.1 else "flat",
                    updated_at=datetime.now().strftime("%H:%M"),
                )
                tickers.append(t)

    except Exception as e:
        print(f"[Market] CoinGecko error: {e}")

    return tickers


def fetch_fear_greed() -> tuple[int, str]:
    """Fetch CNN Fear & Greed index alternative (from alternative.me crypto)."""
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "chibi-avatar/1.0")
        with urllib.request.urlopen(req, timeout=10) as resp:
            j = json.loads(resp.read().decode())

        data = j.get("data", [{}])[0]
        value = int(data.get("value", -1))
        label = data.get("value_classification", "Unknown")
        return value, label

    except Exception as e:
        print(f"[Market] Fear & Greed error: {e}")
        return -1, ""


def get_market_status() -> str:
    """Estimate US market status based on current time."""
    now = datetime.now()
    # Simple EST approximation (not accounting for DST perfectly)
    # You can improve this with pytz if needed
    hour = now.hour
    weekday = now.weekday()  # 0=Mon, 6=Sun

    if weekday >= 5:
        return "closed"
    elif 4 <= hour < 9:
        return "pre-market"
    elif 9 <= hour < 16:
        return "open"
    elif 16 <= hour < 20:
        return "after-hours"
    else:
        return "closed"


# ─── Feed Manager ────────────────────────────────────────────────────────────

class DataFeedManager:
    """
    Background manager that periodically fetches weather + market data
    and provides it for LLM context injection and visual overlays.
    """

    def __init__(self, config):
        self.config = config
        self.weather = WeatherData()
        self.market = MarketData()
        self._running = True
        self._lock = threading.Lock()

        # Start background threads
        if self.config.weather_enabled:
            t = threading.Thread(target=self._weather_loop, daemon=True)
            t.start()

        if self.config.market_enabled:
            t = threading.Thread(target=self._market_loop, daemon=True)
            t.start()

    def _weather_loop(self):
        """Fetch weather periodically."""
        while self._running:
            try:
                if self.config.weather_api_key:
                    data = fetch_weather_owm(
                        self.config.weather_api_key,
                        self.config.weather_city,
                    )
                else:
                    data = fetch_weather_wttr(self.config.weather_city)

                with self._lock:
                    self.weather = data
                print(f"[Weather] Updated: {data.description}, {data.temperature:.0f}°F")

            except Exception as e:
                print(f"[Weather] Feed error: {e}")

            time.sleep(self.config.weather_interval)

    def _market_loop(self):
        """Fetch market data periodically."""
        while self._running:
            try:
                # Stocks
                tickers = []
                if self.config.market_symbols:
                    tickers = fetch_market_yfinance(self.config.market_symbols)

                # Crypto
                crypto = []
                if self.config.crypto_coins:
                    crypto = fetch_crypto_coingecko(self.config.crypto_coins)

                # Fear & Greed
                fg_val, fg_label = fetch_fear_greed()

                with self._lock:
                    self.market = MarketData(
                        tickers=tickers,
                        crypto=crypto,
                        fear_greed=fg_val,
                        fear_greed_label=fg_label,
                        market_status=get_market_status(),
                        updated_at=datetime.now().strftime("%H:%M"),
                    )
                print(f"[Market] Updated: {len(tickers)} stocks, {len(crypto)} crypto")

            except Exception as e:
                print(f"[Market] Feed error: {e}")

            time.sleep(self.config.market_interval)

    def get_context(self) -> str:
        """
        Returns a context string to inject into the LLM system prompt.
        This gives the avatar awareness of current conditions.
        """
        with self._lock:
            parts = []

            if self.config.weather_enabled and self.weather.city:
                parts.append(f"[CURRENT WEATHER] {self.weather.summary()}")

            if self.config.market_enabled and (self.market.tickers or self.market.crypto):
                parts.append(f"[MARKET DATA] {self.market.summary()}")

            now = datetime.now()
            parts.append(
                f"[CURRENT TIME] {now.strftime('%A, %B %d, %Y at %I:%M %p')}"
            )

            return "\n".join(parts)

    def get_weather(self) -> WeatherData:
        with self._lock:
            return self.weather

    def get_market(self) -> MarketData:
        with self._lock:
            return self.market

    def stop(self):
        self._running = False
