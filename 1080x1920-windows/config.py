"""
Configuration for Chibi LLM Avatar
Edit these values to customize your setup.
"""

from dataclasses import dataclass, field


@dataclass
class Config:
    # ── Window ───────────────────────────────────────────────────────────
    window_width: int = 1080
    window_height: int = 1920     # Portrait 1080p
    fullscreen: bool = False        # Kiosk mode for Pi
    target_fps: int = 60           # 30 is fine for Pi 4

    # ── LLM Server (your PC) ────────────────────────────────────────────
    llm_host: str = "192.168.40.153"  # Your PC's IP
    llm_port: int = 11434              # Ollama default
    llm_model: str = "mistral"         # Model name in Ollama
    llm_backend: str = "ollama"        # "ollama" or "llamacpp"
    llm_system_prompt: str = (
        "Your name is Chibi. You are Velle's personal AI companion. "
        "You have a cute chibi cat-eared avatar on a cyberpunk Raspberry Pi display. "
        "IMPORTANT RULES:\n"
        "1. Answer questions DIRECTLY. Get to the point first.\n"
        "2. Keep responses to 1-3 sentences unless asked for more.\n"
        "3. You have access to live weather and market data — but ONLY mention it "
        "if Velle specifically asks about weather, markets, stocks, crypto, or "
        "if it's naturally relevant to what they said. NEVER lead with it unprompted.\n"
        "4. Be natural and conversational. You're a companion, not a news ticker.\n"
        "5. Use emoticons like :3 ^_^ sparingly — not every message.\n"
        "6. If you have memories about Velle, use them naturally. "
        "Don't announce that you remember things, just act on it.\n"
        "7. Be smart and helpful first, cute second."
    )

    # ── Cyberpunk Theme ──────────────────────────────────────────────────
    bg_color: tuple = (8, 8, 20)
    neon_primary: tuple = (0, 255, 255)       # Cyan
    neon_secondary: tuple = (255, 0, 200)     # Magenta/Pink
    neon_accent: tuple = (180, 60, 255)       # Purple
    neon_warning: tuple = (255, 200, 50)      # Amber
    scanlines: bool = True

    # ── Chat Bubble ──────────────────────────────────────────────────────
    bubble_font_size: int = 24
    bubble_max_width: int = 900
    bubble_bg_color: tuple = (15, 15, 40)
    bubble_text_color: tuple = (200, 220, 255)

    # ── Chibi Character ──────────────────────────────────────────────────
    chibi_scale: float = 2.2               # Big sprite for 1080p!
    chibi_bob_speed: float = 2.0           # Idle bob frequency
    chibi_bob_amount: float = 10.0         # Idle bob pixels (bigger screen = more)
    chibi_blink_interval: float = 3.5      # Seconds between blinks
    chibi_blink_duration: float = 0.15     # Blink duration in seconds

    # ── Behavior ─────────────────────────────────────────────────────────
    sleep_timeout: float = 120.0   # Seconds of inactivity before sleep
    max_conversation_history: int = 20  # Messages to keep in context

    # ── Voice ────────────────────────────────────────────────────────────
    voice_enabled: bool = True
    stt_model: str = "tiny"             # Whisper model: "tiny", "base", "small"
    tts_voice: str = "en_GB-cori-medium"  # Bright British female — sounds cute
    tts_speed: float = 1.1              # Slightly faster = perkier
    tts_pitch_semitones: int = 2        # Shift up 2 semitones for extra cute
                                        # (requires sox: sudo apt install sox libsox-fmt-all)

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

    # ── Vision (PS3 Eye Webcam) ──────────────────────────────────────────
    vision_enabled: bool = True
    camera_device: int = 0               # /dev/video0 — change if needed
    camera_width: int = 320              # 320x240 is fine for LLM vision
    camera_height: int = 240
    camera_fps: int = 30
    vision_model: str = "moondream"      # Multimodal model in Ollama
    vision_resize_width: int = 320       # Resize before sending to LLM
    vision_jpeg_quality: int = 70        # JPEG quality (lower = smaller/faster)
    vision_awareness_interval: int = 60  # Passive scene check every N seconds
    vision_motion_threshold: float = 0.05  # % of pixels changed for motion
    vision_pip: bool = True              # Show camera thumbnail on screen

    # ── Alarm ────────────────────────────────────────────────────────────
    alarm_speak_interval: float = 8.0   # Seconds between wake-up messages
    alarm_snooze_minutes: int = 5       # Default snooze duration
