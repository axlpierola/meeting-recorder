"""Menú de terminal, equivalente a grabar.sh pero en Python."""
from __future__ import annotations

from pathlib import Path

from . import core


def _print_checks(checks) -> None:
    print("\nVerificación del entorno:")
    for c in checks:
        mark = "OK " if c.ok else ("FALTA" if c.required else "aviso")
        print(f"  [{mark}] {c.label}: {c.detail}")
        if not c.ok and c.fix:
            print(f"          -> {c.fix}")
    print()


def _ensure_ready() -> None:
    while True:
        checks = core.check_environment()
        _print_checks(checks)
        pending = [c for c in checks if not c.ok and c.action and c.required]
        if not pending:
            return
        if input("Faltan componentes que puedo instalar con pip. ¿Instalar ahora? [S/n]: ").strip().lower() in ("n", "no"):
            return
        core.install_audio_deps(print)


def _pick_devices():
    devs = core.list_audio_devices()
    loop, mic = devs["default_loopback"], devs["default_input"]
    return (loop["index"] if loop else None), (mic["index"] if mic else None), devs


def _choose_file() -> Path | None:
    files = core.list_recordings()
    if not files:
        print("No hay grabaciones.")
        return None
    for i, f in enumerate(files, 1):
        done = " [transcrito]" if f.with_suffix(".md").exists() else ""
        print(f"  {i}) {f.name}{done}")
    sel = input("Número o ruta completa: ").strip().strip('"')
    if sel.isdigit() and 1 <= int(sel) <= len(files):
        return files[int(sel) - 1]
    p = Path(sel)
    return p if p.is_file() else None


def _transcribe(path: Path) -> None:
    dev = core.default_device()
    print(f"\nDispositivo de cómputo: {dev}")
    for i, (m, d) in enumerate(core.MODELS.items(), 1):
        print(f"  {i}) {m} - {d}")
    default = "1" if dev == "cuda" else "2"
    sel = input(f"Modelo [{default}]: ").strip() or default
    model = list(core.MODELS)[int(sel) - 1] if sel.isdigit() and 1 <= int(sel) <= len(core.MODELS) else "medium"
    diarize = input("¿Identificar hablantes? (requiere HF_TOKEN) [s/N]: ").strip().lower() in ("s", "si", "sí", "y")
    token = ""
    if diarize and not core.os.environ.get("HF_TOKEN"):
        token = input("Pegá tu token de Hugging Face (Enter para omitir): ").strip()
        diarize = bool(token)
    try:
        core.Transcription(path, model, core.os.environ.get("GRABAR_LANG", "es"), diarize, token, dev).run(print)
    except Exception as e:
        print(f"[ERROR] {e}")


def main() -> None:
    print("=== Grabador + Transcriptor (Python) ===")
    _ensure_ready()
    rec = None
    while True:
        print("\n  1) Grabar\n  2) Parar grabación\n  3) Transcribir última grabación"
              "\n  4) Transcribir archivo específico\n  5) Importar video/audio (convertir a WAV)"
              "\n  6) Listar grabaciones\n  7) Ver dispositivos de audio\n  8) Verificar entorno\n  9) Salir")
        choice = input("  Opción: ").strip()
        try:
            if choice == "1":
                if rec and rec.active:
                    print("Ya hay una grabación en curso.")
                    continue
                loop, mic, _ = _pick_devices()
                rec = core.Recorder(loop, mic)
                out = rec.start(input("  Nombre (Enter = solo fecha/hora): "))
                print(f"Grabando -> {out}")
            elif choice == "2":
                if rec and rec.active:
                    secs = int(rec.elapsed())
                    out = rec.stop(print)
                    print(f"Guardado: {out} ({secs}s)")
                else:
                    print("No hay grabación activa.")
            elif choice == "3":
                files = core.list_recordings()
                if files:
                    _transcribe(files[0])
                else:
                    print("No hay grabaciones.")
            elif choice == "4":
                f = _choose_file()
                if f:
                    _transcribe(f)
            elif choice == "5":
                src = Path(input("Ruta del archivo: ").strip().strip('"'))
                print(f"Creado: {core.convert_to_wav(src, print)}")
            elif choice == "6":
                for f in core.list_recordings():
                    d = core.duration_seconds(f)
                    print(f"  {f.name} ({d if d is not None else '?'}s)"
                          f"{' [transcrito]' if f.with_suffix('.md').exists() else ''}")
            elif choice == "7":
                _, _, devs = _pick_devices()
                print("Salida del sistema (loopback):")
                for d in devs["loopbacks"]:
                    print(f"    {d['name']}")
                print("Micrófonos:")
                for d in devs["inputs"]:
                    print(f"    {d['name']}")
            elif choice == "8":
                _print_checks(core.check_environment())
            elif choice in ("9", "q", "Q"):
                if rec and rec.active:
                    rec.stop(print)
                return
        except Exception as e:
            print(f"[ERROR] {e}")
