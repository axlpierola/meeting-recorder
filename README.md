# 🎙️ Grabador + Transcriptor de Audio

Script bash interactivo para grabar audio del sistema + micrófono y transcribir con Whisper. Ideal para grabar llamadas de Slack, Meet o Zoom y obtener la transcripción después.

## Características

- Graba audio del sistema (lo que escuchás) + micrófono simultáneamente
- Transcripción con Whisper (large-v3 o medium)
- Identificación de speakers con whisperx + pyannote
- Menú interactivo simple
- Comando global: `grabar`

## Requisitos

- Ubuntu 24 (PipeWire/PulseAudio)
- ffmpeg
- pulseaudio-utils (`pactl`)
- openai-whisper (transcripción básica)
- whisperx (transcripción con speakers)
- Token de Hugging Face (solo para diarization)

## Instalación

```bash
# Dependencias del sistema
sudo apt install ffmpeg pulseaudio-utils

# Whisper (transcripción)
pipx install openai-whisper

# Whisperx (transcripción + identificación de speakers)
pipx install whisperx

# Hacer ejecutable
chmod +x grabar.sh

# Crear comando global
ln -sf $(pwd)/grabar.sh ~/.local/bin/grabar
```

## Configuración de Hugging Face (para diarization)

1. Crear cuenta en https://huggingface.co/join
2. Aceptar licencias:
   - https://huggingface.co/pyannote/speaker-diarization-community-1
   - https://huggingface.co/pyannote/segmentation-3.0
3. Generar token en https://huggingface.co/settings/tokens
4. Configurar:

```bash
echo 'export HF_TOKEN="hf_tu_token"' >> ~/.bashrc
source ~/.bashrc
```

## Uso

```bash
grabar
```

### Menú

```
1) Grabar                        - Inicia grabación (sistema + mic)
2) Parar grabación               - Detiene la grabación
3) Transcribir última grabación  - Transcribe el último archivo
4) Transcribir archivo específico - Elegir de la lista
5) Listar grabaciones            - Ver todas las grabaciones
6) Salir
```

### Modos de transcripción

| Modo | Modelo | Device | Velocidad (30 min audio) | Calidad |
|------|--------|--------|--------------------------|---------|
| 1 | large-v3 | CPU | ~5-10 min | Excelente |
| 2 | medium | GPU | ~1 min | Muy buena |
| 3 | medium + speakers | GPU | ~2 min | Muy buena + quién habla |

## Archivos generados

Las grabaciones se guardan en `./grabaciones/` (dentro del proyecto):

```
my-notes/
├── grabar.sh
├── README.md
└── grabaciones/
    ├── 2026-05-13_22-17-32.wav    # Audio
    ├── 2026-05-13_22-17-32.txt    # Transcripción
    └── 2026-05-13_22-17-32.json   # Detalle con speakers (modo 3)
```

## Notas

- La primera transcripción descarga el modelo (~3 GB para large-v3, ~1.5 GB para medium)
- Los modelos quedan cacheados en `~/.cache/whisper/`
- El audio se graba a 16kHz mono (formato óptimo para Whisper)
- Para diarization, funciona mejor con audios largos (+5 min) y turnos claros de conversación
