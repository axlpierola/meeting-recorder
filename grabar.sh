#!/bin/bash
# ============================================================
# grabar.sh - Graba audio del sistema + micrófono y transcribe
# Mejorado con WhisperX, Normalización de Audio y Markdown
# Requiere: ffmpeg, pulseaudio-utils, whisperx
# ============================================================

set -euo pipefail

# --- Configuración ---
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
OUTPUT_DIR="${SCRIPT_DIR}/grabaciones"
WHISPER_LANG="es"
DATE_FMT="+%Y-%m-%d_%H-%M-%S"
HF_TOKEN="${HF_TOKEN:-}"  # Configurar con: export HF_TOKEN="hf_tu_token"

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
    for cmd in /usr/bin/ffmpeg pactl; do
        if ! command -v "$cmd" &>/dev/null; then
            missing+=("$cmd")
        fi
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        error "Faltan dependencias: ${missing[*]}"
        echo "  Instalá con: sudo apt install ffmpeg pulseaudio-utils"
        exit 1
    fi
}

check_whisperx() {
    if ! command -v whisperx &>/dev/null; then
        warn "Whisperx no está instalado."
        echo "  Instalá con: pipx install whisperx"
        return 1
    fi
    if [[ "$USE_DIARIZE" == true && -z "$HF_TOKEN" ]]; then
        warn "HF_TOKEN no configurado. Necesario para identificar hablantes."
        echo "  Configurá con: export HF_TOKEN=\"hf_tu_token\""
        echo -n "  O ingresá tu token de HuggingFace ahora (déjalo en blanco para omitir diarization): "
        read -r HF_TOKEN
        if [[ -z "$HF_TOKEN" ]]; then
            warn "Token no provisto, se desactivará la identificación de hablantes."
            USE_DIARIZE=false
        fi
    fi
    return 0
}

get_monitor_source() {
    local default_sink
    default_sink=$(pactl get-default-sink 2>/dev/null)
    if [[ -n "$default_sink" ]]; then
        echo "${default_sink}.monitor"
    else
        pactl list short sources 2>/dev/null | grep monitor | head -1 | awk '{print $2}'
    fi
}

get_mic_source() {
    pactl get-default-source 2>/dev/null
}

