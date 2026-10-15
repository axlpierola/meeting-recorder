"""Gestión de reuniones ya grabadas: renombrar, borrar (a la Papelera) y datos opcionales (cliente, participantes)."""
from __future__ import annotations

import ctypes
import glob
import json
import re
from pathlib import Path
from typing import Optional

from . import core

_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})(?:_(.*))?$")


class LibraryError(RuntimeError):
    pass


def split_stem(stem: str) -> tuple[str, str]:
    """('2026-10-14_10-09-50', 'Prueba_whatsapp'). Sin marca de tiempo: ('', stem)."""
    m = _STAMP.match(stem)
    return (m[1], m[2] or "") if m else ("", stem)


def display_name(audio: Path) -> str:
    return split_stem(audio.stem)[1].replace("_", " ")


def companions(audio: Path) -> list[Path]:
    """Todos los archivos de la reunión: audio, .json, .md, .resumen.md, .meta.json, pistas crudas."""
    found = {audio}
    for p in audio.parent.glob(glob.escape(audio.stem) + ".*"):
        if p.is_file():
            found.add(p)
    return sorted(found)


# ------------------------------------------------------------------ datos
def meta_path(audio: Path) -> Path:
    return audio.with_name(audio.stem + ".meta.json")


def load_meta(audio: Path) -> dict:
    try:
        data = json.loads(meta_path(audio).read_text(encoding="utf-8"))
        return {"cliente": str(data.get("cliente", "")).strip(), "participantes": str(data.get("participantes", "")).strip()}
    except (OSError, ValueError):
        return {"cliente": "", "participantes": ""}


def save_meta(audio: Path, cliente: str, participantes: str) -> None:
    p = meta_path(audio)
    cliente, participantes = cliente.strip(), participantes.strip()
    if not cliente and not participantes:
        p.unlink(missing_ok=True)
        return
    p.write_text(json.dumps({"cliente": cliente, "participantes": participantes}, indent=2, ensure_ascii=False),
                 encoding="utf-8")


# --------------------------------------------------------------- renombrar
def rename_recording(audio: Path, new_name: str) -> Path:
    """Cambia la parte descriptiva del nombre conservando la fecha/hora. Renombra todos los archivos asociados."""
    stamp, old = split_stem(audio.stem)
    clean = core.clean_name(new_name)
    if not clean and not stamp:
        raise LibraryError("Escribe un nombre.")
    new_stem = stamp + (f"_{clean}" if clean and stamp else clean)
    if new_stem == audio.stem:
        return audio
    moves = []
    for p in companions(audio):
        target = p.with_name(new_stem + p.name[len(audio.stem):])
        if target.exists():
            raise LibraryError(f"Ya existe un archivo con ese nombre: {target.name}")
        moves.append((p, target))
    for src, dst in moves:
        src.rename(dst)
    return audio.with_name(new_stem + audio.suffix)


# ------------------------------------------------------------------ borrar
class _ShFileOp(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint), ("pFrom", ctypes.c_void_p),
                ("pTo", ctypes.c_void_p), ("fFlags", ctypes.c_ushort), ("aborted", ctypes.c_int),
                ("mappings", ctypes.c_void_p), ("title", ctypes.c_wchar_p)]


def _to_recycle_bin(paths: list[Path]) -> bool:
    buf = ctypes.create_unicode_buffer("\0".join(str(p) for p in paths) + "\0\0")
    op = _ShFileOp()
    op.wFunc = 3                 # FO_DELETE
    op.pFrom = ctypes.cast(buf, ctypes.c_void_p)
    op.fFlags = 0x40 | 0x10 | 0x400 | 0x4   # ALLOWUNDO | NOCONFIRMATION | NOERRORUI | SILENT
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return rc == 0 and not op.aborted


def delete_recording(audio: Path) -> tuple[int, bool]:
    """Envía todos los archivos de la reunión a la Papelera. Devuelve (cantidad, fue_a_papelera)."""
    files = companions(audio)
    if core.IS_WIN and _to_recycle_bin(files):
        return len(files), True
    for p in files:
        p.unlink(missing_ok=True)
    return len(files), False


def prune_empty_dirs() -> None:
    """Quita carpetas AAAA/MM/DD vacías para que la lista quede limpia."""
    root = core.OUTPUT_DIR
    for d in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()   # solo funciona si está vacía
        except OSError:
            pass
