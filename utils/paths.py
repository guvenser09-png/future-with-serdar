"""Proje yolları ve günlük çıktı klasörü yönetimi."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = ROOT / "output"
CONFIG_PATH = ROOT / "config.yaml"
PRONUNCIATION_PATH = ROOT / "pronunciation_map.json"


def output_dir(date_str: str) -> Path:
    """output/YYYYMMDD/ klasörünü (yoksa oluşturarak) döndürür.

    date_str 'YYYY-MM-DD' formatında beklenir; klasör adında tireler atılır.
    """
    folder = OUTPUT_ROOT / date_str.replace("-", "")
    folder.mkdir(parents=True, exist_ok=True)
    return folder
