"""Preferencias de la interfaz (modelo, idioma, tema, ...). Se guardan en config.json junto a la app."""
from __future__ import annotations

import json
from typing import Any

from . import core

CONFIG_FILE = core.APP_DIR / "config.json"


def load() -> dict[str, Any]:
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data: dict[str, Any]) -> None:
    try:
        CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # no es crítico: simplemente no se recuerdan las preferencias
