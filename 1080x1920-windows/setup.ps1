# ─── Chibi-LLM Windows Setup ─────────────────────────────────────────────────
# Run in PowerShell: .\setup.ps1
# Or right-click → Run with PowerShell
# ─────────────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  🐱 Setting up Chibi-LLM for Windows..." -ForegroundColor Cyan
Write-Host ""

# ── Check Python ─────────────────────────────────────────────────────────────
Write-Host "🔍 Checking Python..." -ForegroundColor Yellow
try {
    $pyVersion = python --version 2>&1
    Write-Host "  ✅ $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "  ❌ Python not found!" -ForegroundColor Red
    Write-Host "  Download from https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "  Make sure to check 'Add Python to PATH' during install" -ForegroundColor Yellow
    exit 1
}

# ── Install Python packages ──────────────────────────────────────────────────
Write-Host ""
Write-Host "📦 Installing Python packages..." -ForegroundColor Yellow

$packages = @(
    "pygame",
    "requests",
    "yfinance",
    "piper-tts",
    "faster-whisper",
    "pyaudio",
    "opencv-python"
)

foreach ($pkg in $packages) {
    Write-Host "  Installing $pkg..." -NoNewline
    $result = pip install $pkg --quiet 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host " ✅" -ForegroundColor Green
    } else {
        Write-Host " ⚠️ (may need manual install)" -ForegroundColor Yellow
        # PyAudio often fails — give specific help
        if ($pkg -eq "pyaudio") {
            Write-Host "    PyAudio tip: pip install pipwin && pipwin install pyaudio" -ForegroundColor DarkYellow
            Write-Host "    Or download .whl from https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio" -ForegroundColor DarkYellow
        }
    }
}

# ── Install sox (optional, for pitch shifting) ───────────────────────────────
Write-Host ""
Write-Host "🎵 Checking sox (optional, for cute voice pitch)..." -ForegroundColor Yellow
$soxPath = Get-Command sox -ErrorAction SilentlyContinue
if ($soxPath) {
    Write-Host "  ✅ sox found at $($soxPath.Source)" -ForegroundColor Green
} else {
    Write-Host "  ⚠️ sox not found (voice will work without pitch shift)" -ForegroundColor Yellow
    Write-Host "  Optional: Install from https://sourceforge.net/projects/sox/" -ForegroundColor DarkYellow
    Write-Host "  Then add sox to your PATH" -ForegroundColor DarkYellow
}

# ── Download Piper voice model ───────────────────────────────────────────────
Write-Host ""
Write-Host "🎤 Setting up Chibi's voice..." -ForegroundColor Yellow

$voiceDir = "$env:USERPROFILE\.local\share\piper-voices"
$voiceName = "en_GB-cori-medium"
$baseUrl = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/cori/medium"

if (!(Test-Path $voiceDir)) {
    New-Item -ItemType Directory -Path $voiceDir -Force | Out-Null
}

$onnxFile = "$voiceDir\$voiceName.onnx"
$jsonFile = "$voiceDir\$voiceName.onnx.json"

if (!(Test-Path $onnxFile)) {
    Write-Host "  Downloading $voiceName.onnx (~50MB)..." -ForegroundColor DarkYellow
    try {
        Invoke-WebRequest -Uri "$baseUrl/$voiceName.onnx" -OutFile $onnxFile -UseBasicParsing
        Write-Host "  ✅ Model downloaded" -ForegroundColor Green
    } catch {
        Write-Host "  ❌ Download failed: $_" -ForegroundColor Red
    }
} else {
    Write-Host "  ✅ Voice model already exists" -ForegroundColor Green
}

if (!(Test-Path $jsonFile)) {
    Write-Host "  Downloading config..." -ForegroundColor DarkYellow
    try {
        Invoke-WebRequest -Uri "$baseUrl/$voiceName.onnx.json" -OutFile $jsonFile -UseBasicParsing
        Write-Host "  ✅ Config downloaded" -ForegroundColor Green
    } catch {
        Write-Host "  ❌ Download failed: $_" -ForegroundColor Red
    }
} else {
    Write-Host "  ✅ Voice config already exists" -ForegroundColor Green
}

