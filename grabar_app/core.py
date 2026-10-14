"""Lógica compartida por la CLI y la GUI: verificación del entorno, grabación
(WASAPI loopback + micrófono en Windows) y transcripción con WhisperX."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

APP_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(os.environ.get("GRABAR_DIR") or APP_DIR / "grabaciones")
TOOLS_DIR = APP_DIR / ".tools"
LOG_DIR = APP_DIR / "logs"
LOG_FILE = LOG_DIR / "instalacion.log"
IS_WIN = os.name == "nt"
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".mp4", ".webm", ".flac", ".ogg")
CUDA_INDEX = "https://download.pytorch.org/whl/cu128"

Log = Callable[[str], None]

# La GUI corre con pythonw.exe (sin consola); los subprocesos usan python.exe
_exe = Path(sys.executable)
PYTHON = str(_exe.with_name("python.exe")) if _exe.name.lower() == "pythonw.exe" else sys.executable


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _no_window() -> int:
    # Evita que se abra una consola negra por cada subproceso en Windows
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WIN else 0


def find_ffmpeg() -> Optional[str]:
    env = os.environ.get("GRABAR_FFMPEG")
    if env and Path(env).exists():
        return env
    local = TOOLS_DIR / ("ffmpeg.exe" if IS_WIN else "ffmpeg")
    if local.exists():
        return str(local)
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def prepare_env() -> dict:
    """Entorno para subprocesos. WhisperX llama a `ffmpeg` por nombre, así que
    si solo tenemos el binario de imageio-ffmpeg lo exponemos como ffmpeg(.exe)."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    if shutil.which("ffmpeg") is None:
        exe = find_ffmpeg()
        if exe:
            TOOLS_DIR.mkdir(exist_ok=True)
            target = TOOLS_DIR / ("ffmpeg.exe" if IS_WIN else "ffmpeg")
            if not target.exists():
                shutil.copy2(exe, target)
                target.chmod(0o755)
            env["PATH"] = str(TOOLS_DIR) + os.pathsep + env.get("PATH", "")
    return env


def nvidia_gpu() -> Optional[str]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=15, creationflags=_no_window(),
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip().splitlines()[0]
    except Exception:
        pass
    return None


_cuda_cache: Optional[bool] = None


def cuda_available() -> bool:
    global _cuda_cache
    if _cuda_cache is None:
        if not _has_module("torch"):
            return False  # no cachear: puede instalarse luego
        try:
            out = subprocess.run(
                [PYTHON, "-c", "import torch;print(torch.cuda.is_available())"],
                capture_output=True, text=True, timeout=120, creationflags=_no_window(),
            )
            _cuda_cache = out.stdout.strip() == "True"
        except Exception:
            _cuda_cache = False
    return _cuda_cache


def default_device() -> str:
    forced = os.environ.get("GRABAR_DEVICE")
    if forced in ("cpu", "cuda"):
        return forced
    return "cuda" if cuda_available() else "cpu"


# --------------------------------------------------------------------------
# Verificación del entorno
# --------------------------------------------------------------------------
@dataclass
class Check:
    key: str
    label: str
    ok: bool
    detail: str
    fix: str = ""          # qué hacer a mano
    action: str = ""       # "audio" | "whisperx" si la app puede instalarlo sola
    required: bool = True


