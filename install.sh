#!/usr/bin/env bash
# ============================================================
# install.sh - Instala dependencias y el comando global `grabar`
# Soporta macOS (Homebrew) y Ubuntu/Debian (apt)
# Uso: ./install.sh
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OS="$(uname -s)"
BIN_DIR="${HOME}/.local/bin"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

echo ""
echo "  === Instalador de grabar (${OS}) ==="
echo ""

# ------------------------------------------------------------
# 1. Dependencias del sistema
# ------------------------------------------------------------
PYTHON_FOR_PIPX=""

if [[ "$OS" == "Darwin" ]]; then
    if ! command -v brew &>/dev/null; then
        error "Falta Homebrew. Instalalo primero desde https://brew.sh y volvé a correr ./install.sh"
        exit 1
    fi
    info "Instalando ffmpeg, pipx y python@3.12 con Homebrew..."
    brew install ffmpeg pipx python@3.12
    PYTHON_FOR_PIPX="$(brew --prefix python@3.12)/bin/python3.12"

    info "Instalando BlackHole 2ch (dispositivo virtual para capturar el audio del sistema)..."
    if brew list --cask blackhole-2ch &>/dev/null; then
        ok "BlackHole ya estaba instalado"
    else
        brew install --cask blackhole-2ch || warn "No se pudo instalar BlackHole automáticamente. Bajalo de https://existential.audio/blackhole/"
    fi

elif [[ "$OS" == "Linux" ]]; then
    if command -v apt-get &>/dev/null; then
        info "Instalando ffmpeg, pulseaudio-utils, pipx y python3 con apt (pide sudo)..."
        sudo apt-get update -qq
        sudo apt-get install -y ffmpeg pulseaudio-utils pipx python3
    else
        warn "Distro sin apt: instalá a mano ffmpeg, pulseaudio-utils (pactl), python3 y pipx."
    fi
else
    error "Sistema no soportado: $OS"
    exit 1
fi

# ------------------------------------------------------------
# 2. WhisperX (transcripción) vía pipx
# ------------------------------------------------------------
if command -v whisperx &>/dev/null; then
    ok "whisperx ya está instalado"
else
    info "Instalando whisperx con pipx (descarga torch, puede tardar varios minutos)..."
    if [[ -n "$PYTHON_FOR_PIPX" && -x "$PYTHON_FOR_PIPX" ]]; then
        pipx install --python "$PYTHON_FOR_PIPX" whisperx
    else
        pipx install whisperx
    fi
fi

# ------------------------------------------------------------
# 3. Comandos globales: grabar y mp4towav
# ------------------------------------------------------------
mkdir -p "$BIN_DIR"
chmod +x "$SCRIPT_DIR/grabar.sh" "$SCRIPT_DIR/mp4towav.sh"
ln -sf "$SCRIPT_DIR/grabar.sh"   "$BIN_DIR/grabar"
ln -sf "$SCRIPT_DIR/mp4towav.sh" "$BIN_DIR/mp4towav"
ok "Comandos creados: $BIN_DIR/grabar y $BIN_DIR/mp4towav"

# Asegura ~/.local/bin en el PATH (pipx lo agrega al rc del shell)
pipx ensurepath >/dev/null 2>&1 || true
if ! echo ":$PATH:" | grep -q ":$BIN_DIR:"; then
    warn "$BIN_DIR todavía no está en tu PATH. Cerrá y abrí la terminal (o ejecutá: source ~/.zshrc)"
fi

# ------------------------------------------------------------
# 4. Pasos manuales
# ------------------------------------------------------------
echo ""
echo -e "${GREEN}=== Instalación lista. Faltan estos pasos manuales ===${NC}"
echo ""
if [[ "$OS" == "Darwin" ]]; then
    cat <<'MAC'
  A) Configurar BlackHole para capturar el audio del sistema (una sola vez):
     1. Abrí "Configuración de Audio MIDI" (Spotlight → Audio MIDI Setup).
     2. Botón "+" abajo a la izquierda → "Crear dispositivo de salida múltiple".
     3. Marcá tus parlantes/auriculares Y "BlackHole 2ch". Dejá "Drift Correction" en BlackHole.
     4. Click derecho sobre el nuevo dispositivo → "Usar este dispositivo para la salida de sonido".
     Resultado: vos seguís escuchando normal y BlackHole recibe una copia que graba el script.
     (Opcional) En Zoom/Meet/Slack dejá la salida en "Sistema" o en el dispositivo múltiple.

  B) Permiso de micrófono: la primera vez que grabes, macOS va a pedir permiso para
     Terminal (o iTerm). Aceptalo. Si no aparece: Ajustes del Sistema → Privacidad y
     seguridad → Micrófono → activá tu terminal.

MAC
fi
cat <<'HF'
  C) (Opcional) Identificar quién habla (diarization) necesita un token de Hugging Face:
     1. Creá cuenta en https://huggingface.co/join
     2. Aceptá las licencias de estos modelos (con la sesión iniciada):
        https://huggingface.co/pyannote/speaker-diarization-3.1
        https://huggingface.co/pyannote/segmentation-3.0
     3. Generá un token (Read) en https://huggingface.co/settings/tokens
     4. Guardalo en tu shell (NO lo pegues en chats ni lo subas a git):
          echo 'export HF_TOKEN="hf_xxx"' >> ~/.zshrc      # macOS
          echo 'export HF_TOKEN="hf_xxx"' >> ~/.bashrc     # Linux
        y abrí una terminal nueva.

  Listo. Abrí una terminal nueva y ejecutá:   grabar
HF
