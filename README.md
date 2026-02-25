# Chibi-LLM 🐱

A kawaii AI companion that lives on your Raspberry Pi 4. Chibi is a voice-interactive chibi avatar with cat ears, cyberpunk aesthetics, weather awareness, market tracking, webcam vision, persistent memory, and a natural language alarm clock.

**Architecture:** Pi 4 handles display, voice I/O, and webcam. Your PC runs the LLM via Ollama.

## Features

- **Kawaii chibi avatar** — procedurally drawn with Pygame, cat ears, star-pupil eyes, floating hearts/sparkles, expressive animations across 8 states
- **Voice conversation** — Whisper STT + Piper TTS with a cute pitched-up British voice
- **Persistent memory** — remembers your name, preferences, and past conversations across restarts
- **Weather awareness** — live weather with reactive background (rain, snow, lightning effects)
- **Market dashboard** — scrolling stock/crypto ticker, Fear & Greed index
- **Webcam vision** — PS3 Eye camera for scene awareness, on-demand "what do you see"
- **Natural language alarms** — "wake me up at 7am", repeating voice wake-up until dismissed
- **Cyberpunk HUD** — clock, weather panel, scrolling ticker, camera PiP, neon everything
- **Ollama & llama.cpp** — works with either backend on your PC

## Quick Start

### PC Setup (Windows PowerShell)
```powershell
# Install and serve Ollama
$env:OLLAMA_HOST="0.0.0.0"; ollama serve

# In another terminal — pull models
ollama pull mistral        # Chat model
ollama pull moondream      # Vision model (optional)
```

### Pi Setup
```bash
git clone <your-repo> chibi-llm
cd chibi-llm
bash setup.sh
```

Or manually:
```bash
sudo apt update
sudo apt install -y python3-pygame portaudio19-dev espeak sox libsox-fmt-all alsa-utils

pip install piper-tts faster-whisper pyaudio yfinance requests opencv-python-headless --break-system-packages

# Download Chibi's voice
mkdir -p ~/.local/share/piper-voices
cd ~/.local/share/piper-voices
wget https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/cori/medium/en_GB-cori-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/cori/medium/en_GB-cori-medium.onnx.json
```

### Run
```bash
cd chibi-llm
python3 main.py
```

## Controls

| Input | Action |
|-------|--------|
| Type + Enter | Send text message |
| F1 | Toggle microphone |
| Escape | Quit |
| Any key during alarm | Dismiss alarm |

Voice commands work naturally — just talk.

## Project Structure

```
chibi-llm/
├── main.py              # App core, state machine, event loop, draw
├── config.py            # All settings in one place
├── sprite_renderer.py   # Kawaii chibi character (procedural)
├── llm_client.py        # Ollama/llama.cpp streaming client
├── voice_input.py       # Whisper speech-to-text
├── voice_output.py      # Piper TTS with pitch shifting
├── data_feeds.py        # Weather + market data fetchers
├── hud_overlay.py       # Weather panel, scrolling ticker, mini panel
├── memory.py            # Persistent long-term memory
├── vision.py            # PS3 Eye webcam + multimodal LLM
├── alarm.py             # Natural language alarm system
├── setup.sh             # One-shot Pi installer
└── README.md
```

## Configuration

Edit `config.py`. Key settings:

### LLM Server
| Setting | Default | Description |
|---------|---------|-------------|
| `llm_host` | `192.168.40.153` | Your PC's IP |
| `llm_port` | `11434` | Ollama default |
| `llm_model` | `mistral` | Chat model name |
| `llm_backend` | `ollama` | `ollama` or `llamacpp` |

### Voice
| Setting | Default | Description |
|---------|---------|-------------|
| `tts_voice` | `en_GB-cori-medium` | Piper voice model |
| `tts_speed` | `1.1` | Speech rate (higher = faster) |
| `tts_pitch_semitones` | `2` | Pitch shift (0=natural, 2-3=cute) |
| `stt_model` | `tiny` | Whisper model size |

### Weather
| Setting | Default | Description |
|---------|---------|-------------|
| `weather_city` | `St. Louis` | Your city |
| `weather_api_key` | `""` | OWM key (empty = uses wttr.in) |
| `weather_interval` | `600` | Refresh seconds |

Weather affects the background: rain drops, snowflakes, lightning flashes, dimmed stars on overcast days.

### Markets
| Setting | Default | Description |
|---------|---------|-------------|
| `market_symbols` | S&P, Dow, NASDAQ, AAPL, NVDA | Stock tickers |
| `crypto_coins` | BTC, ETH, SOL | CoinGecko IDs |
| `market_interval` | `300` | Refresh seconds |
| `ticker_scroll_speed` | `60.0` | Scroll px/sec |

All free, no API keys needed (yfinance + CoinGecko + alternative.me).

### Vision
| Setting | Default | Description |
|---------|---------|-------------|
| `camera_device` | `0` | /dev/video index |
| `vision_model` | `moondream` | Ollama multimodal model |
| `vision_awareness_interval` | `60` | Passive capture seconds |
| `vision_pip` | `True` | Show camera thumbnail |

Ask Chibi to look: *"what do you see"*, *"how do I look"*, *"read this"*

### Alarm
| Setting | Default | Description |
|---------|---------|-------------|
| `alarm_speak_interval` | `8.0` | Seconds between wake-up messages |
| `alarm_snooze_minutes` | `5` | Snooze duration |

Set alarms naturally: *"wake me up at 7am"*, *"set alarm for 6:30"*, *"alarm in 30 minutes"*. Dismiss with any keypress or voice. Say *"snooze"* for 5 more minutes.

## Avatar States

| State | Trigger | Visual |
|-------|---------|--------|
| IDLE | Default | Gentle bob, cat mouth :3, slow sparkles |
| LISTENING | Mic active | Pulsing rings, ear wiggle, open mouth |
| THINKING | Waiting for LLM | Floating star dots, swaying, "o" mouth |
| SPEAKING | Response streaming | Mouth animation + tongue, particles |
| HAPPY | Response complete | Bouncy, closed happy eyes, hearts + sparkles, fang smile |
| CONFUSED | Error | Spiral eyes, wavy mouth |
| SLEEPING | 2min idle | Tilted head, Zzz, drool, closed eyes |
| ALARM | Alarm fires | Super bounce, pulsing amber border, wake-up messages |

## Memory

Chibi remembers things across restarts via `~/.chibi-avatar-memory.json`:
- Auto-extracts facts from conversations (name, preferences, topics)
- Stores explicit notes ("remember that I like pizza")
- Conversation summaries
- Interaction stats (how long you've known each other)

To reset: `rm ~/.chibi-avatar-memory.json`

## Troubleshooting

**No sound:** Check `aplay -l` for audio devices. Make sure `alsa-utils` is installed.

**Piper not found:** Run `pip install piper-tts --break-system-packages` or download the binary from [piper releases](https://github.com/rhasspy/piper/releases).

**Camera not detected:** `ls /dev/video*` — PS3 Eye should be video0. Try `camera_device = 1` in config.

**LLM connection failed:** Make sure Ollama is serving on `0.0.0.0`: `$env:OLLAMA_HOST="0.0.0.0"; ollama serve`

**Voice feedback loop:** Should be fixed — mic pauses during TTS. If it still happens, lower mic sensitivity or increase the physical distance between speaker and mic.

**Old memory causing issues:** `rm ~/.chibi-avatar-memory.json` for a fresh start.
