#!/usr/bin/env bash
# ============================================================
# grabar.sh - Graba audio del sistema + micrófono y transcribe
# Funciona en Linux (PipeWire/PulseAudio) y macOS (BlackHole + avfoundation)
# Requiere: ffmpeg, whisperx
#   Linux: pulseaudio-utils (pactl)
#   macOS: BlackHole 2ch configurado como salida (ver README)
# ============================================================

set -euo pipefail

# --- Configuración ---
resolve_path() {
    # readlink -f no existe en macOS < 12.3; python3 sirve de respaldo
    readlink -f "$1" 2>/dev/null || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$1"
}
SCRIPT_DIR="$(cd "$(dirname "$(resolve_path "${BASH_SOURCE[0]}")")" && pwd)"
OUTPUT_DIR="${GRABAR_DIR:-${SCRIPT_DIR}/grabaciones}"
WHISPER_LANG="${GRABAR_LANG:-es}"
DATE_FMT="+%Y-%m-%d_%H-%M-%S"
HF_TOKEN="${HF_TOKEN:-}"            # export HF_TOKEN="hf_..." (solo para identificar hablantes)
OS="$(uname -s)"                    # Linux | Darwin
GRABAR_DEVICE="${GRABAR_DEVICE:-}"  # cpu | cuda  (por defecto: cuda en Linux, cpu en macOS)
GRABAR_MONITOR="${GRABAR_MONITOR:-}" # macOS: nombre del dispositivo que captura el sistema (ej. "BlackHole 2ch")
GRABAR_MIC="${GRABAR_MIC:-}"         # macOS: nombre del micrófono (ej. "MacBook Pro Microphone")
GRABAR_FFMPEG="${GRABAR_FFMPEG:-}"   # ruta a un ffmpeg concreto (por defecto se busca uno que soporte pulse/avfoundation)

# Backend de captura que necesita ffmpeg en este sistema
if [[ "$OS" == "Darwin" ]]; then CAPTURE_BACKEND="avfoundation"; else CAPTURE_BACKEND="pulse"; fi

# Busca un ffmpeg que soporte el backend de captura. Los builds estáticos (johnvansickle,
# conda, pipx) suelen no traer pulse/avfoundation, así que no basta con el primero del PATH.
find_ffmpeg() {
    if [[ -n "$GRABAR_FFMPEG" ]]; then
        echo "$GRABAR_FFMPEG"
        return
    fi
    local candidates=() c
    while IFS= read -r c; do candidates+=("$c"); done < <(which -a ffmpeg 2>/dev/null || true)
    candidates+=(/opt/homebrew/bin/ffmpeg /usr/local/bin/ffmpeg /usr/bin/ffmpeg)
    for c in "${candidates[@]}"; do
        [[ -x "$c" ]] || continue
        if "$c" -hide_banner -devices 2>/dev/null | grep -qw "$CAPTURE_BACKEND"; then
            echo "$c"
            return
        fi
    done
    command -v ffmpeg || true   # sin soporte de captura; check_deps avisará
}
FFMPEG="$(find_ffmpeg)"
FFPROBE="$(dirname "${FFMPEG:-/nonexistent}")/ffprobe"
[[ -x "$FFPROBE" ]] || FFPROBE="$(command -v ffprobe || true)"

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# --- Funciones ---
info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_deps() {
    local missing=()
    local deps=(python3)
    if [[ "$OS" == "Linux" ]]; then
        deps+=(pactl)
    fi
    [[ -n "$FFMPEG" && -x "$FFMPEG" ]] || missing+=(ffmpeg)
    [[ -n "$FFPROBE" && -x "$FFPROBE" ]] || missing+=(ffprobe)
    for cmd in "${deps[@]}"; do
        if ! command -v "$cmd" &>/dev/null; then
            missing+=("$cmd")
        fi
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        error "Faltan dependencias: ${missing[*]}"
        if [[ "$OS" == "Darwin" ]]; then
            echo "  Instalá con: brew install ffmpeg   (o ejecutá ./install.sh)"
        else
            echo "  Instalá con: sudo apt install ffmpeg pulseaudio-utils   (o ejecutá ./install.sh)"
        fi
        exit 1
    fi
    if ! "$FFMPEG" -hide_banner -devices 2>/dev/null | grep -qw "$CAPTURE_BACKEND"; then
        error "El ffmpeg encontrado ($FFMPEG) no soporta captura '$CAPTURE_BACKEND'."
        if [[ "$OS" == "Darwin" ]]; then
            echo "  Instalá el de Homebrew: brew install ffmpeg"
        else
            echo "  Instalá el del sistema: sudo apt install ffmpeg"
        fi
        echo "  O indicá uno: export GRABAR_FFMPEG=/ruta/a/ffmpeg"
        exit 1
    fi
}

