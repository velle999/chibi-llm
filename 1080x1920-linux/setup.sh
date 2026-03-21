#!/usr/bin/env bash
# ─── Chibi-LLM Arch Linux Setup ─────────────────────────────────────────────
# Run: chmod +x setup.sh && ./setup.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

echo ""
echo "  🐱 Setting up Chibi-LLM for Arch Linux..."
echo ""

# ── Check Python ─────────────────────────────────────────────────────────────
echo "🔍 Checking Python..."
if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 --version)
    echo "  ✅ $PY_VERSION"
else
    echo "  ❌ Python not found!"
    echo "  sudo pacman -S python"
    exit 1
fi

# ── Check pip ────────────────────────────────────────────────────────────────
echo "🔍 Checking pip..."
if command -v pip &>/dev/null || python3 -m pip --version &>/dev/null 2>&1; then
    echo "  ✅ pip available"
else
    echo "  ❌ pip not found!"
    echo "  sudo pacman -S python-pip"
    exit 1
fi

# ── System dependencies via pacman ───────────────────────────────────────────
echo ""
echo "📦 Installing system dependencies..."

PACMAN_PKGS=(
    "python-pygame"
    "python-numpy"
    "python-requests"
    "opencv"
    "python-opencv"
    "portaudio"
    "sox"
    "espeak-ng"
)

for pkg in "${PACMAN_PKGS[@]}"; do
    if pacman -Qi "$pkg" &>/dev/null; then
        echo "  ✅ $pkg (installed)"
    else
        echo "  Installing $pkg..."
        sudo pacman -S --noconfirm "$pkg" 2>/dev/null && echo "  ✅ $pkg" || echo "  ⚠️  $pkg (may need manual install)"
    fi
done

# ── Screenshot tools (for screen awareness) ──────────────────────────────────
echo ""
echo "📸 Checking screenshot tools..."

# Check for grim (Wayland) or scrot/maim (X11)
if [ "$XDG_SESSION_TYPE" = "wayland" ]; then
    if command -v grim &>/dev/null; then
        echo "  ✅ grim (Wayland screenshot)"
    else
        echo "  Installing grim for Wayland screenshots..."
        sudo pacman -S --noconfirm grim 2>/dev/null || echo "  ⚠️  Install grim manually: sudo pacman -S grim"
    fi
else
    # X11 — check for scrot or maim
    if command -v scrot &>/dev/null; then
        echo "  ✅ scrot (X11 screenshot)"
    elif command -v maim &>/dev/null; then
        echo "  ✅ maim (X11 screenshot)"
    else
        echo "  Installing scrot for X11 screenshots..."
        sudo pacman -S --noconfirm scrot 2>/dev/null || echo "  ⚠️  Install scrot: sudo pacman -S scrot"
    fi
fi

# Active window detection
if command -v xdotool &>/dev/null; then
    echo "  ✅ xdotool (active window detection)"
elif [ "$XDG_SESSION_TYPE" = "wayland" ]; then
    echo "  ℹ️  Wayland: active window detection uses swaymsg/hyprctl"
else
    echo "  Installing xdotool..."
    sudo pacman -S --noconfirm xdotool 2>/dev/null || echo "  ⚠️  Install xdotool: sudo pacman -S xdotool"
fi

# ── Install Python packages via pip ──────────────────────────────────────────
echo ""
echo "📦 Installing Python packages..."

PIP_PKGS=(
    "piper-tts"
    "faster-whisper"
    "sounddevice"
    "yfinance"
    "Pillow"
    "psutil"
)

for pkg in "${PIP_PKGS[@]}"; do
    echo -n "  $pkg..."
    if pip install --user "$pkg" --quiet 2>/dev/null; then
        echo " ✅"
    else
        echo " ⚠️  (may need manual install)"
    fi
done

# ── Install sox (for pitch shifting) ─────────────────────────────────────────
echo ""
echo "🎵 Checking sox..."
if command -v sox &>/dev/null; then
    echo "  ✅ sox found"
else
    echo "  ⚠️  sox not found (voice will work without pitch shift)"
    echo "  Install: sudo pacman -S sox"
fi

# ── Download Piper voice model ───────────────────────────────────────────────
echo ""
echo "🎤 Setting up Chibi's voice..."