def check_environment() -> list[Check]:
    checks: list[Check] = []
    v = sys.version_info
    checks.append(Check(
        "python", "Python", (3, 9) <= v[:2] <= (3, 12),
        f"{v.major}.{v.minor}.{v.micro}" + ("" if (3, 9) <= v[:2] <= (3, 12) else " (WhisperX funciona mejor con 3.10-3.12)"),
        "Instalá Python 3.12: winget install Python.Python.3.12", required=False,
    ))

    ff = find_ffmpeg()
    ok_ff = False
    detail = "no encontrado"
    if ff:
        try:
            r = subprocess.run([ff, "-version"], capture_output=True, text=True, timeout=15,
                               creationflags=_no_window())
            ok_ff = r.returncode == 0
            detail = ff if ok_ff else f"{ff} no se pudo ejecutar"
        except Exception as e:
            detail = f"{ff}: {e}"
    checks.append(Check("ffmpeg", "ffmpeg", ok_ff, detail,
                        "Se instala con el paquete pip imageio-ffmpeg (botón Instalar)", "audio"))

    if IS_WIN:
        has_pa = _has_module("pyaudiowpatch")
        checks.append(Check("pyaudio", "Captura de audio (PyAudioWPatch)", has_pa,
                            "instalado" if has_pa else "no instalado",
                            "pip install PyAudioWPatch (botón Instalar)", "audio"))
        if has_pa:
            try:
                devs = list_audio_devices()
                loop = devs["default_loopback"]
                mic = devs["default_input"]
                checks.append(Check("loopback", "Audio del sistema (loopback)", loop is not None,
                                    loop["name"] if loop else "sin dispositivo de salida activo",
                                    "Conectá/activá parlantes o auriculares en Configuración de sonido"))
                checks.append(Check("mic", "Micrófono", mic is not None,
                                    mic["name"] if mic else "no detectado",
                                    "Conectá un micrófono y revisá Configuración > Privacidad > Micrófono",
                                    required=False))
            except Exception as e:
                checks.append(Check("loopback", "Dispositivos de audio", False, str(e)))
    else:
        checks.append(Check("platform", "Sistema", True,
                            "Grabar solo funciona en Windows; en Linux/macOS usá grabar.sh. "
                            "La transcripción sí funciona aquí.", required=False))

    wx = _has_module("whisperx")
    checks.append(Check("whisperx", "WhisperX (transcripción)", wx,
                        "instalado" if wx else "no instalado (~3 GB con PyTorch)",
                        "Botón Instalar WhisperX", "whisperx", required=False))

    gpu = nvidia_gpu()
    if gpu:
        cu = cuda_available() if wx else False
        checks.append(Check(
            "gpu", "GPU NVIDIA", True,
            f"{gpu}" + (" · CUDA activo en PyTorch" if cu else
                        " · PyTorch aún sin CUDA (se corregirá al instalar WhisperX)" if not wx else
                        " · PyTorch SIN CUDA: reinstalá WhisperX para usar la GPU"),
            required=False))
    else:
        checks.append(Check("gpu", "GPU NVIDIA", True,
                            "no detectada: se usará CPU (modelo 'medium' recomendado)", required=False))

    tok = bool(load_hf_token())
    checks.append(Check("hf", "Token Hugging Face (hablantes)", tok,
                        "definido" if tok else "no definido: solo hace falta para identificar hablantes",
                        "Opcional y gratis. Pegalo en el campo 'Token HF' (botón '¿Qué es?' explica cómo obtenerlo)",
                        required=False))
    return checks


HF_HELP = (
    "¿Para qué sirve?\n"
    "Solo para 'Identificar hablantes' (saber quién dijo qué). Sin token la transcripción funciona "
    "igual, pero sin separar voces. El modelo que distingue voces (pyannote) está alojado en "
    "Hugging Face y exige una cuenta.\n\n"
    "¿Es gratis? Sí: cuenta, token (tipo 'Read') y modelos son gratuitos; todo se procesa en tu PC.\n\n"
    "Pasos (una sola vez):\n"
    "1. Crear cuenta en huggingface.co\n"
    "2. Aceptar las condiciones (botón 'Agree') en:\n"
    "   huggingface.co/pyannote/speaker-diarization-3.1\n"
    "   huggingface.co/pyannote/segmentation-3.0\n"
    "3. Crear un token 'Read' en huggingface.co/settings/tokens y pegarlo acá."
)


def missing_required(checks: list[Check]) -> list[Check]:
    return [c for c in checks if c.required and not c.ok]