check_whisperx() {
    if ! command -v whisperx &>/dev/null; then
        warn "Whisperx no está instalado."
        echo "  Instalá con: pipx install whisperx   (o ejecutá ./install.sh)"
        return 1
    fi
    if [[ "$USE_DIARIZE" == true && -z "$HF_TOKEN" ]]; then
        warn "HF_TOKEN no configurado. Necesario para identificar hablantes."
        echo "  Configurá con: export HF_TOKEN=\"hf_tu_token\"  (ver README)"
        echo -n "  O ingresá tu token de HuggingFace ahora (déjalo en blanco para omitir diarization): "
        read -r HF_TOKEN
        if [[ -z "$HF_TOKEN" ]]; then
            warn "Token no provisto, se desactivará la identificación de hablantes."
            USE_DIARIZE=false
        fi
    fi
    return 0
}

# --- Detección de dispositivos de audio ---

# macOS: imprime "indice|nombre" de cada dispositivo de audio que ve avfoundation
list_avf_audio_devices() {
    "$FFMPEG" -hide_banner -f avfoundation -list_devices true -i "" 2>&1 \
        | sed -n '/AVFoundation audio devices/,$p' \
        | sed -nE 's/^.*\[([0-9]+)\] (.*)$/\1|\2/p' || true
}

get_monitor_source() {
    if [[ "$OS" == "Darwin" ]]; then
        if [[ -n "$GRABAR_MONITOR" ]]; then
            echo "$GRABAR_MONITOR"
            return
        fi
        list_avf_audio_devices | grep -i 'blackhole' | head -1 | cut -d'|' -f2- || true
        return
    fi
    local default_sink
    default_sink=$(pactl get-default-sink 2>/dev/null || true)
    if [[ -n "$default_sink" ]]; then
        echo "${default_sink}.monitor"
    else
        pactl list short sources 2>/dev/null | grep monitor | head -1 | awk '{print $2}' || true
    fi
}

get_mic_source() {
    if [[ "$OS" == "Darwin" ]]; then
        if [[ -n "$GRABAR_MIC" ]]; then
            echo "$GRABAR_MIC"
            return
        fi
        # Primer dispositivo que no sea BlackHole ni un dispositivo virtual agregado
        list_avf_audio_devices | grep -viE 'blackhole|aggregate|agregado|multi-output|salida múltiple' \
            | head -1 | cut -d'|' -f2- || true
        return
    fi
    pactl get-default-source 2>/dev/null || true
}

show_audio_devices() {
    echo ""
    if [[ "$OS" == "Darwin" ]]; then
        info "Dispositivos de audio (avfoundation):"
        list_avf_audio_devices | sed 's/^/    /'
        echo ""
        echo "  Para elegir otro: export GRABAR_MONITOR=\"BlackHole 2ch\"  export GRABAR_MIC=\"Nombre del mic\""
    else
        info "Fuentes de audio (PulseAudio/PipeWire):"
        pactl list short sources | sed 's/^/    /'
    fi
    echo ""
    info "Sistema: $(get_monitor_source)"
    info "Micrófono: $(get_mic_source)"
}

# --- Transcripción ---

