"""
Configuration for Chibi LLM Avatar
Edit these values to customize your setup.
"""

from dataclasses import dataclass, field


@dataclass
class Config:
    # ── Window ───────────────────────────────────────────────────────────
    window_width: int = 800
    window_height: int = 480      # Common Pi touchscreen resolution
    fullscreen: bool = True        # Kiosk mode for Pi
    target_fps: int = 30           # 30 is fine for Pi 4

    # ── LLM Server (your PC) ────────────────────────────────────────────
    llm_host: str = "192.168.40.153"  # Your PC's IP
    llm_port: int = 11434              # Ollama default
    llm_model: str = "mistral"         # Model name in Ollama
    llm_backend: str = "ollama"        # "ollama" or "llamacpp"
    llm_system_prompt: str = (
        "Your name is Chibi. You are a cute, kawaii AI companion with a chibi cat-eared avatar! "
        "Your user's name is Velle. Always call them Velle. "
        "Keep responses concise (2-3 sentences max). "
        "Be playful, warm, and expressive. Use emoticons like :3 ^_^ >w< occasionally. "
        "You live inside a cyberpunk display on a Raspberry Pi. "
        "If you have memories about Velle, reference them naturally — "
        "recall past conversations and remember their preferences. "
        "If Velle says 'remember this' or asks you to remember something, "
        "acknowledge it warmly. You genuinely care about Velle!"
    )

    # ── Cyberpunk Theme ──────────────────────────────────────────────────
    bg_color: tuple = (8, 8, 20)
    neon_primary: tuple = (0, 255, 255)       # Cyan
    neon_secondary: tuple = (255, 0, 200)     # Magenta/Pink
    neon_accent: tuple = (180, 60, 255)       # Purple
    neon_warning: tuple = (255, 200, 50)      # Amber
    scanlines: bool = True

    # ── Chat Bubble ──────────────────────────────────────────────────────
    bubble_font_size: int = 16
    bubble_max_width: int = 450
    bubble_bg_color: tuple = (15, 15, 40)
    bubble_text_color: tuple = (200, 220, 255)

    # ── Chibi Character ──────────────────────────────────────────────────
    chibi_scale: float = 1.0               # Scale multiplier
    chibi_bob_speed: float = 2.0           # Idle bob frequency
    chibi_bob_amount: float = 6.0          # Idle bob pixels
    chibi_blink_interval: float = 3.5      # Seconds between blinks
    chibi_blink_duration: float = 0.15     # Blink duration in seconds

    # ── Behavior ─────────────────────────────────────────────────────────
    sleep_timeout: float = 120.0   # Seconds of inactivity before sleep
    max_conversation_history: int = 20  # Messages to keep in context

    # ── Voice ────────────────────────────────────────────────────────────
    voice_enabled: bool = True
    stt_model: str = "tiny"             # Whisper model: "tiny", "base", "small"
    tts_voice: str = "en_US-lessac-medium"  # Piper voice name
    tts_speed: float = 1.0              # Speech rate (1.0 = normal)

    # ── Weather ──────────────────────────────────────────────────────────
    weather_enabled: bool = True
    weather_city: str = "St. Louis"     # Your city
    weather_api_key: str = ""           # OpenWeatherMap key (free). Leave empty for wttr.in
    weather_interval: int = 600         # Fetch every 10 minutes

    # ── Markets ──────────────────────────────────────────────────────────
    market_enabled: bool = True
    market_symbols: list = field(default_factory=lambda: [
        "^GSPC",     # S&P 500
        "^DJI",      # Dow Jones
        "^IXIC",     # NASDAQ
        "AAPL",      # Apple
        "NVDA",      # Nvidia
    ])
    crypto_coins: list = field(default_factory=lambda: [
        "bitcoin",
        "ethereum",
        "solana",
    ])
    market_interval: int = 300          # Fetch every 5 minutes
    ticker_scroll_speed: float = 60.0   # Pixels per second
