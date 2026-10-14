#!/bin/bash
# Convierte un archivo MP4 a WAV (16kHz mono, óptimo para Whisper)
# Uso: mp4towav /ruta/al/archivo.mp4

set -e

DEST_DIR="/home/silent/my-tools/my-notes/grabaciones"

if [ -z "$1" ]; then
    echo "Uso: mp4towav /ruta/al/archivo.mp4"
    exit 1
fi

if [ ! -f "$1" ]; then
    echo "Error: archivo no encontrado: $1"
    exit 1
fi

mkdir -p "$DEST_DIR"

# Nombre de salida basado en fecha actual
OUTPUT="$DEST_DIR/$(date +%Y-%m-%d_%H-%M-%S).wav"

echo "Convirtiendo: $1"
echo "Destino: $OUTPUT"

ffmpeg -i "$1" -ar 16000 -ac 1 -c:a pcm_s16le "$OUTPUT"

echo ""
echo "Listo: $OUTPUT"