select_whisper_mode() {
    local device compute
    if [[ -n "$GRABAR_DEVICE" ]]; then
        device="$GRABAR_DEVICE"
    elif [[ "$OS" == "Darwin" ]]; then
        device="cpu"
    else
        device="cuda"
    fi
    if [[ "$device" == "cuda" ]]; then
        compute="float16"
    else
        compute="int8"
    fi

    echo ""
    echo -e "${BLUE}  Seleccioná el modo de transcripción (WhisperX, device: ${device}):${NC}"
    echo ""
    if [[ "$device" == "cuda" ]]; then
        echo "  1) large-v3 + Speakers   (Mejor calidad, requiere GPU ~8GB VRAM)"
        echo "  2) medium + Speakers     (Buena calidad, requiere GPU ~5GB VRAM)"
        echo "  3) medium sin Speakers   (Si no tenés token o no te importan los hablantes)"
        echo "  4) large-v3 en CPU sin Speakers (Lento, pero funciona sin tarjeta gráfica)"
    else
        echo "  1) large-v3 + Speakers   (Mejor calidad; en CPU tarda ~1x la duración del audio)"
        echo "  2) medium + Speakers     (Buena calidad, más rápido)"
        echo "  3) medium sin Speakers   (El más rápido; no necesita token)"
        echo "  4) large-v3 sin Speakers"
    fi
    echo ""
    echo -n "  Modo [1/2/3/4]: "
    read -r mode_choice

    WHISPER_DEVICE="$device"
    COMPUTE_TYPE="$compute"
    case "$mode_choice" in
        1)
            WHISPER_MODEL="large-v3"
            USE_DIARIZE=true
            ;;
        2)
            WHISPER_MODEL="medium"
            USE_DIARIZE=true
            ;;
        4)
            WHISPER_MODEL="large-v3"
            WHISPER_DEVICE="cpu"
            COMPUTE_TYPE="int8"
            USE_DIARIZE=false
            ;;
        *)
            WHISPER_MODEL="medium"
            USE_DIARIZE=false
            ;;
    esac
    local diar="sin speakers"
    [[ "$USE_DIARIZE" == true ]] && diar="+ speakers"
    info "Usando modelo: ${WHISPER_MODEL} en ${WHISPER_DEVICE} ${diar}"
}

# --- Grabación ---

start_recording() {
    echo ""
    echo -n "  Nombre de la grabación (Enter para usar fecha/hora): "
    read -r custom_name

    local timestamp
    timestamp=$(date "$DATE_FMT")

    if [[ -n "$custom_name" ]]; then
        # Sanitizar nombre: espacios a guiones bajos, mantener solo alfanuméricos
        custom_name=$(echo "$custom_name" | tr ' ' '_' | tr -cd 'A-Za-z0-9_-')
        RECORDING_FILE="${OUTPUT_DIR}/${timestamp}_${custom_name}.mp3"
    else
        RECORDING_FILE="${OUTPUT_DIR}/${timestamp}.mp3"
    fi

    mkdir -p "$OUTPUT_DIR"

    local monitor_src mic_src
    monitor_src=$(get_monitor_source)
    mic_src=$(get_mic_source)

    if [[ -z "$monitor_src" ]]; then
        error "No se encontró fuente de audio del sistema (monitor)"
        if [[ "$OS" == "Darwin" ]]; then
            echo "  En macOS hace falta BlackHole: brew install --cask blackhole-2ch"
            echo "  y configurar un dispositivo de salida múltiple (ver README, sección macOS)."
        fi
        return 1
    fi

    info "Audio del sistema: $monitor_src"
    info "Micrófono: ${mic_src:-no detectado}"
    info "Archivo: $RECORDING_FILE"
    echo ""

    # Entradas de ffmpeg según el sistema operativo
    local in_args=()
    if [[ "$OS" == "Darwin" ]]; then
        in_args=(-thread_queue_size 1024 -f avfoundation -i ":${monitor_src}")
        if [[ -n "$mic_src" ]]; then
            in_args+=(-thread_queue_size 1024 -f avfoundation -i ":${mic_src}")
        fi
    else
        in_args=(-thread_queue_size 1024 -use_wallclock_as_timestamps 1 -f pulse -i "$monitor_src")
        if [[ -n "$mic_src" ]]; then
            in_args+=(-thread_queue_size 1024 -use_wallclock_as_timestamps 1 -f pulse -i "$mic_src")
        fi
    fi

    if [[ -n "$mic_src" ]]; then
        # Mezcla, corrige desfasajes y normaliza volumen a nivel estándar
        "$FFMPEG" -y "${in_args[@]}" \
            -filter_complex "[0:a]aresample=async=1[a0];[1:a]aresample=async=1[a1];[a0][a1]amix=inputs=2:duration=longest[amixed];[amixed]loudnorm=I=-16:TP=-1.5:LRA=11[out]" \
            -map "[out]" \
            -ac 2 -ar 48000 -b:a 192k \
            "$RECORDING_FILE" \
            -loglevel quiet &
    else
        warn "No se detectó micrófono, grabando solo audio del sistema"
        "$FFMPEG" -y "${in_args[@]}" \
            -af "aresample=async=1,loudnorm=I=-16:TP=-1.5:LRA=11" \
            -ac 2 -ar 48000 -b:a 192k \
            "$RECORDING_FILE" \
            -loglevel quiet &
    fi

    FFMPEG_PID=$!
    ok "Grabando... (PID: $FFMPEG_PID)"
}