# ── Check/Setup Ollama ───────────────────────────────────────────────────────
Write-Host ""
Write-Host "🤖 Checking Ollama..." -ForegroundColor Yellow
$ollamaPath = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollamaPath) {
    Write-Host "  ✅ Ollama found" -ForegroundColor Green

    Write-Host "  Pulling mistral (chat model)..." -ForegroundColor DarkYellow
    ollama pull mistral 2>&1 | Out-Null

    Write-Host "  Pulling moondream (vision model)..." -ForegroundColor DarkYellow
    ollama pull moondream 2>&1 | Out-Null

    Write-Host "  ✅ Models ready" -ForegroundColor Green
} else {
    Write-Host "  ⚠️ Ollama not found" -ForegroundColor Yellow
    Write-Host "  Download from https://ollama.com/download" -ForegroundColor DarkYellow
    Write-Host "  After installing, run:" -ForegroundColor DarkYellow
    Write-Host '    $env:OLLAMA_HOST="0.0.0.0"; ollama serve' -ForegroundColor White
    Write-Host "    ollama pull mistral" -ForegroundColor White
    Write-Host "    ollama pull moondream" -ForegroundColor White
}

# ── Update config for Windows paths ──────────────────────────────────────────
Write-Host ""
Write-Host "⚙️ Checking config..." -ForegroundColor Yellow

$configFile = Join-Path $PSScriptRoot "config.py"
if (Test-Path $configFile) {
    # Update voice path to Windows format
    $content = Get-Content $configFile -Raw

    # Set host to localhost since we're running everything on this machine
    if ($content -match 'llm_host.*"192\.168') {
        Write-Host "  💡 Config has a LAN IP for llm_host." -ForegroundColor DarkYellow
        Write-Host "  Since you're running on Windows (same machine as Ollama)," -ForegroundColor DarkYellow
        Write-Host "  you may want to change llm_host to '127.0.0.1' in config.py" -ForegroundColor DarkYellow
    }

    Write-Host "  ✅ Config exists" -ForegroundColor Green
} else {
    Write-Host "  ⚠️ config.py not found in script directory" -ForegroundColor Yellow
}

# ── Verify Installation ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "🔍 Verifying installation..." -ForegroundColor Yellow

$modules = @("pygame", "piper", "faster_whisper", "cv2", "yfinance", "requests")
$labels  = @("pygame", "piper-tts", "faster-whisper", "opencv", "yfinance", "requests")

for ($i = 0; $i -lt $modules.Count; $i++) {
    Write-Host "  $($labels[$i]): " -NoNewline
    $mod = $modules[$i]
    $out = python -c "import $mod; print('ok')" 2>&1
    if ($out -match "ok") {
        Write-Host "✅" -ForegroundColor Green
    } else {
        Write-Host "❌" -ForegroundColor Red
    }
}

# Voice model check
Write-Host "  voice model: " -NoNewline
if (Test-Path $onnxFile) {
    $sizeMB = [math]::Round((Get-Item $onnxFile).Length / 1MB, 1)
    Write-Host "✅ $voiceName (${sizeMB}MB)" -ForegroundColor Green
} else {
    Write-Host "❌" -ForegroundColor Red
}

# ── Done ─────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "─────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "  🐱 Chibi-LLM setup complete!" -ForegroundColor Cyan
Write-Host ""
Write-Host "  To run:" -ForegroundColor White
Write-Host "    1. Start Ollama (if not running):" -ForegroundColor Gray
Write-Host '       $env:OLLAMA_HOST="0.0.0.0"; ollama serve' -ForegroundColor White
Write-Host ""
Write-Host "    2. Launch Chibi:" -ForegroundColor Gray
Write-Host "       python main.py" -ForegroundColor White
Write-Host ""
Write-Host "  💡 Tips:" -ForegroundColor Yellow
Write-Host "    - Edit config.py to set llm_host to '127.0.0.1' for local" -ForegroundColor Gray
Write-Host "    - Or keep the LAN IP if running Ollama on another PC" -ForegroundColor Gray
Write-Host "    - Press ESC to quit, F1 to toggle mic" -ForegroundColor Gray
Write-Host "    - If no mic/speaker, Chibi still works via text input" -ForegroundColor Gray
Write-Host "─────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""