select_whisper_mode() {
    echo ""
    echo -e "${BLUE}  Seleccioná el modo de transcripción (usando WhisperX ultrarrápido):${NC}"
    echo ""
    echo "  1) large-v3 en GPU + Speakers  (Mejor calidad, requiere GPU ~8GB VRAM)"
    echo "  2) medium en GPU + Speakers    (Buena calidad, requiere GPU ~5GB VRAM)"
    echo "  3) medium en GPU sin Speakers  (Si no tienes token o no te importan los hablantes)"
    echo "  4) large-v3 en CPU sin Speakers(Lento, pero funciona sin tarjeta gráfica)"
    echo ""
    echo -n "  Modo [1/2/3/4]: "
    read -r mode_choice

    case "$mode_choice" in
        1)
            WHISPER_MODEL="large-v3"
            WHISPER_DEVICE="cuda"
            COMPUTE_TYPE="float16"
            USE_DIARIZE=true
            info "Usando modelo: large-v3 en GPU + diarization"
            ;;
        2)
            WHISPER_MODEL="medium"
            WHISPER_DEVICE="cuda"
            COMPUTE_TYPE="float16"
            USE_DIARIZE=true
            info "Usando modelo: medium en GPU + diarization"
            ;;
        4)
            WHISPER_MODEL="large-v3"
            WHISPER_DEVICE="cpu"
            COMPUTE_TYPE="int8"
            USE_DIARIZE=false
            info "Usando modelo: large-v3 en CPU (int8)"
            ;;
        *)
            WHISPER_MODEL="medium"
            WHISPER_DEVICE="cuda"
            COMPUTE_TYPE="float16"
            USE_DIARIZE=false
            info "Usando modelo: medium en GPU"
            ;;
    esac
}

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
        exit 1
    fi

    info "Audio del sistema: $monitor_src"
    info "Micrófono: ${mic_src:-no detectado}"
    info "Archivo: $RECORDING_FILE"
    echo ""

    if [[ -n "$mic_src" ]]; then
        # Mezcla, añade silencio a los cortes, y normaliza volumen a nivel estándar
        /usr/bin/ffmpeg -y \
            -thread_queue_size 1024 -use_wallclock_as_timestamps 1 -f pulse -i "$monitor_src" \
            -thread_queue_size 1024 -use_wallclock_as_timestamps 1 -f pulse -i "$mic_src" \
            -filter_complex "[0:a]aresample=async=1[a0];[1:a]aresample=async=1[a1];[a0][a1]amix=inputs=2:duration=longest[amixed];[amixed]loudnorm=I=-16:TP=-1.5:LRA=11[out]" \
            -map "[out]" \
            -ac 2 -ar 48000 -b:a 192k \
            "$RECORDING_FILE" \
            -loglevel quiet &
    else
        warn "No se detectó micrófono, grabando solo audio del sistema"
        /usr/bin/ffmpeg -y \
            -thread_queue_size 1024 -use_wallclock_as_timestamps 1 -f pulse -i "$monitor_src" \
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
            duration=$(/usr/bin/ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$RECORDING_FILE" 2>/dev/null | cut -d. -f1)
            ok "Archivo guardado: $RECORDING_FILE ($size, ${duration:-?}s)"
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
        python3 -c "
import json, sys

def format_time(seconds):
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f'{mins:02d}:{secs:02d}'

try:
    with open('$json_file') as f:
        data = json.load(f)
    
    with open('$md_file', 'w', encoding='utf-8') as out:
        out.write('# Transcripción de Audio\n\n')
        
        current_speaker = None
        current_text = []
        start_time = 0.0
        
        for seg in data.get('segments', []):
            speaker = seg.get('speaker', 'SPEAKER')
            text = seg.get('text', '').strip()
            if not text: continue
            
            if speaker != current_speaker:
                if current_speaker is not None:
                    timestamp = format_time(start_time)
                    joined = ' '.join(current_text)
                    out.write(f'**[{timestamp}] {current_speaker}:** {joined}\n\n')
                current_speaker = speaker
                start_time = seg.get('start', 0.0)
                current_text = [text]
            else:
                current_text.append(text)
                
        # Last segment
        if current_speaker is not None:
            timestamp = format_time(start_time)
            joined = ' '.join(current_text)
            out.write(f'**[{timestamp}] {current_speaker}:** {joined}\n\n')
            
    print(f'\n[OK] Documento Markdown generado: $md_file')
except Exception as e:
    print(f'Error al generar Markdown: {e}')
" 2>/dev/null || true

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
        duration=$(/usr/bin/ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$file" 2>/dev/null | cut -d. -f1)
        [[ -f "${file%.*}.md" ]] && has_md=" [transcrito]"
        echo "  $i) $(basename "$file") (${size}, ${duration:-?}s)${has_md}"
        ((i++))
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
    echo "  6) Salir"
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
                    start_recording
                fi
                ;;
            2) stop_recording ;;
            3)
                if [[ -n "${RECORDING_FILE:-}" ]]; then
                    transcribe "$RECORDING_FILE"
                else
                    local latest
                    latest=$(find "$OUTPUT_DIR" -type f \( -name "*.wav" -o -name "*.mp3" \) 2>/dev/null | sort -r | head -1)
                    if [[ -n "$latest" ]]; then
                        transcribe "$latest"
                    else
                        warn "No hay grabaciones para transcribir"
                    fi
                fi
                ;;
            4) select_and_transcribe ;;
            5) list_recordings ;;
            6|q|Q)
                stop_recording 2>/dev/null || true
                ok "Chau!"
                exit 0
                ;;
            *) warn "Opción inválida" ;;
        esac
    done
}

trap 'stop_recording 2>/dev/null || true' EXIT INT TERM
main "$@"
