# Chibi-LLM — Linux Edition (Arch)

A cyberpunk AI companion with a procedurally animated chibi avatar, powered by a local LLM via Ollama. Features voice I/O, webcam vision, natural language alarms, live weather and market data, and a fully animated neon background — all running on your desktop at 1080x1920 portrait.

```
┌─────────────────────────────────────┐
│        Your Linux Machine           │
│                                     │
│   Ollama (LLM + Vision models)      │
│            ▲                        │
│            │ HTTP localhost          │
│            ▼                        │
│   Chibi-LLM (Pygame window)        │
│   ┌───────────────────────────┐     │
│   │  Animated background      │     │
│   │  Parallax stars + geometry│     │
│   │                           │     │
│   │      ∧＿∧                 │     │
│   │     (◕ᴗ◕)  ← Chibi       │     │
│   │      /つ♡                 │     │
│   │                           │     │
│   │  [Chat bubble]            │     │
│   │  [Weather] [Market ticker]│     │
│   │  [> Type here...]        │     │
│   └───────────────────────────┘     │
└─────────────────────────────────────┘
```

## Features

- **Procedural chibi character** — fully scalable, drawn with Pygame primitives (no sprite sheets)
- **8 avatar states** — idle, listening, thinking, speaking, happy, confused, sleeping, alarm
- **Lifelike animations** — breathing, natural blinking, wake-up particle burst, pulsing glow
- **Cyberpunk HUD** — weather panel, scrolling stock/crypto ticker, neon-styled UI
- **Animated background** — parallax star field, floating geometry, scrolling grid, light beams
- **Voice input** — Whisper speech-to-text via sounddevice
- **Voice output** — Piper TTS with pitch shifting for a cute voice
- **Webcam vision** — PS3 Eye or any USB camera, multimodal scene awareness via Ollama
- **Natural language alarms** — "wake me up at 7am", snooze, dismiss by voice or keypress
- **Persistent memory** — remembers facts about you across sessions
- **Weather-reactive** — rain, snow, lightning effects based on real weather
- **Market awareness** — LLM can reference live stock/crypto data in conversation
- **Screen awareness** — periodic screenshots via grim (Wayland) or scrot/maim (X11)
- **Active window detection** — hyprctl (Hyprland), swaymsg (Sway), xdotool (X11)

## Quick Start

### 1. Install Ollama

From AUR:
```bash
yay -S ollama
```

Or download from [ollama.com](https://ollama.com/download).

Pull the models:
```bash
ollama pull mistral
ollama pull moondream
```

Start with network access:
```bash
OLLAMA_HOST=0.0.0.0 ollama serve
```

### 2. Run Setup

```bash
chmod +x setup.sh
./setup.sh
```

This installs system packages, Python dependencies, downloads the Piper voice model, and verifies everything.

### 3. Configure

Edit `config.py`:

```python
llm_host = "127.0.0.1"    # localhost since Ollama runs on same machine
llm_port = 11434           # Ollama default
llm_model = "mistral"      # Chat model
weather_city = "Your City" # For weather display
```

### 4. Launch

```bash
python3 main.py
```

## Controls

| Key | Action |
|-----|--------|
| Type + Enter | Send text message |
| F1 | Toggle microphone on/off |
| Escape | Quit |
| Any key | Dismiss alarm |

## Voice Commands

| Say... | Does... |
|--------|---------|
| *anything* | Chibi responds with voice + animation |
| "what do you see" | Captures webcam frame and describes it |
| "set alarm for 7am" | Sets a wake-up alarm |
| "wake me up in 30 minutes" | Relative alarm |
| "list alarms" | Shows active alarms |
| "cancel alarm" | Removes an alarm |
| "snooze" / "5 more minutes" | Snoozes a ringing alarm |

## Avatar States

| State | Trigger | Animation |
|-------|---------|-----------|
| Idle | Default | Gentle bob, breathing, blinking, cat mouth |
| Listening | Mic detects speech | Pulsing rings, perked ears |
| Thinking | Message sent | Floating star dots, looking around |
| Speaking | LLM response + TTS | Mouth animation, subtle particles |
| Happy | Response complete | Bouncy, sparkle eyes, arm wave |
| Confused | Connection error | Wavy mouth, spiral eyes, head tilt |
| Sleeping | 2 min inactivity | Closed eyes, Zzz, deep breathing |
| Alarm | Alarm triggers | Rapid bounce, yelling mouth, amber pulse |

## Project Structure

```
chibi-llm/
├── main.py              # Main app, state machine, UI, animated background
├── config.py            # All settings (display, LLM, voice, weather, etc.)
├── llm_client.py        # Ollama/llama.cpp streaming client
├── sprite_renderer.py   # Procedural chibi drawing (fully scalable)
├── voice_input.py       # Whisper STT via sounddevice
├── voice_output.py      # Piper TTS with pitch shifting
├── vision.py            # Webcam capture + multimodal LLM
├── alarm.py             # Natural language alarm system
├── data_feeds.py        # Weather + market data fetchers
├── hud_overlay.py       # Weather panel + market ticker rendering
├── memory.py            # Persistent conversation memory
├── soul.py              # Mood, system monitor, screen awareness, calendar
├── setup.sh             # Arch Linux setup script
└── README.md
```

## Linux-Specific Notes

### Screen Awareness

Screen capture uses native tools instead of PIL's ImageGrab:

- **Wayland (Hyprland/Sway)**: Uses `grim` — `sudo pacman -S grim`
- **X11**: Uses `scrot` or `maim` — `sudo pacman -S scrot`

### Active Window Detection

- **Hyprland**: Uses `hyprctl activewindow -j`
- **Sway**: Uses `swaymsg -t get_tree`
- **X11**: Uses `xdotool getactivewindow getwindowname` — `sudo pacman -S xdotool`

### Audio

- TTS playback uses `aplay` (ALSA) by default, falls back to pygame.mixer
- Voice input uses `sounddevice` (PortAudio) — `sudo pacman -S portaudio`
- Pitch shifting uses `sox` — `sudo pacman -S sox`

### Dependencies (pacman)

```bash
sudo pacman -S python python-pip python-pygame python-numpy python-requests \
  opencv python-opencv portaudio sox espeak-ng
```

### Dependencies (pip)

```bash
pip install --user piper-tts faster-whisper sounddevice yfinance Pillow psutil
```

## Troubleshooting

**Chibi can't reach Ollama**
Make sure Ollama is running: `OLLAMA_HOST=0.0.0.0 ollama serve`. Config defaults to `127.0.0.1`.

**No voice input / mic not working**
Check `arecord -l` to list capture devices. Make sure PulseAudio/PipeWire is running. If using PipeWire, ensure `pipewire-alsa` is installed.

**Piper TTS not found**
Run `setup.sh` or manually: `pip install --user piper-tts`. Voice model downloads to `~/.local/share/piper-voices/`.

**Sox not found (pitch shifting)**
Voice works without sox — just no pitch shift. Install: `sudo pacman -S sox`.

**Screen awareness not working**
Install the appropriate screenshot tool for your session type. Check `echo $XDG_SESSION_TYPE` to see if you're on wayland or x11.

**Camera not working**
Check `ls /dev/video*` for available devices. Set `vision_enabled = False` in config.py to disable. Try changing `camera_device` to `1` if you have multiple cameras.

**Window is too big / wrong resolution**
Change `window_width` and `window_height` in config.py. Set `fullscreen = False` for windowed mode.

**Memory reset**
Delete `~/.chibi-avatar-memory.json` to clear Chibi's memories.