VOICE_DIR="$HOME/.local/share/piper-voices"
VOICE_NAME="en_GB-cori-medium"
BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/cori/medium"

mkdir -p "$VOICE_DIR"

ONNX_FILE="$VOICE_DIR/$VOICE_NAME.onnx"
JSON_FILE="$VOICE_DIR/$VOICE_NAME.onnx.json"

if [ ! -f "$ONNX_FILE" ]; then
    echo "  Downloading $VOICE_NAME.onnx (~50MB)..."
    if curl -L -o "$ONNX_FILE" "$BASE_URL/$VOICE_NAME.onnx" 2>/dev/null || \
       wget -q -O "$ONNX_FILE" "$BASE_URL/$VOICE_NAME.onnx" 2>/dev/null; then
        echo "  ✅ Model downloaded"
    else
        echo "  ❌ Download failed"
    fi
else
    echo "  ✅ Voice model already exists"
fi

if [ ! -f "$JSON_FILE" ]; then
    echo "  Downloading config..."
    if curl -L -o "$JSON_FILE" "$BASE_URL/$VOICE_NAME.onnx.json" 2>/dev/null || \
       wget -q -O "$JSON_FILE" "$BASE_URL/$VOICE_NAME.onnx.json" 2>/dev/null; then
        echo "  ✅ Config downloaded"
    else
        echo "  ❌ Download failed"
    fi
else
    echo "  ✅ Voice config already exists"
fi

# ── Check/Setup Ollama ───────────────────────────────────────────────────────
echo ""
echo "🤖 Checking Ollama..."
if command -v ollama &>/dev/null; then
    echo "  ✅ Ollama found"

    echo "  Pulling mistral (chat model)..."
    ollama pull mistral 2>/dev/null || true

    echo "  Pulling moondream (vision model)..."
    ollama pull moondream 2>/dev/null || true

    echo "  ✅ Models ready"
else
    echo "  ⚠️  Ollama not found"
    echo "  Install from AUR: yay -S ollama"
    echo "  Or download from https://ollama.com/download"
    echo "  After installing, run:"
    echo '    OLLAMA_HOST=0.0.0.0 ollama serve'
    echo "    ollama pull mistral"
    echo "    ollama pull moondream"
fi

# ── Verify Installation ──────────────────────────────────────────────────────
echo ""
echo "🔍 Verifying installation..."

MODULES=("pygame" "piper" "faster_whisper" "cv2" "yfinance" "requests" "sounddevice" "psutil" "PIL")
LABELS=("pygame" "piper-tts" "faster-whisper" "opencv" "yfinance" "requests" "sounddevice" "psutil" "Pillow")

for i in "${!MODULES[@]}"; do
    echo -n "  ${LABELS[$i]}: "
    if python3 -c "import ${MODULES[$i]}" 2>/dev/null; then
        echo "✅"
    else
        echo "❌"
    fi
done

# Voice model check
echo -n "  voice model: "
if [ -f "$ONNX_FILE" ]; then
    SIZE=$(du -m "$ONNX_FILE" | cut -f1)
    echo "✅ $VOICE_NAME (${SIZE}MB)"
else
    echo "❌"
fi

# Screenshot tool check
echo -n "  screenshot tool: "
if command -v grim &>/dev/null; then
    echo "✅ grim (Wayland)"
elif command -v scrot &>/dev/null; then
    echo "✅ scrot (X11)"
elif command -v maim &>/dev/null; then
    echo "✅ maim (X11)"
else
    echo "❌ (screen awareness will be disabled)"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "─────────────────────────────────────────────────"
echo "  🐱 Chibi-LLM setup complete!"
echo ""
echo "  To run:"
echo "    1. Start Ollama (if not running):"
echo '       OLLAMA_HOST=0.0.0.0 ollama serve'
echo ""
echo "    2. Launch Chibi:"
echo "       python3 main.py"
echo ""
echo "  💡 Tips:"
echo "    - Edit config.py to change llm_host if Ollama is on another machine"
echo "    - Press ESC to quit, F1 to toggle mic"
echo "    - If no mic/speaker, Chibi still works via text input"
echo "    - For Wayland: install grim for screen awareness"
echo "    - For X11: install scrot or maim for screen awareness"
echo "─────────────────────────────────────────────────"
echo ""