# --------------------------------------------------------------------------
# Instalación de dependencias (pip, sin permisos de administrador)
# --------------------------------------------------------------------------
class InstallError(RuntimeError):
    """Fallo de instalación con causa probable y pasos para corregirlo."""


# (patrón en la salida de pip, causa probable + qué hacer)
_DIAGNOSES = [
    (r"No space left|Errno 28|not enough space",
     "Sin espacio en disco. WhisperX + PyTorch necesitan ~8 GB libres durante la instalación. "
     "Liberá espacio en esta unidad y reintentá."),
    (r"Read timed out|ConnectionError|Connection aborted|Max retries exceeded|"
     r"Temporary failure in name resolution|getaddrinfo failed|Network is unreachable",
     "Problema de red: se cortó la descarga. Revisá tu internet (¿VPN/proxy/firewall corporativo?) "
     "y reintentá; pip retoma lo ya descargado."),
    (r"SSLError|CERTIFICATE_VERIFY_FAILED",
     "Error SSL/certificados, típico de proxys corporativos que inspeccionan HTTPS. "
     "Probá en otra red o pedí a TI que permita pypi.org, files.pythonhosted.org y download.pytorch.org."),
    (r"WinError 5|PermissionError|Access is denied|Acceso denegado|WinError 32",
     "Permisos o archivo en uso. Cerrá otras ventanas de la app/Python, pausá el antivirus un momento "
     "y reintentá. La app no necesita ser administrador."),
    (r"Microsoft Visual C\+\+|Failed building wheel|error: subprocess-exited-with-error|"
     r"Could not build wheels",
     "pip intentó compilar un paquete (no hay versión precompilada para tu Python). "
     "Usá Python 3.12 de 64 bits (winget install Python.Python.3.12), borrá la carpeta .venv y volvé a abrir."),
    (r"No matching distribution found|Could not find a version that satisfies",
     "pip no encontró una versión compatible. Suele pasar con Python muy nuevo (3.13+) o de 32 bits. "
     "Usá Python 3.12 de 64 bits, borrá la carpeta .venv y volvé a abrir."),
    (r"MemoryError",
     "Memoria insuficiente al instalar. Cerrá otras aplicaciones y reintentá."),
    (r"Long Path|path too long|FileNotFoundError.*\\",
     "Ruta demasiado larga en Windows. Mové el proyecto a una carpeta corta (p. ej. C:\\grabador)."),
]


def diagnose(lines: list[str]) -> str:
    text = "\n".join(lines[-400:])
    for pattern, msg in _DIAGNOSES:
        if re.search(pattern, text, re.I):
            return msg
    return "Causa no reconocida. Mirá las últimas líneas del log (arriba) y el archivo de log completo."


def _run_stream(cmd: list[str], log: Log, env: Optional[dict] = None,
                progress: Optional[Callable[[int, int], None]] = None) -> tuple[int, list[str]]:
    """Ejecuta cmd mostrando la salida en vivo y guardándola en logs/instalacion.log.
    Las líneas 'Progress X of Y' de pip (--progress-bar raw) alimentan `progress`."""
    LOG_DIR.mkdir(exist_ok=True)
    env = dict(env or prepare_env())
    env["PYTHONUNBUFFERED"] = "1"
    lines: list[str] = []
    with open(LOG_FILE, "a", encoding="utf-8") as lf:
        lf.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} :: {' '.join(cmd)}\n")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", env=env,
                                creationflags=_no_window())
        assert proc.stdout
        for raw in proc.stdout:
            line = raw.rstrip()
            m = re.match(r"Progress (\d+) of (\d+)", line)
            if m:
                if progress:
                    progress(int(m[1]), int(m[2]))
                continue
            lines.append(line)
            lf.write(line + "\n")
            log(line)
        rc = proc.wait()
        lf.write(f"===== código de salida: {rc}\n")
    return rc, lines


_PIP = ["-m", "pip", "install", "--no-input", "--progress-bar", "raw",
        "--retries", "10", "--timeout", "60"]


