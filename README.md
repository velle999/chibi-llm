# Chibi-LLM 🐱

A kawaii AI companion that lives on your Raspberry Pi 4. Chibi is a voice-interactive chibi avatar with cat ears, cyberpunk aesthetics, weather awareness, market tracking, webcam vision, persistent memory, and a natural language alarm clock.

**Architecture:** Pi 4 handles display, voice I/O, and webcam. Your PC runs the LLM via Ollama.

## Features

- **Kawaii chibi avatar** — procedurally drawn with Pygame, cat ears, star-pupil eyes, floating hearts/sparkles, expressive animations across 8 states
- **Voice conversation** — Whisper STT + Piper TTS with a cute pitched-up British voice; responses are spoken sentence-by-sentence as they stream from the LLM
- **Wake word** — say **"computer"** to get Chibi's attention (Whisper-tiny can't reliably hear "Chibi"; a custom openWakeWord model can bring the real name back — see `oww_enabled` in config). After any exchange a short conversation window stays open so follow-ups don't need the wake word
- **Soul system** — persistent mood and relationship arc (`~/.chibi-soul.json`): milestones and chat streaks, emotional mirroring, topic callbacks, and spontaneous impulses (morning greetings, storm excitement, "you've been in that app for 2 hours"). Optional extras: system monitoring (psutil), screen awareness (off by default), and calendar reminders via an ICS URL
- **Persistent memory** — remembers your name, preferences, and past conversations across restarts
- **Weather awareness** — live weather with reactive background (rain, snow, lightning effects)
- **Market dashboard** — scrolling stock/crypto ticker, Fear & Greed index
- **Webcam vision** — PS3 Eye camera for scene awareness, on-demand "what do you see"
- **Natural language alarms** — "wake me up at 7am", repeating voice wake-up until dismissed
- **Cyberpunk HUD** — clock, weather panel, scrolling ticker, camera PiP, neon everything
- **Ollama & llama.cpp** — works with either backend on your PC
- **Thoth mode** — a second AI aspect within Chibi's soul system, invoked for deep symbolic analysis, dream journaling, and cross-tradition pattern recognition

### Thoth Mode

Thoth is Chibi's second soul aspect — a quieter, more oracular presence that surfaces when you need something other than conversation. Where Chibi is warm and reactive, Thoth is contemplative and archetypal. Both run within the same soul system; Thoth is not a separate process but a distinct behavioral and interpretive mode Chibi shifts into on request.

#### Activation

Enter Thoth by voice or keyboard:

- *"Horus mode"* / *"enter horus mode"* / *"Thoth"* / *"I had a dream"* / *"open the journal"*
- Any short utterance ending in "mode" also works — Whisper-tiny mangles the spoken name "Horus" (horse/chorus/forest...), so the mode suffix is the reliable trigger
- Thoth auto-activates during the threshold hours (5–8am by default, `horus_threshold_start/end`) — the veil-thin window right after waking

