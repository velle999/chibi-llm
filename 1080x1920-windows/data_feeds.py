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


@dataclass
class NewsHeadline:
    title: str = ""
    source: str = ""
    published: str = ""
    url: str = ""


@dataclass
class NewsData:
    headlines: list = field(default_factory=list)
    updated_at: str = ""

    def summary(self, max_items: int = 8) -> str:
        if not self.headlines:
            return "News data unavailable."
        items = []
        for h in self.headlines[:max_items]:
            src = f" ({h.source})" if h.source else ""
            items.append(f"• {h.title}{src}")
        return "Top headlines:\n" + "\n".join(items)


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
        with urllib.request.urlopen(req, timeout=8) as resp:
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


# City → lat/lon lookup for Open-Meteo (add your city here)
_CITY_COORDS = {
    "st. louis": (38.63, -90.20),
    "st louis": (38.63, -90.20),
    "new york": (40.71, -74.01),
    "los angeles": (34.05, -118.24),
    "chicago": (41.88, -87.63),
    "houston": (29.76, -95.37),
    "phoenix": (33.45, -112.07),
    "san francisco": (37.77, -122.42),
    "seattle": (47.61, -122.33),
    "denver": (39.74, -104.99),
    "miami": (25.76, -80.19),
    "dallas": (32.78, -96.80),
    "london": (51.51, -0.13),
    "tokyo": (35.68, 139.69),
}


def fetch_weather_openmeteo(city: str) -> WeatherData:
    """Fetch weather from Open-Meteo (free, no key, very reliable)."""
    data = WeatherData()
    try:
        coords = _CITY_COORDS.get(city.lower())
        if not coords:
            # Try geocoding
            geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.request.quote(city)}&count=1"
            req = urllib.request.Request(geo_url)
            req.add_header("User-Agent", "chibi-llm/1.0")
            with urllib.request.urlopen(req, timeout=8) as resp:
                geo = json.loads(resp.read().decode())
            results = geo.get("results", [])
            if not results:
                print(f"[Weather] Open-Meteo: city '{city}' not found")
                return data
            coords = (results[0]["latitude"], results[0]["longitude"])
            # Cache it
            _CITY_COORDS[city.lower()] = coords

        lat, lon = coords
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
            f"weather_code,wind_speed_10m"
            f"&temperature_unit=fahrenheit&wind_speed_unit=mph"
            f"&daily=sunrise,sunset&timezone=auto&forecast_days=1"
        )
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "chibi-llm/1.0")
        with urllib.request.urlopen(req, timeout=8) as resp:
            j = json.loads(resp.read().decode())

        current = j.get("current", {})
        data.city = city
        data.temperature = float(current.get("temperature_2m", 0))
        data.feels_like = float(current.get("apparent_temperature", 0))
        data.humidity = int(current.get("relative_humidity_2m", 0))
        data.wind_speed = float(current.get("wind_speed_10m", 0))

        wmo_code = current.get("weather_code", 0)
        data.condition = _map_wmo_condition(wmo_code)
        data.description = _wmo_description(wmo_code)
        data.updated_at = datetime.now().strftime("%H:%M")

        daily = j.get("daily", {})
        if daily.get("sunrise"):
            try:
                sr = datetime.fromisoformat(daily["sunrise"][0])
                data.sunrise = sr.strftime("%I:%M %p")
            except Exception:
                pass
        if daily.get("sunset"):
            try:
                ss = datetime.fromisoformat(daily["sunset"][0])
                data.sunset = ss.strftime("%I:%M %p")
            except Exception:
                pass

    except Exception as e:
        print(f"[Weather] Open-Meteo error: {e}")

    return data


def _map_wmo_condition(code: int) -> str:
    """Map WMO weather codes to simple conditions."""
    if code == 0:
        return "clear"
    elif code in (1, 2, 3):
        return "clouds"
    elif code in (45, 48):
        return "fog"
    elif code in (51, 53, 55, 56, 57):
        return "drizzle"
    elif code in (61, 63, 65, 66, 67, 80, 81, 82):
        return "rain"
    elif code in (71, 73, 75, 77, 85, 86):
        return "snow"
    elif code in (95, 96, 99):
        return "storm"
    return "unknown"