def _pip(args: list[str], log: Log, progress=None) -> tuple[int, list[str]]:
    return _run_stream([PYTHON, *_PIP, *args], log, progress=progress)


def _fail(what: str, lines: list[str], rc: int) -> InstallError:
    return InstallError(f"{what} falló (código {rc}).\n\nCausa probable: {diagnose(lines)}\n\n"
                        f"Log completo: {LOG_FILE}")


def install_audio_deps(log: Log, progress=None) -> bool:
    pkgs = ["imageio-ffmpeg"] + (["PyAudioWPatch"] if IS_WIN else [])
    log(f"Instalando {', '.join(pkgs)} ...")
    rc, lines = _pip(["--upgrade", *pkgs], log, progress)
    if rc != 0:
        raise _fail("La instalación de audio/ffmpeg", lines, rc)
    return True


def _torch_versions() -> dict[str, str]:
    code = ("import importlib.metadata as m;"
            "print(';'.join(n+'='+m.version(n) for n in ('torch','torchaudio','torchvision') "
            "if __import__('importlib.util').util.find_spec(n)))")
    r = subprocess.run([PYTHON, "-c", code], capture_output=True, text=True, creationflags=_no_window())
    return dict(kv.split("=", 1) for kv in r.stdout.strip().split(";") if "=" in kv)


TOKEN_FILE = APP_DIR / ".hf_token"


def load_hf_token() -> str:
    """Token guardado por la app (archivo local, ignorado por git) o variable HF_TOKEN."""
    try:
        t = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if t:
            return t
    except OSError:
        pass
    return os.environ.get("HF_TOKEN", "").strip()


def save_hf_token(token: str) -> None:
    token = token.strip()
    if token:
        TOKEN_FILE.write_text(token, encoding="utf-8")
    else:
        TOKEN_FILE.unlink(missing_ok=True)


def _free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1024 ** 3


def install_whisperx(log: Log, progress=None) -> bool:
    """Si hay GPU NVIDIA instala primero PyTorch con CUDA; luego WhisperX."""
    global _cuda_cache
    _cuda_cache = None
    free = _free_gb(APP_DIR)
    log(f"Espacio libre en la unidad: {free:.1f} GB (se necesitan ~8 GB).")
    if free < 8:
        raise InstallError(f"Solo hay {free:.1f} GB libres; hacen falta ~8 GB. Liberá espacio y reintentá.")
    gpu = nvidia_gpu()
    steps = 3 if gpu else 2
    log(f"Paso 1/{steps}: WhisperX y sus dependencias (incluye PyTorch, puede tardar 5-20 min) ...")
    rc, lines = _pip(["--upgrade", "whisperx"], log, progress)
    if rc != 0:
        raise _fail("La instalación de WhisperX", lines, rc)
    if gpu:
        # WhisperX fija su propia versión de torch (CPU en Windows): se reemplaza por la
        # misma versión compilada con CUDA. Debe hacerse DESPUÉS de instalar WhisperX.
        log("Paso 2/3: GPU NVIDIA detectada, cambiando PyTorch a la versión con CUDA (~2.7 GB) ...")
        vers = _torch_versions()
        pk = [f"{n}=={v.split('+')[0]}" for n, v in vers.items()] or ["torch", "torchaudio"]
        rc, lines = _pip(["--force-reinstall", "--no-deps", *pk, "--index-url", CUDA_INDEX], log, progress)
        if rc != 0:
            raise _fail("La instalación de PyTorch con CUDA (WhisperX quedó instalado pero solo en CPU)", lines, rc)
        _cuda_cache = None
        if not cuda_available():
            log("Aviso: PyTorch se instaló pero CUDA no está disponible; actualizá el driver de NVIDIA.")
    log(f"Paso {steps}/{steps}: verificando que WhisperX arranca ...")
    r = subprocess.run([PYTHON, "-c", "import whisperx"], capture_output=True, text=True,
                       env=prepare_env(), creationflags=_no_window())
    if r.returncode != 0:
        tail = r.stderr.strip().splitlines()
        for ln in tail[-15:]:
            log(ln)
        raise InstallError("WhisperX se instaló pero falla al importarse:\n" + "\n".join(tail[-3:])
                           + f"\n\nPosible causa: {diagnose(tail)}\n"
                           "Si menciona 'DLL', instalá 'Microsoft Visual C++ Redistributable 2015-2022 x64'.")
    return True


