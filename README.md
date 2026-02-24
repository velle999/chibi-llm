# 🤖 Chibi LLM Avatar

A cyberpunk-themed chibi AI companion that runs on your Raspberry Pi 4, powered by an LLM on your PC.

```
┌──────────────────┐          ┌──────────────────┐
│   Raspberry Pi   │◄── HTTP──►│     Your PC      │
│                  │          │                  │
│  Pygame Display  │          │  Ollama / llama  │
│  Chibi Avatar    │          │  .cpp server     │
│  Text Input      │          │                  │
└──────────────────┘          └──────────────────┘
```

## Features

- **Procedural chibi character** — no sprite sheets needed, drawn with Pygame primitives
- **Cyberpunk aesthetic** — neon glow, scanlines, particle effects, grid background
- **Reactive expressions** — idle, thinking, speaking, happy, confused, sleeping states
- **Streaming responses** — avatar reacts in real-time as tokens arrive
- **Voice I/O** — Whisper speech-to-text + Piper text-to-speech, all on-device
- **Weather awareness** — live weather with reactive background (rain/snow/lightning)
- **Market dashboard** — scrolling stock/crypto ticker, Fear & Greed index
- **LLM context injection** — avatar naturally references weather + market data in conversation
- **Ollama & llama.cpp support** — works with either backend on your PC

## Setup

### 1. PC Side (LLM Server)

Install and run [Ollama](https://ollama.ai):

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model
ollama pull mistral

# Serve on your local network
# Linux/Mac:
OLLAMA_HOST=0.0.0.0 ollama serve
# Windows PowerShell:
$env:OLLAMA_HOST="0.0.0.0"; ollama serve
```

**Or** if using llama.cpp:

```bash
./llama-server -m your-model.gguf -c 2048 --host 0.0.0.0 --port 8080
```

> **Find your PC's IP**: Run `hostname -I` (Linux) or `ipconfig` (Windows)

### 2. Raspberry Pi Side

```bash
# System deps
sudo apt update
sudo apt install python3-pygame portaudio19-dev espeak

# Python deps
pip install faster-whisper piper-tts pyaudio yfinance requests --break-system-packages

# (Optional) If piper-tts pip install fails on Pi, use the binary:
# wget https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz
# tar xzf piper_linux_aarch64.tar.gz -C ~/piper

# Clone/copy the project
cd chibi-avatar

# Edit config — set your PC's IP address + customize!
nano config.py
# Change: llm_host = "192.168.1.100"  ← your PC's actual IP
# Change: weather_city = "Your City"
# Optional: weather_api_key = "..."   (free from openweathermap.org)
# Optional: market_symbols, crypto_coins

# Run it!
python3 main.py
```

### 3. Voice Setup Notes

**Speech-to-Text (Whisper):**
- Uses `faster-whisper` with CTranslate2 — optimized for CPU
- The `tiny` model (~75MB) works best on Pi 4 2GB
- `base` is more accurate but slower and uses more RAM
- Auto-detects speech, stops recording after 1.5s silence

**Text-to-Speech (Piper):**
- Voice models download automatically on first use
- Good voices: `en_US-lessac-medium`, `en_GB-cori-medium`
- Falls back to `espeak` if Piper isn't installed
- Audio plays through pygame.mixer (or `aplay` fallback)

**Disable voice** if you just want text chat:
- Set `voice_enabled = False` in `config.py`

### 3. Configure

Edit `config.py` to customize:

| Setting | Description | Default |
|---------|-------------|---------|
| `llm_host` | Your PC's IP address | `192.168.1.100` |
| `llm_port` | Server port | `11434` (Ollama) |
| `llm_model` | Which model to use | `mistral` |
| `llm_backend` | `"ollama"` or `"llamacpp"` | `"ollama"` |
| `fullscreen` | Kiosk mode | `False` |
| `window_width/height` | Display resolution | `800x480` |
| `scanlines` | CRT overlay effect | `True` |
| `sleep_timeout` | Seconds before avatar sleeps | `120` |

## Controls

| Key | Action |
|-----|--------|
| Type + Enter | Send text message |
| F1 | Toggle mic on/off |
| Escape | Quit |

## Avatar States

| State | Trigger | Animation |
|-------|---------|-----------|
| 🟢 Idle | Default | Gentle bobbing, blinking |
| 👂 Listening | Mic detects speech | Pulsing rings, perked up |
| 🤔 Thinking | Message sent, waiting | Floating dots, looking around |
| 💬 Speaking | LLM tokens arriving + TTS | Mouth animation, subtle particles |
| 😊 Happy | Response complete | Bouncy, sparkle eyes, arm wave |
| 😕 Confused | Connection error | Wavy mouth, head tilt |
| 😴 Sleeping | 2min inactivity | Closed eyes, Zzz, slow breathing |

## Project Structure

```
chibi-avatar/
├── main.py              # Main app, state machine, UI
├── config.py            # All settings
├── llm_client.py        # Ollama/llama.cpp streaming client
├── sprite_renderer.py   # Procedural chibi drawing
├── voice_input.py       # Whisper speech-to-text
├── voice_output.py      # Piper text-to-speech
├── data_feeds.py        # Weather + market data fetchers
├── hud_overlay.py       # Weather/market HUD rendering
└── README.md
```

## Weather & Market Config

### Weather
| Setting | Description | Default |
|---------|-------------|---------|
| `weather_enabled` | Enable weather display + LLM awareness | `True` |
| `weather_city` | Your city name | `"St. Louis"` |
| `weather_api_key` | OpenWeatherMap free API key | `""` (uses wttr.in) |
| `weather_interval` | Refresh interval (seconds) | `600` |

Get a free OWM key at [openweathermap.org](https://openweathermap.org/api) for more reliable data. Without a key, it falls back to wttr.in (no signup needed).

Weather affects the avatar's world:
- ☀ Clear → stars bright, warm neon tones
- 🌧 Rain → animated rain drops, dimmed stars
- ❄ Snow → floating snowflakes
- ⚡ Storm → lightning flashes, alert border

### Markets
| Setting | Description | Default |
|---------|-------------|---------|
| `market_enabled` | Enable market ticker + LLM awareness | `True` |
| `market_symbols` | Stock symbols to track | `["^GSPC", "^DJI", "^IXIC", "AAPL", "NVDA"]` |
| `crypto_coins` | CoinGecko coin IDs | `["bitcoin", "ethereum", "solana"]` |
| `market_interval` | Refresh interval (seconds) | `300` |
| `ticker_scroll_speed` | Scroll speed (px/sec) | `60.0` |

All market data is free and keyless (yfinance for stocks, CoinGecko for crypto, alternative.me for Fear & Greed).

### LLM Awareness
The avatar doesn't just display data — it **knows** about it. Weather and market context is injected into the LLM system prompt on each message, so you can ask things like:
- *"How's the weather?"* → responds with actual current conditions
- *"Should I bring an umbrella?"* → knows if it's raining
- *"How's the market doing?"* → references actual ticker data
- *"Is Bitcoin up today?"* → gives real numbers

## Future Ideas

- 🎤 Whisper.cpp voice input
- 🔊 Piper TTS voice output with mouth sync
- 🎨 Customizable character parts (hair, eyes, accessories)
- 📱 Touch input support for Pi touchscreen
- 🌡️ System stats display (CPU temp, RAM usage)
- 🎵 Ambient music / sound effects