stop_recording() {
    if [[ -n "${FFMPEG_PID:-}" ]] && kill -0 "$FFMPEG_PID" 2>/dev/null; then
        kill -INT "$FFMPEG_PID" 2>/dev/null
        wait "$FFMPEG_PID" 2>/dev/null || true
        ok "Grabación detenida"

        if [[ -f "$RECORDING_FILE" ]]; then
            local size duration
            size=$(du -h "$RECORDING_FILE" | cut -f1)
            duration=$("$FFPROBE" -v quiet -show_entries format=duration -of csv=p=0 "$RECORDING_FILE" 2>/dev/null | cut -d. -f1)
            ok "Archivo guardado: $RECORDING_FILE ($size, ${duration:-?}s)"
        else
            warn "No se generó el archivo. ¿Terminal tiene permiso de micrófono? (macOS: Ajustes > Privacidad > Micrófono)"
        fi
    else
        warn "No hay grabación activa"
    fi
}

transcribe() {
    local file="${1:-$RECORDING_FILE}"

    if [[ ! -f "$file" ]]; then
        error "Archivo no encontrado: $file"
        return 1
    fi

    select_whisper_mode

    if ! check_whisperx; then
        return 1
    fi

    info "Transcribiendo: $(basename "$file")"
    info "Esto puede tardar unos minutos..."
    echo ""

    local output_dir
    output_dir=$(dirname "$file")

    local cmd=(whisperx "$file" --model "$WHISPER_MODEL" --language "$WHISPER_LANG" --device "$WHISPER_DEVICE" --compute_type "$COMPUTE_TYPE" --output_dir "$output_dir" --output_format json --vad_onset 0.500)

    if [[ "$USE_DIARIZE" == true ]]; then
        cmd+=(--diarize --hf_token "$HF_TOKEN")
    fi

    # Ejecutamos whisperx
    "${cmd[@]}"

    local json_file="${file%.*}.json"
    local md_file="${file%.*}.md"

    if [[ -f "$json_file" ]]; then
        # Procesamos el JSON con Python para generar un Markdown bonito
        python3 - "$json_file" "$md_file" <<'PY' || true
import json, sys

json_file, md_file = sys.argv[1], sys.argv[2]

def format_time(seconds):
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f'{mins:02d}:{secs:02d}'

try:
    with open(json_file) as f:
        data = json.load(f)

    with open(md_file, 'w', encoding='utf-8') as out:
        out.write('# Transcripción de Audio\n\n')

        current_speaker = None
        current_text = []
        start_time = 0.0

        for seg in data.get('segments', []):
            speaker = seg.get('speaker', 'SPEAKER')
            text = seg.get('text', '').strip()
            if not text:
                continue

            if speaker != current_speaker:
                if current_speaker is not None:
                    out.write(f'**[{format_time(start_time)}] {current_speaker}:** {" ".join(current_text)}\n\n')
                current_speaker = speaker
                start_time = seg.get('start', 0.0)
                current_text = [text]
            else:
                current_text.append(text)

        if current_speaker is not None:
            out.write(f'**[{format_time(start_time)}] {current_speaker}:** {" ".join(current_text)}\n\n')

    print(f'\n[OK] Documento Markdown generado: {md_file}')
except Exception as e:
    print(f'Error al generar Markdown: {e}')
PY

        if [[ -f "$md_file" ]]; then
            echo ""
            echo "--- Resumen Transcripción ---"
            head -n 20 "$md_file"
            echo "..."
            echo "--- Fin ---"
        fi
    fi
}