# --------------------------------------------------------------------------
# Dispositivos y grabación (Windows / WASAPI)
# --------------------------------------------------------------------------
def _slim(d: dict) -> dict:
    return {"index": d["index"], "name": d["name"], "channels": int(d["maxInputChannels"]),
            "rate": int(d["defaultSampleRate"])}


def list_audio_devices() -> dict:
    import pyaudiowpatch as pa  # type: ignore

    p = pa.PyAudio()
    try:
        wasapi = p.get_host_api_info_by_type(pa.paWASAPI)
        loops = [_slim(d) for d in p.get_loopback_device_info_generator()]
        ins = []
        for i in range(p.get_device_count()):
            d = p.get_device_info_by_index(i)
            if (d["hostApi"] == wasapi["index"] and d["maxInputChannels"] > 0
                    and not d.get("isLoopbackDevice")):
                ins.append(_slim(d))
        out_idx = wasapi["defaultOutputDevice"]
        out_name = p.get_device_info_by_index(out_idx)["name"] if out_idx >= 0 else ""
        default_loop = next((d for d in loops if out_name and out_name in d["name"]),
                            loops[0] if loops else None)
        in_idx = wasapi["defaultInputDevice"]
        default_in = _slim(p.get_device_info_by_index(in_idx)) if in_idx >= 0 else None
        return {"loopbacks": loops, "inputs": ins,
                "default_loopback": default_loop, "default_input": default_in}
    finally:
        p.terminate()


class _Track:
    """Graba un dispositivo a WAV. El loopback de WASAPI no entrega datos
    durante el silencio, así que se rellenan los huecos con ceros según el
    reloj para que ambas pistas queden alineadas."""

    def __init__(self, pa_mod, pa, dev_index: int, path: Path):
        info = pa.get_device_info_by_index(dev_index)
        self.pa_mod = pa_mod
        self.rate = int(info["defaultSampleRate"])
        self.ch = int(info["maxInputChannels"])
        self.path = path
        self.frames = 0
        self.wf = wave.open(str(path), "wb")
        self.wf.setnchannels(self.ch)
        self.wf.setsampwidth(2)
        self.wf.setframerate(self.rate)
        self.t0 = time.monotonic()
        self.stream = pa.open(format=pa_mod.paInt16, channels=self.ch, rate=self.rate, input=True,
                              input_device_index=dev_index, frames_per_buffer=1024,
                              stream_callback=self._cb)

    def _pad_to(self, target_frames: int) -> None:
        gap = target_frames - self.frames
        if gap > 0:
            self.wf.writeframes(b"\x00" * gap * self.ch * 2)
            self.frames += gap

    def _cb(self, data, frame_count, time_info, status):
        expected = int((time.monotonic() - self.t0) * self.rate)
        if expected - frame_count - self.frames > self.rate // 10:
            self._pad_to(expected - frame_count)
        self.wf.writeframes(data)
        self.frames += frame_count
        return (None, self.pa_mod.paContinue)

    def close(self) -> None:
        self.stream.stop_stream()
        self.stream.close()
        self._pad_to(int((time.monotonic() - self.t0) * self.rate))
        self.wf.close()


