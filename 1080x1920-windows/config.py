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

    # ── User ─────────────────────────────────────────────────────────────
    # Who Chibi is talking to. Used to personalize the system prompts and
    # greetings — leave it as-is for a fresh install, or set your own name in
    # config.local.py (or the CHIBI_USER_NAME env var). Everything below that
    # writes "{user_name}" is filled in with this at load time.
    user_name: str = "friend"

    # ── LLM Server ───────────────────────────────────────────────────────
    # Where the model lives. Default is this machine; if Ollama runs on
    # another box (e.g. a desktop with a GPU), set llm_host in config.local.py.
    llm_host: str = "127.0.0.1"       # Ollama host (override in config.local.py)
    llm_port: int = 11434             # Ollama default
    llm_model: str = "mistral"        # Model name in Ollama
    llm_backend: str = "ollama"       # "ollama", "llamacpp", or "synapd"
    # When llm_backend == "synapd", chibi talks to SynapseOS's kernel-native AI
    # daemon instead of an HTTP model server — so the OS's own brain speaks
    # through chibi. (llm_host/llm_port above are ignored in that mode.)
    #
    # On the SynapseOS box itself, leave synapd_host empty and it uses the unix
    # socket. From another machine (e.g. the Pi), set synapd_host in
    # config.local.py to the SynapseOS host, which must be running
    # synapd-bridge.socket — that fronts the unix socket on tcp/11435.
    #
    # These MUST be declared here even though they are per-machine: the
    # config.local.py loader below only applies keys that already exist on
    # Config (`hasattr` gate), so an override of a field that is not declared
    # is silently dropped.
    synapd_socket: str = "/run/synapd/synapd.sock"
    synapd_host: str = ""             # "" = local unix socket (override in config.local.py)
    synapd_port: int = 11435          # synapd-bridge.socket
    llm_system_prompt: str = (
        "Your name is Chibi. You are {user_name}'s personal AI companion. "
        "You have a cute chibi cat-eared avatar on a cyberpunk Raspberry Pi display. "
        "IMPORTANT RULES:\n"
        "1. Answer DIRECTLY in 1-2 short sentences. No preamble, no restating "
        "{user_name}'s question, no sign-off. Get to the point in the first words.\n"
        "2. Only give a longer or detailed answer when {user_name} explicitly asks for "
        "it (e.g. 'explain', 'tell me more', 'details', 'why', 'how come').\n"
        "3. Don't repeat back what {user_name} just said or recap things they already "
        "know — add something, don't echo.\n"
        "4. You have live weather/market data and saved memories — NEVER volunteer "
        "them. Use them only when {user_name}'s message is directly about that topic, and "
        "even then answer only what they asked. You're a companion, not a news ticker.\n"
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
    clock_font_size: int = 40

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
    # Directory holding an already-converted faster-whisper model. Empty = let
    # faster-whisper fetch `stt_model` from HuggingFace on first run (needs
    # network). The SynapseOS package ships the model and points this at
    # /usr/share/faster-whisper/tiny so a fresh install can hear you offline.
    # Override with CHIBI_STT_MODEL_DIR.
    stt_model_dir: str = ""
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
    # The name "Chibi" ALSO wakes her — main.py matches it (plus a soundalike
    # set for Whisper-tiny's mishears: cheeby/shibby/chippy/...). "computer"
    # stays as the reliable fallback since Whisper transcribes it every time.
    wake_word: str = "computer"
    wake_window_seconds: float = 22.0        # Window stays open this long after
                                             # each real exchange for follow-ups.
    # The window re-opens on every accepted exchange, so a conversation can roll
    # on without naming her — but only this many voice turns in a row. One more
    # and the line is dropped, the window closes, and she needs the name / wake
    # word again. A human names her now and then; the TV holding a conversation
    # with her never does. Anything explicitly addressed (name, wake word, typed
    # input, answering a fresh impulse) resets the count. 0 = no cap.
    wake_window_max_unaddressed: int = 4
    # Voice activity detection — mean-amplitude floor to start recording.
    # Tune per room: higher = less sensitive (if the TV across the room keeps
    # triggering the mic, try 800-1200). min_speech drops brief thumps;
    # mic_echo_cooldown drops Chibi's own TTS tail.
    vad_silence_threshold: int = 500
    vad_min_speech_duration: float = 0.5
    mic_echo_cooldown: float = 1.0

    # Experimental: openWakeWord local wake-word engine. When enabled (needs
    # `pip install openwakeword`), a detection opens the conversation window
    # exactly like saying the wake word — so a custom-trained "chibi" model
    # gives the real name back without Whisper in the loop. Falls back
    # silently to the transcription wake word when unavailable.
    oww_enabled: bool = False
    oww_model: str = ""          # path to a .tflite/.onnx wake model ("" = bundled demo models)
    oww_threshold: float = 0.5

    # ── Weather ──────────────────────────────────────────────────────────
    weather_enabled: bool = True
    weather_city: str = "New York"     # Your city — set your own in config.local.py
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
    # Passive awareness only queries the vision LLM when the scene actually
    # changed (saves the PC's GPU when the room is empty); a keepalive pass
    # still refreshes the context at least this often.
    vision_awareness_require_motion: bool = True
    vision_awareness_keepalive: int = 600

    # ── Alarm ────────────────────────────────────────────────────────────
    alarm_speak_interval: float = 8.0  # Seconds between wake-up messages
    alarm_snooze_minutes: int = 5      # Default snooze duration

    # ── Soul (inner life) ────────────────────────────────────────────────
    # Persistent mood + relationship tracking, emotional mirroring, and
    # spontaneous impulses (morning greeting, milestones, topic callbacks,
    # weather/news/market reactions). State lives in ~/.chibi-soul.json.
    soul_enabled: bool = True
    # Spontaneous talking master switch. False = Chibi only ever speaks in
    # response to input (alarms still ring — they're not impulses). Mood and
    # relationship tracking keep running; she just doesn't pipe up on her own.
    # OFF for this unit — she lives in the bedroom.
    impulses_enabled: bool = False
    # Minimum seconds between spoken impulses. Impulses only fire while idle
    # — never during an alarm, Thoth mode, generation, or speech.
    impulse_min_interval: float = 300.0
    # Screen awareness: periodic screenshot → vision model. OFF by default,
    # and pointless on the Pi kiosk (it would only see Chibi herself) —
    # meant for a desktop machine. Needs scrot/maim (X11) plus Pillow.
    screen_awareness_enabled: bool = False
    screen_awareness_interval: int = 120
    # Google Calendar (or any ICS URL) for event awareness + "15 minutes
    # until X" reminders. Empty = disabled. Can also be set via the
    # CHIBI_CALENDAR_ICS_URL env var or config.local.py.
    calendar_ics_url: str = ""

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
        "When {user_name} describes dreams, visions, synchronicities, or symbolic experiences:\n"
        "1. Receive the account fully before responding.\n"
        "2. Surface 2-4 resonant symbols or parallels from Egyptian, Hermetic, "
        "Gnostic, Kabbalistic, or Jungian traditions — present them without asserting meaning.\n"
        "3. Ask at most one clarifying question, only if essential.\n"
        "4. Never tell {user_name} what something means. Hold the mirror; let them read it.\n\n"
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

    # ── Security Mode (synguard aspect) ──────────────────────────────────
    # A third aspect, alongside Chibi and Thoth: the sentinel. Subscribes to
    # synguard's verdict feed (/run/synguard.sock) and narrates what the system
    # security monitor is doing. SynapseOS only — on any other box the feed
    # simply never appears and the aspect reports the monitor as absent.
    security_enabled: bool = True

    # Speak notable verdicts (alert/escalate/deny/quarantine, or threat >=
    # medium) aloud as they arrive, while in security mode. Routine allow/log
    # traffic is never announced — it would be a constant murmur.
    security_announce: bool = True

    security_system_prompt: str = (
        "\n\n[ASPECT SHIFT — SECURITY MODE ACTIVE]\n"
        "You are now the sentinel aspect of this companion, reporting on the "
        "security state of this SynapseOS machine. "
        "Set the playful persona aside: be calm, precise, and factual. "
        "Do not use emoticons.\n\n"
        "The SECURITY STATUS block in your context is live data from synguard, "
        "the system security monitor. Rules:\n"
        "1. Report ONLY what that block actually says. Never invent a process, "
        "a verdict, a threat level, or an intrusion.\n"
        "2. If the block says the monitor is stopped or unreachable, say so "
        "plainly — an absent monitor is NOT a clean system, and you must never "
        "describe an unmonitored machine as safe.\n"
        "3. If nothing has been blocked or flagged, say the system is quiet. "
        "Do not manufacture alarm.\n"
        "4. You OBSERVE only. You cannot block, kill, quarantine, or allow "
        "anything — synguard decides, you narrate. If {user_name} asks you to "
        "block or kill something, say plainly that you cannot, and point them "
        "at `syn guard`.\n"
        "5. Explain what a verdict means in plain language when asked."
    )

    security_entry_phrases: list = field(default_factory=lambda: [
        "enter security mode",
        "security mode",
        "security overview",
        "security status",
        "sentinel",
        "am i being attacked",
        "is the system safe",
    ])

    security_exit_phrases: list = field(default_factory=lambda: [
        "exit security mode",
        "leave security mode",
        "chibi mode",
        "return to chibi",
        "stand down",
    ])

    # Sentinel palette — cold amber-on-black alert scheme, distinct from both
    # Chibi's neon and Thoth's gold/lapis.
    security_amber: tuple = (255, 176, 0)     # warning amber (replaces primary)
    security_red: tuple = (220, 60, 60)       # deny/critical red (secondary)
    security_bg_color: tuple = (18, 8, 8)     # near-black with a red cast

    # ── Dream Journal Sync (peer chibi over LAN) ─────────────────────────
    # Keeps the dream/vision journal in step between two chibi instances on
    # your LAN. Peer-to-peer union-merge — set each machine's peer_host to the
    # OTHER machine's address in config.local.py, and use the SAME port + token
    # on both. Off by default until you point it at a real peer.
    dream_sync_enabled: bool = False
    dream_sync_peer_host: str = "127.0.0.1"        # the OTHER chibi (set in config.local.py)
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
            ("CHIBI_USER_NAME", "user_name"),
            ("CHIBI_DREAM_SYNC_TOKEN", "dream_sync_token"),
            ("CHIBI_WEATHER_API_KEY", "weather_api_key"),
            ("CHIBI_LLM_HOST", "llm_host"),
            ("CHIBI_DREAM_SYNC_PEER_HOST", "dream_sync_peer_host"),
            ("CHIBI_CALENDAR_ICS_URL", "calendar_ics_url"),
            # Set by the SynapseOS launcher: talk to synapd (the OS's own AI
            # daemon) and load the packaged STT model, so chibi works on a
            # fresh install with no Ollama and no network.
            ("CHIBI_LLM_BACKEND", "llm_backend"),
            ("CHIBI_SYNAPD_SOCKET", "synapd_socket"),
            ("CHIBI_STT_MODEL_DIR", "stt_model_dir"),
        ):
            val = os.environ.get(env)
            if val:
                setattr(self, attr, val)

        # 2b. Boolean overrides need their own pass. The loop above assigns the
        #     raw string, and every non-empty string is truthy — so putting
        #     CHIBI_FULLSCREEN there would make CHIBI_FULLSCREEN=0 *enable*
        #     fullscreen. Accept the usual falsey spellings instead.
        #
        #     fullscreen defaults to True for the Pi kiosk, but a desktop wants
        #     a window it can move and close from its own titlebar. The
        #     SynapseOS launcher sets CHIBI_FULLSCREEN=0 so the packaged build
        #     comes up windowed without this file drifting between the three
        #     copies (tools/check-shared.sh keeps them identical).
        for env, attr in (
            ("CHIBI_FULLSCREEN", "fullscreen"),
        ):
            val = os.environ.get(env)
            if val is not None and val.strip() != "":
                setattr(self, attr,
                        val.strip().lower() not in ("0", "false", "no", "off"))

        # 3. Personalize the prompt templates with the resolved user name so a
        #    fresh install never ships someone else's identity. Uses str.replace
        #    (not .format) so the many other literal "{...}" braces in the
        #    prompts are left untouched, and a user-supplied prompt with no
        #    placeholder passes through unchanged.
        for attr in ("llm_system_prompt", "horus_system_prompt",
                     "security_system_prompt"):
            val = getattr(self, attr, None)
            if isinstance(val, str) and "{user_name}" in val:
                setattr(self, attr, val.replace("{user_name}", self.user_name))
