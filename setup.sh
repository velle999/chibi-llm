#!/bin/bash
# ─── Chibi Avatar Setup Script ──────────────────────────────────────────────
# Run this on your Raspberry Pi to install everything Chibi needs.
# Usage: bash setup.sh

set -e
echo "🐱 Setting up Chibi Avatar..."
echo ""

# ── System packages ──────────────────────────────────────────────────────────
echo "📦 Installing system packages..."
sudo apt update
sudo apt install -y \
    python3-pygame \
    portaudio19-dev \
    espeak \
    sox \
    libsox-fmt-all \
    aplay

# ── Python packages ──────────────────────────────────────────────────────────
echo ""
echo "🐍 Installing Python packages..."
pip install --break-system-packages \
    piper-tts \
    faster-whisper \
    pyaudio \
    yfinance \
    requests \
    opencv-python-headless

# ── Download Piper voice model ───────────────────────────────────────────────
VOICE_DIR="$HOME/.local/share/piper-voices"
VOICE_NAME="en_GB-cori-medium"
VOICE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/cori/medium"

mkdir -p "$VOICE_DIR"

if [ ! -f "$VOICE_DIR/$VOICE_NAME.onnx" ]; then
    echo ""
    echo "🎤 Downloading Chibi's voice (en_GB-cori-medium)..."
    wget -q --show-progress \
        "$VOICE_URL/$VOICE_NAME.onnx" \
        -O "$VOICE_DIR/$VOICE_NAME.onnx"
    wget -q --show-progress \
        "$VOICE_URL/$VOICE_NAME.onnx.json" \
        -O "$VOICE_DIR/$VOICE_NAME.onnx.json"
    echo "✅ Voice downloaded!"
else
    echo "✅ Voice model already exists"
fi

# ── Alternative cute voices you can try ──────────────────────────────────────
# Uncomment any of these to download additional voices:
#
# Amy (clear US female):
# wget "$HF/en/en_US/amy/medium/en_US-amy-medium.onnx" -O "$VOICE_DIR/en_US-amy-medium.onnx"
# wget "$HF/en/en_US/amy/medium/en_US-amy-medium.onnx.json" -O "$VOICE_DIR/en_US-amy-medium.onnx.json"
#
# Lessac (warm US female):
# wget "$HF/en/en_US/lessac/medium/en_US-lessac-medium.onnx" -O "$VOICE_DIR/en_US-lessac-medium.onnx"
# wget "$HF/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json" -O "$VOICE_DIR/en_US-lessac-medium.onnx.json"

# ── Verify ───────────────────────────────────────────────────────────────────
echo ""
echo "🔍 Checking installation..."

echo -n "  pygame: "
python3 -c "import pygame; print('✅')" 2>/dev/null || echo "❌"

echo -n "  piper-tts: "
python3 -c "import piper; print('✅')" 2>/dev/null || (piper --version > /dev/null 2>&1 && echo "✅ (cli)") || echo "❌"

echo -n "  faster-whisper: "
python3 -c "import faster_whisper; print('✅')" 2>/dev/null || echo "❌"

echo -n "  opencv: "
python3 -c "import cv2; print('✅')" 2>/dev/null || echo "❌"

echo -n "  sox: "
sox --version > /dev/null 2>&1 && echo "✅" || echo "❌ (optional, for pitch shift)"

echo -n "  voice model: "
[ -f "$VOICE_DIR/$VOICE_NAME.onnx" ] && echo "✅ $VOICE_NAME" || echo "❌"

echo ""
echo "─────────────────────────────────────────"
echo "🐱 Chibi is ready! Run: python3 main.py"
echo ""
echo "💡 Tips:"
echo "   - Edit config.py to set your PC's IP (currently 192.168.40.153)"
echo "   - On your PC: \$env:OLLAMA_HOST='0.0.0.0'; ollama serve"
echo "   - For vision: ollama pull moondream"
echo "   - Delete old memory: rm ~/.chibi-avatar-memory.json"
echo "─────────────────────────────────────────"