class Recorder:
    def __init__(self, loopback_index: Optional[int], mic_index: Optional[int]):
        self.loopback_index = loopback_index
        self.mic_index = mic_index
        self.tracks: list[_Track] = []
        self.pa = None
        self.final: Optional[Path] = None
        self.started_at = 0.0

    @property
    def active(self) -> bool:
        return bool(self.tracks)

    def start(self, name: str = "") -> Path:
        if not IS_WIN:
            raise RuntimeError("La grabación solo está implementada para Windows (usá grabar.sh en Linux/macOS).")
        if self.active:
            raise RuntimeError("Ya hay una grabación en curso")
        if self.loopback_index is None and self.mic_index is None:
            raise RuntimeError("No hay ni audio del sistema ni micrófono para grabar")
        import pyaudiowpatch as pa  # type: ignore

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        clean = re.sub(r"[^A-Za-z0-9_-]", "", name.strip().replace(" ", "_"))
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        base = OUTPUT_DIR / (f"{stamp}_{clean}" if clean else stamp)
        self.final = base.with_suffix(".mp3")
        self.pa = pa.PyAudio()
        try:
            for tag, idx in (("sys", self.loopback_index), ("mic", self.mic_index)):
                if idx is not None:
                    self.tracks.append(_Track(pa, self.pa, idx, Path(f"{base}.{tag}.wav")))
        except Exception:
            self._abort()
            raise
        self.started_at = time.monotonic()
        return self.final

    def _abort(self) -> None:
        for t in self.tracks:
            try:
                t.close()
            except Exception:
                pass
        self.tracks = []
        if self.pa:
            self.pa.terminate()
            self.pa = None

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at if self.active else 0.0

    def stop(self, log: Log = print) -> Optional[Path]:
        if not self.active:
            return None
        wavs = [t.path for t in self.tracks]
        self._abort()
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            raise RuntimeError(f"ffmpeg no disponible; las pistas crudas quedaron en {wavs}")
        cmd = [ffmpeg, "-y", "-loglevel", "error"]
        for w in wavs:
            cmd += ["-i", str(w)]
        if len(wavs) == 2:
            cmd += ["-filter_complex",
                    "[0:a]aresample=async=1[a0];[1:a]aresample=async=1[a1];"
                    "[a0][a1]amix=inputs=2:duration=longest[m];[m]loudnorm=I=-16:TP=-1.5:LRA=11[out]",
                    "-map", "[out]"]
        else:
            cmd += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
        cmd += ["-ac", "2", "-ar", "48000", "-b:a", "192k", str(self.final)]
        log("Mezclando y normalizando audio ...")
        r = subprocess.run(cmd, capture_output=True, text=True, creationflags=_no_window())
        if r.returncode != 0 or not self.final or not self.final.exists():
            raise RuntimeError(f"ffmpeg falló: {r.stderr.strip()}\nPistas crudas: {wavs}")
        for w in wavs:
            w.unlink(missing_ok=True)
        return self.final


# --------------------------------------------------------------------------
# Archivos
# --------------------------------------------------------------------------
def list_recordings() -> list[Path]:
    if not OUTPUT_DIR.exists():
        return []
    files = [p for p in OUTPUT_DIR.iterdir()
             if p.suffix.lower() in AUDIO_EXT and ".sys." not in p.name and ".mic." not in p.name]
    return sorted(files, key=lambda p: p.name, reverse=True)


def duration_seconds(path: Path) -> Optional[int]:
    ff = find_ffmpeg()
    if not ff:
        return None
    probe = Path(ff).with_name("ffprobe" + (".exe" if IS_WIN else ""))
    if probe.exists():
        r = subprocess.run([str(probe), "-v", "quiet", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True,
                           creationflags=_no_window())
        try:
            return int(float(r.stdout.strip()))
        except ValueError:
            return None
    # imageio-ffmpeg no trae ffprobe: se lee la duración de la salida de ffmpeg
    r = subprocess.run([ff, "-i", str(path)], capture_output=True, text=True,
                       creationflags=_no_window())
    m = re.search(r"Duration: (\d+):(\d+):(\d+)", r.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) if m else None


def convert_to_wav(src: Path, log: Log = print) -> Path:
    """Equivalente a mp4towav: WAV 16 kHz mono dentro de grabaciones/."""
    ff = find_ffmpeg()
    if not ff:
        raise RuntimeError("ffmpeg no disponible")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base = re.sub(r"[^A-Za-z0-9_-]", "", src.stem.replace(" ", "_"))
    out = OUTPUT_DIR / f"{datetime.now():%Y-%m-%d_%H-%M-%S}_{base}.wav"
    log(f"Convirtiendo {src.name} ...")
    r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src), "-ar", "16000", "-ac", "1",
                        "-c:a", "pcm_s16le", str(out)], capture_output=True, text=True,
                       creationflags=_no_window())
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return out


