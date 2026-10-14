# 🎙️ grabar — Grabador + Transcriptor de llamadas

Script de terminal que graba **el audio del sistema (lo que escuchás) + tu micrófono** al mismo
tiempo y después lo transcribe con [WhisperX](https://github.com/m-bain/whisperX), opcionalmente
identificando quién habla. Pensado para reuniones de Slack, Meet, Zoom o Teams.

Funciona en **macOS** (Apple Silicon o Intel), **Linux** (Ubuntu con PipeWire/PulseAudio) y **Windows** (versión Python con interfaz gráfica, ver [Windows](#windows)).

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


## Windows

La versión de Windows es una app en Python (`grabar_app/`) con **interfaz gráfica** y menú de terminal.
No hace falta instalar drivers de audio ni ffmpeg a mano ni ser administrador.

**Qué necesitás:** solo Python 3.10–3.12 (`winget install Python.Python.3.12`, marcando "Add to PATH").

```bat
iniciar.bat          :: interfaz gráfica
iniciar.bat cli      :: menú de terminal
```

La primera vez crea un entorno `.venv` e instala `PyAudioWPatch` (captura del audio del sistema
por WASAPI loopback, sin "Mezcla estéreo" ni VB-Cable) e `imageio-ffmpeg` (ffmpeg incluido).
Luego la app **verifica el entorno** (arriba de la ventana) y, si falta algo, te dice qué hacer.
WhisperX se instala desde el botón **Instalar WhisperX**: si detecta una GPU NVIDIA instala PyTorch
con CUDA y usará la GPU automáticamente.

Flujo: elegí salida y micrófono → **Grabar** → **Parar** → seleccioná la grabación → **Transcribir**.
También podés **Importar video/audio** (mp4, m4a, ...) para transcribir una reunión ya grabada.
Los archivos quedan en `grabaciones/` igual que en las otras plataformas. Para identificar hablantes
pegá el token de Hugging Face en la GUI (no se guarda) o definí `HF_TOKEN` con `setx HF_TOKEN "hf_xxx"`.

Notas: se graba el dispositivo de salida activo (si cambiás de auriculares, elegilo en la lista); los
modelos de WhisperX se descargan la primera vez (varios GB para `large-v3`).

### Instalación de WhisperX y solución de problemas (Windows)

- `iniciar.bat` abre **solo la ventana de la app** (sin consola negra). Si la app no arranca, el error
  se muestra en un mensaje y queda en `logs/error.log`.
- **Instalar WhisperX** descarga ~3 GB (PyTorch con CUDA si hay GPU NVIDIA) y necesita ~8 GB libres.
  Puede tardar 5–20 min: la app muestra una **barra de progreso** con MB descargados, tiempo transcurrido
  y la última línea de pip. Al final verifica que WhisperX realmente arranca.
- Si falla, aparece un mensaje con la **causa probable y cómo corregirla** (sin espacio, red/proxy, SSL,
  permisos, Python incompatible, ruta larga). El detalle completo queda en `logs/instalacion.log`
  (botón **Abrir carpeta de logs**). Pip reintenta hasta 10 veces ante cortes de red.
- Si cambias de Python o algo queda corrupto: borra la carpeta `.venv` y abre `iniciar.bat` de nuevo.

### Carpetas, resumen y proveedores (Windows)

- Las grabaciones, transcripciones y resúmenes se guardan en `grabaciones/AAAA/MM/DD/`
  (p. ej. `grabaciones/2026/10/14/`). Al abrir la app, los archivos antiguos sueltos en `grabaciones/`
  se ordenan solos en esa estructura.
- El botón **Resumen** (sección 4) genera `NOMBRE.resumen.md` junto a la transcripción, con: **Resumen**,
  **Key discussion points**, **Decisiones**, **Action items** (tabla acción/responsable/fecha) y **pendientes/riesgos**.
- El prompt vive en [`prompts/resumen.md`](prompts/resumen.md): edítalo para cambiar el formato o el tono
  (`{{TRANSCRIPCION}}` marca dónde se inserta el texto). También sirve para pegarlo en cualquier chat de IA.
- Proveedores: **Ollama** (local, gratis, nada sale de tu PC; instala [Ollama](https://ollama.com/download)
  y la app descarga el modelo, ~5 GB, con barra de progreso), **Claude**, **Gemini** (tiene plan gratuito) y
  **ChatGPT** por API key. La key se guarda en `.api_keys.json` (ignorado por git) y se cambia con **Editar**.
  El campo Modelo es editable por si cambian los nombres. Con APIs en la nube la transcripción se envía al proveedor.

### Token de Hugging Face: ¿para qué y es gratis?

Solo sirve para **Identificar hablantes** (quién dijo qué). Sin token la transcripción funciona igual,
sin separar voces. Es **gratis** (cuenta, token y modelos); todo se procesa en tu PC. Una sola vez:

1. Crea una cuenta en https://huggingface.co.
2. Acepta las condiciones (botón *Agree*) en `pyannote/speaker-diarization-community-1`.
3. Crea un token *Read* en https://huggingface.co/settings/tokens y pégalo en el campo **Token HF**
   (el botón **¿Qué es?** de la app explica esto y abre la página). Pulsa **Guardar**: queda en `.hf_token`
   (ignorado por git) y el campo se bloquea; usa **Editar** para cambiarlo.

### GPU (Windows)

El selector **Cómputo** tiene `auto`, `gpu` y `cpu`. WhisperX instala su propio PyTorch (solo CPU), por eso
el botón **Instalar WhisperX** lo reemplaza al final por la misma versión con CUDA si detecta una GPU NVIDIA.
Si `gpu` avisa que PyTorch no tiene CUDA, pulsa **Instalar WhisperX** de nuevo. Los avisos de `torchcodec`
en el log son inofensivos. La primera transcripción descarga varios GB de modelos (puede tardar con red lenta).