list_recordings() {
    if [[ ! -d "$OUTPUT_DIR" ]]; then
        warn "No hay grabaciones aún"
        return
    fi

    echo ""
    info "Grabaciones en $OUTPUT_DIR:"
    echo ""

    local i=1
    while IFS= read -r file; do
        local size duration has_md=""
        size=$(du -h "$file" | cut -f1)
        duration=$("$FFPROBE" -v quiet -show_entries format=duration -of csv=p=0 "$file" 2>/dev/null | cut -d. -f1)
        [[ -f "${file%.*}.md" ]] && has_md=" [transcrito]"
        echo "  $i) $(basename "$file") (${size}, ${duration:-?}s)${has_md}"
        i=$((i + 1))
    done < <(find "$OUTPUT_DIR" -type f \( -name "*.wav" -o -name "*.mp3" \) | sort -r)
}

show_menu() {
    echo ""
    echo -e "${GREEN}=== Grabador de Audio ===${NC}"
    echo ""
    echo "  1) Grabar"
    echo "  2) Parar grabación"
    echo "  3) Transcribir última grabación"
    echo "  4) Transcribir archivo específico"
    echo "  5) Listar grabaciones"
    echo "  6) Ver dispositivos de audio"
    echo "  7) Salir"
    echo ""
    echo -n "  Opción: "
}

select_and_transcribe() {
    list_recordings
    echo ""
    echo -n "  Número de grabación a transcribir (o ruta completa): "
    read -r selection

    if [[ -f "$selection" ]]; then
        transcribe "$selection"
        return
    fi

    local files=()
    while IFS= read -r file; do
        files+=("$file")
    done < <(find "$OUTPUT_DIR" -type f \( -name "*.wav" -o -name "*.mp3" \) | sort -r)

    if [[ "$selection" =~ ^[0-9]+$ ]] && [[ "$selection" -ge 1 ]] && [[ "$selection" -le ${#files[@]} ]]; then
        transcribe "${files[$((selection-1))]}"
    else
        error "Selección inválida"
    fi
}

# --- Main ---
main() {
    check_deps

    echo -e "${GREEN}"
    echo "  ╔══════════════════════════════════════╗"
    echo "  ║   🎙️  Grabador + Transcriptor       ║"
    echo "  ║   Audio sistema + Micrófono          ║"
    echo "  ╚══════════════════════════════════════╝"
    echo -e "${NC}"

    info "Sistema: $OS"
    info "ffmpeg: $FFMPEG"
    info "Directorio de grabaciones: $OUTPUT_DIR"

    FFMPEG_PID=""
    RECORDING_FILE=""

    while true; do
        show_menu
        read -r choice
        case "$choice" in
            1)
                if [[ -n "${FFMPEG_PID:-}" ]] && kill -0 "$FFMPEG_PID" 2>/dev/null; then
                    warn "Ya hay una grabación en curso. Pará primero (opción 2)."
                else
                    start_recording || true
                fi
                ;;
            2) stop_recording ;;
            3)
                if [[ -n "${RECORDING_FILE:-}" ]]; then
                    transcribe "$RECORDING_FILE" || true
                else
                    local latest
                    latest=$(find "$OUTPUT_DIR" -type f \( -name "*.wav" -o -name "*.mp3" \) 2>/dev/null | sort -r | head -1 || true)
                    if [[ -n "$latest" ]]; then
                        transcribe "$latest" || true
                    else
                        warn "No hay grabaciones para transcribir"
                    fi
                fi
                ;;
            4) select_and_transcribe || true ;;
            5) list_recordings ;;
            6) show_audio_devices ;;
            7|q|Q)
                stop_recording 2>/dev/null || true
                ok "Chau!"
                exit 0
                ;;
            *) warn "Opción inválida" ;;
        esac
    done
}

# Solo corre el menú si se ejecuta directamente (permite `source` para pruebas)
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    trap 'stop_recording 2>/dev/null || true' EXIT INT TERM
    main "$@"
fi