def _wmo_description(code: int) -> str:
    """Human-readable WMO weather description."""
    descriptions = {
        0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
        45: "foggy", 48: "depositing rime fog",
        51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
        56: "light freezing drizzle", 57: "dense freezing drizzle",
        61: "slight rain", 63: "moderate rain", 65: "heavy rain",
        66: "light freezing rain", 67: "heavy freezing rain",
        71: "slight snowfall", 73: "moderate snowfall", 75: "heavy snowfall",
        77: "snow grains", 80: "slight rain showers", 81: "moderate rain showers",
        82: "violent rain showers", 85: "slight snow showers", 86: "heavy snow showers",
        95: "thunderstorm", 96: "thunderstorm with slight hail",
        99: "thunderstorm with heavy hail",
    }
    return descriptions.get(code, "unknown")


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


def fetch_news_google(topic: str = "", max_items: int = 10) -> list[NewsHeadline]:
    """Fetch top headlines from Google News RSS (no API key needed)."""
    import xml.etree.ElementTree as ET
    headlines = []
    try:
        if topic:
            url = f"https://news.google.com/rss/search?q={urllib.request.quote(topic)}&hl=en-US&gl=US&ceid=US:en"
        else:
            url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"

        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "chibi-llm/1.0")
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read().decode()

        root = ET.fromstring(xml_data)
        for item in root.findall(".//item")[:max_items]:
            title = item.findtext("title", "")
            source = item.findtext("source", "")
            pub_date = item.findtext("pubDate", "")
            link = item.findtext("link", "")

            # Clean up title — Google News appends " - Source" to titles
            if " - " in title and source:
                title = title.rsplit(" - ", 1)[0].strip()

            # Parse date to something short
            short_date = ""
            if pub_date:
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(pub_date)
                    short_date = dt.strftime("%I:%M %p")
                except Exception:
                    short_date = pub_date[:16]

            headlines.append(NewsHeadline(
                title=title,
                source=source,
                published=short_date,
                url=link,
            ))

    except Exception as e:
        print(f"[News] Google News RSS error: {e}")

    return headlines


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
        self.news = NewsData()
        self._running = True
        self._lock = threading.Lock()

        # Start background threads
        if self.config.weather_enabled:
            t = threading.Thread(target=self._weather_loop, daemon=True)
            t.start()

        if self.config.market_enabled:
            t = threading.Thread(target=self._market_loop, daemon=True)
            t.start()

        if getattr(self.config, 'news_enabled', True):
            t = threading.Thread(target=self._news_loop, daemon=True)
            t.start()

    def _weather_loop(self):
        """Fetch weather periodically with fallback chain."""
        while self._running:
            data = None
            try:
                if self.config.weather_api_key:
                    data = fetch_weather_owm(
                        self.config.weather_api_key,
                        self.config.weather_city,
                    )

                # Try wttr.in first (if no OWM key or OWM failed)
                if not data or not data.description:
                    data = fetch_weather_wttr(self.config.weather_city)

                # Fallback to Open-Meteo if wttr.in failed
                if not data or not data.description:
                    print("[Weather] wttr.in failed, trying Open-Meteo...")
                    data = fetch_weather_openmeteo(self.config.weather_city)

                # Only update if we got valid data
                if data and data.description:
                    with self._lock:
                        self.weather = data
                    print(f"[Weather] Updated: {data.description}, {data.temperature:.0f}°F")
                else:
                    print("[Weather] All sources failed, keeping previous data")

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

    def _news_loop(self):
        """Fetch news headlines periodically."""
        interval = getattr(self.config, 'news_interval', 600)
        topic = getattr(self.config, 'news_topic', '')
        while self._running:
            try:
                headlines = fetch_news_google(topic=topic, max_items=10)
                with self._lock:
                    self.news = NewsData(
                        headlines=headlines,
                        updated_at=datetime.now().strftime("%H:%M"),
                    )
                print(f"[News] Updated: {len(headlines)} headlines")
            except Exception as e:
                print(f"[News] Feed error: {e}")
            time.sleep(interval)

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

            if getattr(self.config, 'news_enabled', True) and self.news.headlines:
                parts.append(f"[NEWS HEADLINES] {self.news.summary()}")

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

    def get_news(self) -> NewsData:
        with self._lock:
            return self.news

    def stop(self):
        self._running = False
