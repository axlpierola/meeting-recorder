"""Resumen de transcripciones con un LLM: Ollama (local) o APIs de Claude, Gemini y ChatGPT.
Solo usa la librería estándar (urllib): no hay que instalar SDKs."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import core

PROMPT_FILE = core.APP_DIR / "prompts" / "resumen.md"
KEYS_FILE = core.APP_DIR / ".api_keys.json"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"

Log = Callable[[str], None]


class SummaryError(RuntimeError):
    pass


# nombre visible -> configuración. Los modelos son sugerencias: el campo es editable.
PROVIDERS = {
    "Ollama (local, gratis)": {
        "id": "ollama", "needs_key": False, "models": ["qwen2.5:7b", "llama3.1:8b", "gemma2:9b"],
        "key_url": "https://ollama.com/download"},
    "Claude (Anthropic)": {
        "id": "claude", "needs_key": True, "models": ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"],
        "key_url": "https://console.anthropic.com/settings/keys"},
    "Gemini (Google)": {
        "id": "gemini", "needs_key": True, "models": ["gemini-2.5-flash", "gemini-2.5-pro"],
        "key_url": "https://aistudio.google.com/apikey"},
    "ChatGPT (OpenAI)": {
        "id": "openai", "needs_key": True, "models": ["gpt-4o-mini", "gpt-4o"],
        "key_url": "https://platform.openai.com/api-keys"},
}


# --------------------------------------------------------------------------
# API keys (archivo local ignorado por git)
# --------------------------------------------------------------------------
def load_key(provider_id: str) -> str:
    try:
        return json.loads(KEYS_FILE.read_text(encoding="utf-8")).get(provider_id, "").strip()
    except (OSError, ValueError):
        return ""


def save_key(provider_id: str, key: str) -> None:
    try:
        data = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if key.strip():
        data[provider_id] = key.strip()
    else:
        data.pop(provider_id, None)
    KEYS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def _post(url: str, payload: dict, headers: dict, timeout: int = 900) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            j = json.loads(body)
            detail = j.get("error", j)
            detail = detail.get("message", detail) if isinstance(detail, dict) else detail
        except ValueError:
            detail = body[:300]
        hints = {401: "La API key no es válida.", 403: "La API key no tiene permiso o la cuenta/región no está habilitada.",
                 404: "No se encontró el modelo: revisá el nombre.", 429: "Límite de uso o cuota agotada (revisá tu plan/saldo).",
                 400: "Solicitud rechazada (¿modelo inexistente o transcripción demasiado larga?)."}
        if "api key" in str(detail).lower() or "api_key" in str(detail).lower():
            e.code = 401  # Gemini responde 400 con una key inválida
        raise SummaryError(f"Error {e.code}: {hints.get(e.code, 'falló la solicitud')}\n\nDetalle del proveedor: {detail}") from None
    except urllib.error.URLError as e:
        raise SummaryError(f"No se pudo conectar ({e.reason}). Revisá tu internet o proxy.") from None
    except TimeoutError:
        raise SummaryError("El proveedor tardó demasiado en responder.") from None


# --------------------------------------------------------------------------
# Ollama (local)
# --------------------------------------------------------------------------
def _ollama_get(path: str, timeout: int = 5) -> dict:
    with urllib.request.urlopen(OLLAMA_URL + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ollama_models() -> Optional[list[str]]:
    """Modelos instalados, o None si el servidor de Ollama no responde."""
    try:
        return [m["name"] for m in _ollama_get("/api/tags").get("models", [])]
    except Exception:
        return None


def _ollama_exe() -> Optional[str]:
    exe = shutil.which("ollama")
    if exe:
        return exe
    local = os.environ.get("LOCALAPPDATA")
    if local:
        p = Path(local) / "Programs" / "Ollama" / "ollama.exe"
        if p.exists():
            return str(p)
    return None


def ensure_ollama(log: Log) -> list[str]:
    models = ollama_models()
    if models is not None:
        return models
    exe = _ollama_exe()
    if not exe:
        raise SummaryError("Ollama no está instalado. Descargalo gratis desde https://ollama.com/download "
                           "(instalador normal, sin administrador), ábrelo una vez y vuelve a pulsar Resumen.")
    log("Iniciando Ollama ...")
    subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=core._no_window())
    for _ in range(30):
        time.sleep(1)
        models = ollama_models()
        if models is not None:
            return models
    raise SummaryError("Ollama está instalado pero no arrancó. Ábrelo desde el menú Inicio y reintenta.")


OLLAMA_SETUP_URL = "https://ollama.com/download/OllamaSetup.exe"


def ollama_installed() -> bool:
    return _ollama_exe() is not None


def install_ollama(progress: Callable[[str, int, str], None], log: Log) -> None:
    """Descarga OllamaSetup.exe (~1.6 GB, se retoma si se corta) y lo instala en silencio.
    Es una instalación por usuario: no pide permisos de administrador."""
    if not core.IS_WIN:
        raise SummaryError("La instalación automática de Ollama solo está disponible en Windows. "
                           "En macOS/Linux: https://ollama.com/download")
    if ollama_installed():
        return
    dest_dir = core.APP_DIR / ".tools" / "ollama"
    dest_dir.mkdir(parents=True, exist_ok=True)
    setup = dest_dir / "OllamaSetup.exe"
    part = dest_dir / "OllamaSetup.exe.part"
    log("Descargando el instalador de Ollama (~1.6 GB, solo una vez; si se corta se retoma) ...")
    for attempt in range(1, 6):
        have = part.stat().st_size if part.exists() else 0
        headers = {"User-Agent": "Mozilla/5.0"}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            with urllib.request.urlopen(urllib.request.Request(OLLAMA_SETUP_URL, headers=headers), timeout=60) as r:
                resumed = r.status == 206
                total = int(r.headers.get("Content-Length", 0)) + (have if resumed else 0)
                done = have if resumed else 0
                with open(part, "ab" if resumed else "wb") as out:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        out.write(chunk)
                        done += len(chunk)
                        if total:
                            progress("Descargando Ollama", int(done * 100 / total),
                                     f"{done / 1e6:.0f} / {total / 1e6:.0f} MB")
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if attempt == 5:
                raise SummaryError(f"No se pudo descargar Ollama ({e}). Revisá tu internet y reintentá: "
                                   "la descarga continúa donde quedó.") from None
            log(f"Se cortó la descarga ({e}); reintentando ({attempt}/5) ...")
            time.sleep(3)
    if part.stat().st_size < 100_000_000 or part.read_bytes()[:2] != b"MZ":
        part.unlink(missing_ok=True)
        raise SummaryError("El instalador de Ollama descargado está incompleto o dañado. Reintentá.")
    part.replace(setup)
    progress("Instalando Ollama (puede tardar un minuto) ...", -1, "")
    log("Instalando Ollama ...")
    r = subprocess.run([str(setup), "/SILENT", "/NORESTART", "/SUPPRESSMSGBOXES"], timeout=900)
    if r.returncode != 0 or not ollama_installed():
        raise SummaryError(f"La instalación de Ollama falló (código {r.returncode}). "
                           f"Podés ejecutarla a mano: {setup}")
    setup.unlink(missing_ok=True)
    log("✔ Ollama instalado.")


def setup_ollama(model: str, progress: Callable[[str, int, str], None], log: Log) -> None:
    """Deja Ollama listo: lo instala si falta, lo inicia y descarga el modelo si no está."""
    install_ollama(progress, log)
    models = ensure_ollama(log)
    if not any(m == model or m == f"{model}:latest" for m in models):
        pull_model(model, progress, log)


def pull_model(model: str, progress: Callable[[str, int, str], None], log: Log) -> None:
    """Descarga un modelo de Ollama mostrando el avance (estado, %, 'X / Y MB')."""
    log(f"Descargando el modelo {model} (solo la primera vez, ~5 GB) ...")
    req = urllib.request.Request(OLLAMA_URL + "/api/pull", method="POST",
                                 data=json.dumps({"model": model, "stream": True}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            for raw in r:
                j = json.loads(raw.decode("utf-8"))
                if "error" in j:
                    raise SummaryError(f"Ollama no pudo descargar '{model}': {j['error']}")
                total, done = j.get("total"), j.get("completed")
                if total and done is not None:
                    progress(j.get("status", ""), int(done * 100 / total), f"{done / 1e6:.0f} / {total / 1e6:.0f} MB")
                else:
                    progress(j.get("status", ""), -1, "")
    except urllib.error.HTTPError as e:
        raise SummaryError(f"Ollama no pudo descargar '{model}' (error {e.code}). ¿El nombre es correcto?") from None
    except urllib.error.URLError as e:
        raise SummaryError(f"Falló la descarga del modelo ({e.reason}). Revisá tu internet.") from None


def _ask_ollama(model: str, prompt: str) -> str:
    # El contexto por defecto de Ollama (4k) cortaría la transcripción: se ajusta al tamaño del prompt.
    need = int(len(prompt) / 3) + 2500
    num_ctx = next((n for n in (8192, 16384, 32768) if need <= n), 32768)
    j = _post(OLLAMA_URL + "/api/chat", {
        "model": model, "stream": False, "messages": [{"role": "user", "content": prompt}],
        "options": {"num_ctx": num_ctx, "temperature": 0.2}}, {}, timeout=3600)
    return j.get("message", {}).get("content", "")


# --------------------------------------------------------------------------
# APIs en la nube
# --------------------------------------------------------------------------
def _ask_claude(model: str, key: str, prompt: str) -> str:
    j = _post("https://api.anthropic.com/v1/messages",
              {"model": model, "max_tokens": 4096, "temperature": 0.2,
               "messages": [{"role": "user", "content": prompt}]},
              {"x-api-key": key, "anthropic-version": "2023-06-01"})
    return "".join(b.get("text", "") for b in j.get("content", []))


def _ask_gemini(model: str, key: str, prompt: str) -> str:
    j = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
              {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2}},
              {"x-goog-api-key": key})
    cands = j.get("candidates") or []
    if not cands:
        raise SummaryError(f"Gemini no devolvió texto: {j.get('promptFeedback', j)}")
    return "".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", []))


def _ask_openai(model: str, key: str, prompt: str) -> str:
    j = _post("https://api.openai.com/v1/chat/completions",
              {"model": model, "temperature": 0.2, "messages": [{"role": "user", "content": prompt}]},
              {"Authorization": f"Bearer {key}"})
    return j["choices"][0]["message"]["content"]


# --------------------------------------------------------------------------
# Resumen
# --------------------------------------------------------------------------
def build_prompt(transcript_md: Path) -> str:
    if not PROMPT_FILE.exists():
        raise SummaryError(f"Falta el archivo del prompt: {PROMPT_FILE}")
    text = transcript_md.read_text(encoding="utf-8")
    text = text.replace("# Transcripción de Audio", "").strip()
    return PROMPT_FILE.read_text(encoding="utf-8").replace("{{TRANSCRIPCION}}", text)


def summary_path(transcript_md: Path) -> Path:
    return transcript_md.with_suffix(".resumen.md")


def summarize(transcript_md: Path, provider_id: str, model: str, key: str, log: Log = print) -> Path:
    model = model.strip()
    if not model:
        raise SummaryError("Indicá el modelo a usar.")
    if provider_id != "ollama" and not key:
        raise SummaryError("Falta la API key de este proveedor (campo 'API key').")
    prompt = build_prompt(transcript_md)
    log(f"Generando resumen con {provider_id}/{model} ...")
    if provider_id == "ollama":
        text = _ask_ollama(model, prompt)
    elif provider_id == "claude":
        text = _ask_claude(model, key, prompt)
    elif provider_id == "gemini":
        text = _ask_gemini(model, key, prompt)
    elif provider_id == "openai":
        text = _ask_openai(model, key, prompt)
    else:
        raise SummaryError(f"Proveedor desconocido: {provider_id}")
    text = text.strip()
    if not text:
        raise SummaryError("El modelo devolvió una respuesta vacía. Probá con otro modelo.")
    out = summary_path(transcript_md)
    header = (f"# Resumen de reunión\n\n_Fuente: {transcript_md.name} · Generado con {provider_id}/{model} "
              f"el {datetime.now():%Y-%m-%d %H:%M}_\n\n")
    out.write_text(header + text + "\n", encoding="utf-8")
    return out