The scene shifts to gold-on-indigo with a faint Eye of Horus watermark. Exit with a short *"exit"*, *"done"*, *"wake up"*, *"chibi"*, or *"chibi mode"* (exit only matches short utterances, so saying "exit" inside a recounted dream won't close the journal).

#### Dream & Vision Journal

Dream entries are stored in `~/.chibi-avatar-memory.json` alongside long-term memory — timestamped, append-only, never trimmed. Press **F2** to browse the journal on-screen (arrow keys to navigate, Enter to read an entry). With `dream_sync_enabled`, the journal union-merges with a peer chibi instance over the LAN, so both machines converge on the same history.

#### Cross-Tradition Symbolic Pattern Engine

At the core of Thoth mode is a symbolic lookup and synthesis layer that maps extracted imagery to a unified schema spanning:

| Tradition | Coverage |
|-----------|----------|
| Egyptian / Kemetic | Neteru, Duat geography, cosmological archetypes |
| Hermetic / Alchemical | Seven principles, elemental operators, solve et coagula |
| Kabbalistic | Sephiroth, paths, Qliphothic correspondences |
| Gnostic | Archons, Pleroma, light/dross distinction |
| Jungian | Shadow, anima/animus, individuation stages |

When a symbol appears in a journal entry or is submitted directly, Thoth returns its correspondences across whichever traditions are relevant, notes any tension or convergence between them, and flags recurrence if the symbol has appeared in prior entries. The intent is synthesis, not encyclopedic lookup — Thoth is looking for *pattern*, not just definition.

#### Architecture

Thoth is a behavioral aspect on the same Ollama backend — a system prompt overlay plus grounding data, no second model required. Two layers feed the scribe:

```
chibi-llm/
├── thoth.py             # Correspondence lexicon — symbols in the account
│                        #   mapped across the five traditions (thoth_lexicon.json)
├── thoth_rag.py         # Primary-text RAG — embeds public-domain sources
│   └── thoth_corpus/    #   (Hermetica, Book of the Dead, Kybalion, ...) via
│                        #   nomic-embed-text on the same Ollama server
```

Build the RAG index once with `ollama pull nomic-embed-text && python thoth_rag.py build`; everything degrades gracefully to the lexicon (and then to the model's own knowledge) when the index or server is unavailable.

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
sudo apt install -y python3-pygame espeak sox libsox-fmt-all alsa-utils

# NOTE: no PortAudio/PyAudio — audio capture streams from arecord/pw-record
# subprocesses (pipewire-jack can segfault the process via libportaudio).
pip install -r requirements.txt --break-system-packages

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
| F2 | Dream journal viewer (↑/↓ navigate, Enter read, Esc close) |
| Escape | Quit |
| Any key during alarm | Dismiss alarm |

Voice: say **"computer"** (the wake word) to address Chibi, then talk naturally — the conversation window stays open for follow-ups after each exchange. Ambient speech and the TV are ignored while the window is closed.

## Project Structure

```
chibi-llm/
├── main.py              # App core, state machine, event loop, draw
├── config.py            # All settings in one place (+ config.local.py overrides)
├── sprite_renderer.py   # Kawaii chibi character (procedural)
├── llm_client.py        # Ollama/llama.cpp streaming client + health check
├── voice_input.py       # Whisper STT (arecord/pw-record capture, optional openWakeWord)
├── voice_output.py      # Piper TTS with pitch shifting
├── soul.py              # Inner life: mood, milestones, impulses, system/calendar awareness
├── data_feeds.py        # Weather + market + news fetchers
├── hud_overlay.py       # Weather panel, scrolling ticker, mini panel
├── memory.py            # Persistent long-term memory + dream journal storage
├── thoth.py             # Thoth correspondence lexicon
├── thoth_rag.py         # Thoth primary-text retrieval (build + query)
├── dream_sync.py        # LAN dream-journal sync between chibi instances
├── vision.py            # PS3 Eye webcam + multimodal LLM (motion-gated awareness)
├── alarm.py             # Natural language alarms (one-shot + repeating)
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

Set alarms naturally: *"wake me up at 7am"*, *"set alarm for 6:30"*, *"alarm in 30 minutes"*, *"set a timer for 20 minutes"*. Repeating alarms work too: *"wake me at 7 every weekday"*, *"alarm at 9 every saturday"*. Dismiss with any keypress or voice. Say *"snooze"* for 5 more minutes.

### Soul
| Setting | Default | Description |
|---------|---------|-------------|
| `soul_enabled` | `True` | Mood, milestones, spontaneous impulses |
| `impulse_min_interval` | `300` | Min seconds between unprompted remarks |
| `screen_awareness_enabled` | `False` | Screenshot → vision model (opt-in) |
| `calendar_ics_url` | `""` | ICS URL for event awareness + reminders |

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

---

## License

Copyright © 2026 Velle Sinclair.

chibi is free software: you can redistribute it and/or modify it under the terms
of the **GNU General Public License as published by the Free Software Foundation,
either version 2 of the License, or (at your option) any later version**
(`GPL-2.0-or-later`). The full text is in [LICENSE](LICENSE).

It is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
PURPOSE. See the GNU General Public License for more details.

### Third-party components

The SynapseOS `chibi` package vendors chibi's Python dependencies alongside it.
Those are **not** covered by the licence above — they remain under their own
terms (largely MIT and Apache-2.0), and each ships its own licence file in
`pydeps/<package>.dist-info/licenses/`. Piper voice models are a dependency
rather than part of this repository and carry their own terms.
