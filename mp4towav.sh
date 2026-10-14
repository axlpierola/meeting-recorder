#!/usr/bin/env bash
# Convierte un archivo de audio/video (mp4, m4a, webm, etc.) a WAV 16kHz mono, óptimo para Whisper
# Uso: mp4towav /ruta/al/archivo.mp4

set -euo pipefail

resolve_path() {
    readlink -f "$1" 2>/dev/null || python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$1"
}
SCRIPT_DIR="$(cd "$(dirname "$(resolve_path "${BASH_SOURCE[0]}")")" && pwd)"
DEST_DIR="${GRABAR_DIR:-${SCRIPT_DIR}/grabaciones}"

if [[ -z "${1:-}" ]]; then
    echo "Uso: mp4towav /ruta/al/archivo.mp4"
    exit 1
fi

if [[ ! -f "$1" ]]; then
    echo "Error: archivo no encontrado: $1"
    exit 1
fi

mkdir -p "$DEST_DIR"

# Nombre de salida: fecha actual + nombre original
base="$(basename "${1%.*}" | tr ' ' '_' | tr -cd 'A-Za-z0-9_-')"
OUTPUT="$DEST_DIR/$(date +%Y-%m-%d_%H-%M-%S)_${base}.wav"

echo "Convirtiendo: $1"
echo "Destino: $OUTPUT"

ffmpeg -i "$1" -ar 16000 -ac 1 -c:a pcm_s16le "$OUTPUT"

echo ""
echo "Listo: $OUTPUT"
echo "Transcribilo con: grabar  →  opción 4"
