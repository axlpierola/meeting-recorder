# 🎙️ grabar — Grabador + Transcriptor de llamadas

Script de terminal que graba **el audio del sistema (lo que escuchás) + tu micrófono** al mismo
tiempo y después lo transcribe con [WhisperX](https://github.com/m-bain/whisperX), opcionalmente
identificando quién habla. Pensado para reuniones de Slack, Meet, Zoom o Teams.

Funciona en **macOS** (Apple Silicon o Intel) y **Linux** (Ubuntu con PipeWire/PulseAudio).

> [!IMPORTANT]
> **¿Usas Windows?** Esta rama (`main`) es para **macOS y Linux**. La versión para **Windows** es una aplicación
> de escritorio con interfaz gráfica (grabar, transcribir y resumir con IA) y vive en la rama
> [`windows`](https://github.com/axlpierola/meeting-recorder/tree/windows). Para usarla, **cambia de rama**:
>
> ```powershell
> git clone -b windows https://github.com/axlpierola/meeting-recorder.git
> # o, si ya clonaste el repositorio:
> git checkout windows
> ```
>
> Allí encontrarás su propio README con las instrucciones para Windows.

## Qué hace

- Graba sistema + micrófono mezclados, con volumen normalizado, a un `.mp3`.
- Transcribe en español (configurable) con WhisperX: `large-v3` o `medium`.
- Identifica hablantes (diarization) con pyannote si tenés token de Hugging Face.
- Genera un `.md` legible con marcas de tiempo y hablante, más el `.json` detallado.
- Menú interactivo; comando global `grabar`.

## Instalación rápida

```bash
git clone https://github.com/axlpierola/meeting-recorder.git   # o git@github.com:axlpierola/meeting-recorder.git
cd meeting-recorder
./install.sh
```

El instalador detecta tu sistema e instala todo lo necesario:

| Sistema | Instala |
|---------|---------|
| macOS   | `ffmpeg`, `pipx`, `python@3.12`, **BlackHole 2ch** (vía Homebrew) + `whisperx` |
| Linux   | `ffmpeg`, `pulseaudio-utils`, `pipx`, `python3` (vía apt) + `whisperx` |

Además crea los comandos `grabar` y `mp4towav` en `~/.local/bin`. Al terminar te muestra
los pasos manuales que faltan (abajo están detallados).

> Necesitás [Homebrew](https://brew.sh) en macOS. `whisperx` baja PyTorch, así que la
> instalación tarda varios minutos y ocupa ~3 GB.

### macOS: configurar BlackHole (una sola vez)

macOS no deja capturar el audio del sistema directamente; **BlackHole** es un dispositivo
virtual que recibe una copia de lo que suena. Hay que decirle a macOS que mande el sonido
a tus parlantes y a BlackHole a la vez:

1. Abrí **Configuración de Audio MIDI** (Spotlight → "Audio MIDI Setup").
2. Botón **+** (abajo a la izquierda) → **Crear dispositivo de salida múltiple**.
3. Marcá tus parlantes o auriculares **y** `BlackHole 2ch`. Activá *Drift Correction* en BlackHole.
4. Click derecho sobre el dispositivo nuevo → **Usar este dispositivo para la salida de sonido**.

Vos seguís escuchando normal y el script graba desde BlackHole. Si cambiás de auriculares,
volvé a elegir el dispositivo múltiple como salida (o agregá los nuevos auriculares a la lista).

**Permiso de micrófono:** la primera vez que grabes, macOS pide permiso para tu terminal.
Si no lo pide y la grabación sale vacía: *Ajustes del Sistema → Privacidad y seguridad →
Micrófono* y activá Terminal / iTerm.

### Linux

No hace falta nada extra: el script usa el `.monitor` de tu salida por defecto y el
micrófono por defecto de PulseAudio/PipeWire.

### Token de Hugging Face (solo para identificar hablantes)

1. Creá cuenta en https://huggingface.co/join
2. Con la sesión iniciada, aceptá las licencias de:
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0
3. Generá un token (permiso *Read*) en https://huggingface.co/settings/tokens
4. Guardalo en tu shell y abrí una terminal nueva:

```bash
echo 'export HF_TOKEN="hf_xxx"' >> ~/.zshrc    # macOS
echo 'export HF_TOKEN="hf_xxx"' >> ~/.bashrc   # Linux
```

Sin token igual podés transcribir, solo que sin separar quién habla.

## Uso

```bash
grabar
```

```
=== Grabador de Audio ===

  1) Grabar                         - Inicia grabación (sistema + mic)
  2) Parar grabación                - Detiene la grabación
  3) Transcribir última grabación
  4) Transcribir archivo específico - Elegir de la lista o pegar una ruta
  5) Listar grabaciones
  6) Ver dispositivos de audio      - Útil si no detecta BlackHole o el mic
  7) Salir
```

Flujo típico: `1` antes de la reunión → `2` al terminar → `3` para transcribir.

### Modos de transcripción

Al transcribir elegís modelo y si querés hablantes:

| Modo | Modelo | Speakers | Comentario |
|------|--------|----------|------------|
| 1 | large-v3 | sí | Mejor calidad. Linux con GPU: ~8 GB VRAM. En CPU/Mac: lento (~la duración del audio) |
| 2 | medium   | sí | Buena calidad, más rápido |
| 3 | medium   | no | El más rápido, no necesita token |
| 4 | large-v3 | no | Fuerza CPU en Linux |

En **macOS** siempre corre en CPU (WhisperX no usa la GPU de Apple). Un audio de 30 min
con `medium` tarda unos 10-15 min en un Mac M1/M2. En **Linux** usa CUDA por defecto; si no
tenés GPU NVIDIA, exportá `GRABAR_DEVICE=cpu`.

### Convertir un video/audio ya grabado

Si tenés la grabación de Zoom/Meet en `.mp4` (o `.m4a`, `.webm`):

```bash
mp4towav ~/Downloads/reunion.mp4   # lo deja en grabaciones/ como .wav
grabar                             # opción 4 para transcribirlo
```

## Archivos generados

Todo queda en `grabaciones/` dentro del proyecto (está en `.gitignore`, nunca se sube):

```
grabaciones/
├── 2026-10-13_15-00-00_kickoff.mp3   # audio
├── 2026-10-13_15-00-00_kickoff.json  # transcripción detallada (segmentos, hablantes)
└── 2026-10-13_15-00-00_kickoff.md    # transcripción legible
```

Ejemplo del `.md`:

```
**[00:12] SPEAKER_00:** Buenas, ¿me escuchan bien?
**[00:15] SPEAKER_01:** Sí, perfecto. Arranquemos con el tema de la migración...
```

## Variables de entorno opcionales

| Variable | Para qué |
|----------|----------|
| `HF_TOKEN` | Token de Hugging Face para identificar hablantes |
| `GRABAR_DIR` | Carpeta de grabaciones (por defecto `grabaciones/` junto al script) |
| `GRABAR_LANG` | Idioma de transcripción (por defecto `es`) |
| `GRABAR_DEVICE` | `cpu` o `cuda` (por defecto cuda en Linux, cpu en macOS) |
| `GRABAR_MONITOR` | macOS: nombre del dispositivo que captura el sistema (por defecto el que contenga "BlackHole") |
| `GRABAR_MIC` | macOS: nombre del micrófono (por defecto el primero que no sea BlackHole) |
| `GRABAR_FFMPEG` | Ruta a un ffmpeg concreto. Por defecto busca uno con soporte `pulse` (Linux) o `avfoundation` (macOS), porque los builds estáticos de ffmpeg no lo traen |

Para ver los nombres exactos de tus dispositivos: opción `6` del menú, o
`ffmpeg -f avfoundation -list_devices true -i ""` en macOS.

## Problemas comunes

- **"No se encontró fuente de audio del sistema" (macOS):** BlackHole no está instalado o
  no aparece. Instalalo con `brew install --cask blackhole-2ch` y reiniciá la terminal.
- **Se graba el mic pero no la otra persona (macOS):** la salida de sonido no es el
  dispositivo múltiple. Revisá *Ajustes → Sonido → Salida*.
- **Grabación vacía o de 0 s:** falta el permiso de micrófono para la terminal.
- **`whisperx: command not found`:** abrí una terminal nueva o corré `pipx ensurepath`.
- **Error de pyannote / 401 al diarizar:** el token no tiene permiso o no aceptaste las
  licencias de los dos modelos.
- **La primera transcripción tarda mucho:** está bajando el modelo (~3 GB large-v3,
  ~1.5 GB medium). Queda cacheado en `~/.cache/huggingface/`.