# --------------------------------------------------------------------------
# Transcripción
# --------------------------------------------------------------------------
def _fmt(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def json_to_markdown(json_file: Path, md_file: Path) -> None:
    data = json.loads(Path(json_file).read_text(encoding="utf-8"))
    lines = ["# Transcripción de Audio", ""]
    speaker, texts, start = None, [], 0.0
    for seg in data.get("segments", []):
        text = seg.get("text", "").strip()
        if not text:
            continue
        who = seg.get("speaker", "SPEAKER")
        if who != speaker:
            if speaker is not None:
                lines += [f"**[{_fmt(start)}] {speaker}:** {' '.join(texts)}", ""]
            speaker, texts, start = who, [text], seg.get("start", 0.0)
        else:
            texts.append(text)
    if speaker is not None:
        lines += [f"**[{_fmt(start)}] {speaker}:** {' '.join(texts)}", ""]
    Path(md_file).write_text("\n".join(lines), encoding="utf-8")


MODELS = {
    "large-v3": "Mejor calidad (GPU ~8 GB VRAM; lento en CPU)",
    "medium": "Buena calidad, más rápido (GPU ~5 GB)",
    "small": "Rápido, calidad media",
}


class Transcription:
    def __init__(self, audio: Path, model: str = "medium", language: str = "es",
                 diarize: bool = False, hf_token: str = "", device: Optional[str] = None):
        self.audio, self.model, self.language = Path(audio), model, language
        self.diarize, self.hf_token = diarize, hf_token or load_hf_token()
        self.device = device or default_device()
        self._proc: Optional[subprocess.Popen] = None
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def run(self, log: Log = print) -> Optional[Path]:
        if not _has_module("whisperx"):
            raise RuntimeError("WhisperX no está instalado")
        if self.diarize and not self.hf_token:
            log("Falta el token de Hugging Face (gratis, botón '¿Qué es?').")
            log("Sin token de Hugging Face: se desactiva la identificación de hablantes.")
            self.diarize = False
        compute = "float16" if self.device == "cuda" else "int8"
        cmd = [PYTHON, "-m", "whisperx", str(self.audio), "--model", self.model,
               "--language", self.language, "--device", self.device, "--compute_type", compute,
               "--output_dir", str(self.audio.parent), "--output_format", "json",
               "--vad_onset", "0.500"]
        if self.diarize:
            cmd += ["--diarize", "--hf_token", self.hf_token]
        log(f"Modelo {self.model} en {self.device} ({compute})"
            f"{' + hablantes' if self.diarize else ''}. Esto puede tardar ...")
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, encoding="utf-8", errors="replace",
                                      env=prepare_env(), creationflags=_no_window())
        assert self._proc.stdout
        for line in self._proc.stdout:
            line = line.rstrip()
            if self.hf_token:
                line = line.replace(self.hf_token, "hf_***")
            log(line)
        rc = self._proc.wait()
        if self._cancelled:
            log("Transcripción cancelada.")
            return None
        if rc != 0:
            raise RuntimeError(f"WhisperX terminó con código {rc}")
        json_file = self.audio.with_suffix(".json")
        md_file = self.audio.with_suffix(".md")
        if not json_file.exists():
            raise RuntimeError("WhisperX no generó el .json")
        json_to_markdown(json_file, md_file)
        log(f"Listo: {md_file}")
        return md_file


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if IS_WIN:
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
