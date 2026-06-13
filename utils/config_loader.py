"""config.yaml + .env yükleyici. Tek giriş noktası: load_config() / get_env()."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import yaml
from dotenv import load_dotenv

from .paths import CONFIG_PATH

# .env dosyasını bir kez yükle (varsa)
load_dotenv()


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    """config.yaml içeriğini sözlük olarak döndürür."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_env(key: str, default: str | None = None) -> str | None:
    """Ortam değişkeni okur. Boş string'i 'yok' sayar."""
    val = os.environ.get(key, default)
    if val is not None and val.strip() == "":
        return default
    return val


def require_env(key: str) -> str:
    """Zorunlu ortam değişkeni — yoksa anlaşılır hata fırlatır."""
    val = get_env(key)
    if not val:
        raise RuntimeError(
            f"Gerekli ortam değişkeni eksik: {key}. "
            f".env dosyasını kontrol edin (örnek: .env.example)."
        )
    return val
