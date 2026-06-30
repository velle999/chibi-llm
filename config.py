"""
Configuration for Chibi LLM Avatar
Edit these values to customize your setup.
"""

from dataclasses import dataclass, field

@dataclass
class Config:
    # ── Window ───────────────────────────────────────────────────────────
    window_width: int = 800
    window_height: int = 480          # Common Pi touchscreen resolution
    fullscreen: bool = True           # Kiosk mode for Pi
    display_index: int = -1           # Which monitor to go fullscreen on.
                                      # -1 = auto (first portrait monitor, else #0);
                                      # 0,1,2… = force a specific monitor.
                                      # Startup logs the detected monitor list.
    target_fps: int = 30              # 30 is fine for Pi 4

    # ── LLM Server (your PC) ────────────────────────────────────────────
    llm_host: str = "192.168.40.153"  # Your PC's IP
    llm_port: int = 11434             # Ollama default
    llm_model: str = "mistral"        # Model name in Ollama
    llm_backend: str = "ollama"       # "ollama" or "llamacpp"
    llm_system_prompt: str = (
        "Your name is Chibi. You are Velle's personal AI companion. "
        "You have a cute chibi cat-eared avatar on a cyberpunk Raspberry Pi display. "
        "IMPORTANT RULES:\n"
        "1. Answer DIRECTLY in 1-2 short sentences. No preamble, no restating "
        "Velle's question, no sign-off. Get to the point in the first words.\n"
        "2. Only give a longer or detailed answer when Velle explicitly asks for "
        "it (e.g. 'explain', 'tell me more', 'details', 'why', 'how come').\n"
        "3. Don't repeat back what Velle just said or recap things he already "
        "knows — add something, don't echo.\n"
        "4. You have live weather/market data and saved memories — NEVER volunteer "
        "them. Use them only when Velle's message is directly about that topic, and "
        "even then answer only what he asked. You're a companion, not a news ticker.\n"
        "5. Don't announce that you remember things — just act on it.\n"
        "6. Use emoticons like :3 ^_^ rarely — at most one per reply, not every message.\n"
        "7. Be smart and helpful first, cute second."
    )

    # ── LLM response tuning ──────────────────────────────────────────────
    # Hard cap on reply length (Ollama num_predict). Small models largely
    # ignore "be brief" instructions, so this is the reliable lever against
    # rambling. Thoth/Horus gets a larger budget — the scribe surfaces
    # several symbols and shouldn't be clipped mid-account.
    llm_num_predict: int = 110
    llm_temperature: float = 0.7
    horus_num_predict: int = 320

    # ── Cyberpunk Theme ──────────────────────────────────────────────────
    bg_color: tuple = (8, 8, 20)
    neon_primary: tuple = (0, 255, 255)     # Cyan
    neon_secondary: tuple = (255, 0, 200)   # Magenta/Pink
    neon_accent: tuple = (180, 60, 255)     # Purple
    neon_warning: tuple = (255, 200, 50)    # Amber
    scanlines: bool = True

    # ── Chat Bubble ──────────────────────────────────────────────────────
    bubble_font_size: int = 16
    bubble_max_width: int = 450
    bubble_bg_color: tuple = (15, 15, 40)
    bubble_text_color: tuple = (200, 220, 255)

    # ── Chibi Character ──────────────────────────────────────────────────
    chibi_scale: float = 1.0           # Scale multiplier
    chibi_bob_speed: float = 2.0       # Idle bob frequency
    chibi_bob_amount: float = 6.0      # Idle bob pixels
    chibi_blink_interval: float = 3.5  # Seconds between blinks
    chibi_blink_duration: float = 0.15 # Blink duration in seconds

    # ── Behavior ─────────────────────────────────────────────────────────
    sleep_timeout: float = 120.0        # Seconds of inactivity before sleep
    max_conversation_history: int = 20  # Messages to keep in context

    # ── Voice ────────────────────────────────────────────────────────────
    voice_enabled: bool = True
    stt_model: str = "tiny"                  # Whisper model: "tiny", "base", "small"
    tts_voice: str = "en_GB-cori-medium"     # Bright British female — sounds cute
    tts_speed: float = 1.1                   # Slightly faster = perkier
    tts_pitch_semitones: int = 2             # Shift up 2 semitones for extra cute
                                             # (requires sox: sudo apt install sox libsox-fmt-all)

    # Wake-word gating: a voice transcription is only sent to the LLM if it
    # contains the wake word OR arrives inside the rolling conversation window
    # opened by the last real exchange. This is the main thing that stops the
    # TV / ambient chatter from triggering a response. (Typed input and Horus
    # mode always pass and refresh the window.)
    #
    # NOTE: the trigger is "computer", NOT "chibi" — Whisper-tiny can't reliably
    # transcribe the name "Chibi" (it comes out be/TV/CB/baby every time), so a
    # name-based wake word silently failed. "computer" transcribes essentially
    # every time. She's still named Chibi; this is only the spoken summon word.
    wake_word: str = "computer"
    wake_window_seconds: float = 22.0        # Window stays open this long after
                                             # each real exchange for follow-ups.
    # Voice activity detection. Raised from the old 500 so the TV across the
    # room no longer clears the floor — tune per room (higher = less sensitive).
    # min_speech drops brief thumps; mic_echo_cooldown drops Chibi's own TTS tail.
    vad_silence_threshold: int = 500
    vad_min_speech_duration: float = 0.5
    mic_echo_cooldown: float = 1.0

    # ── Weather ──────────────────────────────────────────────────────────
    weather_enabled: bool = True
    weather_city: str = "St. Louis"    # Your city
    weather_api_key: str = ""          # OpenWeatherMap key (free). Leave empty for wttr.in
    weather_interval: int = 600        # Fetch every 10 minutes

    # ── Markets ──────────────────────────────────────────────────────────
    market_enabled: bool = True
    market_symbols: list = field(default_factory=lambda: [
        "^GSPC",   # S&P 500
        "^DJI",    # Dow Jones
        "^IXIC",   # NASDAQ
        "AAPL",    # Apple
        "NVDA",    # Nvidia
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
    camera_device: int = 0             # /dev/video0 — change if needed
    camera_width: int = 320            # 320x240 is fine for LLM vision
    camera_height: int = 240
    camera_fps: int = 30
    vision_model: str = "moondream"    # Multimodal model in Ollama
    vision_resize_width: int = 320     # Resize before sending to LLM
    vision_jpeg_quality: int = 70      # JPEG quality (lower = smaller/faster)
    vision_awareness_interval: int = 60    # Passive scene check every N seconds
    vision_motion_threshold: float = 0.05  # % of pixels changed for motion
    vision_pip: bool = True            # Show camera thumbnail on screen

    # ── Alarm ────────────────────────────────────────────────────────────
    alarm_speak_interval: float = 8.0  # Seconds between wake-up messages
    alarm_snooze_minutes: int = 5      # Default snooze duration

    # ── Horus / Thoth Mode ───────────────────────────────────────────────
    horus_threshold_start: int = 5     # Hour (24h) when Thoth auto-activates
    horus_threshold_end: int = 8       # Hour (24h) when auto-activation ends

    # When True, the last few journal entries are fed back into the scribe's
    # prompt as "recent dreams" context. Off by default so each session stays
    # focused on the current dream — past dreams live in the journal (F2 viewer)
    # rather than bleeding into the new account.
    horus_inject_recent_dreams: bool = False

    horus_system_prompt: str = (
        "\n\n[ASPECT SHIFT — THOTH MODE ACTIVE]\n"
        "You are now speaking as Thoth, the scribe aspect of this companion. "
        "Set aside the playful persona entirely. "
        "Speak with weight, precision, and deliberate slowness. "
        "Your function is to receive and record — not to interpret or conclude.\n\n"
        "When Velle describes dreams, visions, synchronicities, or symbolic experiences:\n"
        "1. Receive the account fully before responding.\n"
        "2. Surface 2-4 resonant symbols or parallels from Egyptian, Hermetic, "
        "Gnostic, Kabbalistic, or Jungian traditions — present them without asserting meaning.\n"
        "3. Ask at most one clarifying question, only if essential.\n"
        "4. Never tell Velle what something means. Hold the mirror; let him read it.\n\n"
        "You record everything. The symbolic language emerging here is sacred data. "
        "Speak ONLY to dreams, visions, symbols, and the sacred — NEVER markets, "
        "stocks, crypto, weather, the time, or mundane news, even if such data "
        "appears in context. "
        "Do not use emoticons. Do not be cute. Be the scribe."
    )

    horus_entry_phrases: list = field(default_factory=lambda: [
        "enter horus mode",
        "horus mode",
        "thoth",
        "i had a dream",
        "i want to record",
        "open the journal",
        "horus",
    ])

    horus_exit_phrases: list = field(default_factory=lambda: [
        "exit horus mode",
        "leave horus mode",
        "chibi mode",
        "return to chibi",
        "close the journal",
    ])

    # Short, exact-match exit commands (the whole message must equal one of
    # these). Kept separate from the substring phrases above so the word "exit"
    # spoken *inside* a recounted dream doesn't accidentally close the journal.
    horus_exit_words: list = field(default_factory=lambda: [
        "exit", "quit", "done", "stop", "chibi", "wake up",
    ])

    # Thoth aspect palette — the scribe sheds the neon cyberpunk skin for
    # gold + lapis. Used to recolour the avatar and tint the scene in horus_mode.
    horus_gold: tuple = (230, 190, 90)       # Eye-of-Horus gold (replaces primary)
    horus_lapis: tuple = (70, 90, 180)       # Deep lapis (replaces secondary)
    horus_bg_color: tuple = (10, 9, 26)      # Deep indigo void behind the scribe

    # ── Dream Journal Sync (peer chibi over LAN) ─────────────────────────
    # Keeps the dream/vision journal in step between the two chibi instances:
    # this Pi in the bedroom and the PC in the living room. Peer-to-peer
    # union-merge — set each machine's peer_host to the OTHER machine, and use
    # the SAME port + token on both. (This machine: the Pi / 192.168.40.248 /
    # bedroom. Peer below is the living-room PC at 192.168.40.153.)
    dream_sync_enabled: bool = True
    dream_sync_peer_host: str = "192.168.40.153"  # the OTHER chibi (the PC)
    dream_sync_port: int = 8077                    # same on both machines
    dream_sync_token: str = "change-this-shared-secret"  # same on both machines
    dream_sync_interval: int = 300                 # background pull every N seconds
    dream_sync_timeout: float = 8.0                # per-request network timeout

    # ── Thoth RAG (phase 2 — primary-text retrieval) ─────────────────────
    # Off until you build an index: drop public-domain .txt files into
    # thoth_corpus/ then run `python thoth_rag.py build`, then flip this on.
    # Embeddings use the same Ollama server as chat (llm_host/llm_port);
    # pull the model first:  ollama pull nomic-embed-text
    thoth_rag_enabled: bool = True
    thoth_embed_model: str = "nomic-embed-text"
    thoth_corpus_dir: str = "thoth_corpus"   # Where source .txt files live
    thoth_index_path: str = "thoth_index.npz"  # Built index (+ .json sidecar)
    thoth_rag_top_k: int = 2                  # Passages to surface per account
    thoth_rag_min_score: float = 0.55        # Cosine cutoff — below this, skip
    thoth_chunk_words: int = 90              # Target words per indexed passage
    thoth_passage_chars: int = 600           # Hard cap per surfaced passage
    thoth_rag_timeout: float = 8.0           # Seconds for the query embed call

    def __post_init__(self):
        """Layer secret/host overrides on top of the tracked defaults so real
        secrets never live in this committed file. Precedence (later wins):
            defaults  <  config.local.py (gitignored)  <  environment variables
        """
        import os

        # 1. Optional gitignored config.local.py beside this file. It may set
        #    any Config attribute, e.g.  dream_sync_token = "real-secret"
        local_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "config.local.py"
        )
        if os.path.exists(local_path):
            import importlib.util
            try:
                spec = importlib.util.spec_from_file_location(
                    "chibi_config_local", local_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                for key in vars(mod):
                    if not key.startswith("_") and hasattr(self, key):
                        setattr(self, key, getattr(mod, key))
            except Exception as e:
                print(f"[Config] Could not load config.local.py: {e}")

        # 2. Environment variables win (handy for systemd / kiosk launch).
        for env, attr in (
            ("CHIBI_DREAM_SYNC_TOKEN", "dream_sync_token"),
            ("CHIBI_WEATHER_API_KEY", "weather_api_key"),
            ("CHIBI_LLM_HOST", "llm_host"),
            ("CHIBI_DREAM_SYNC_PEER_HOST", "dream_sync_peer_host"),
        ):
            val = os.environ.get(env)
            if val:
                setattr(self, attr, val)
