"""Yerel bölüm kaydı (episodes.json) — RSS feed'in kaynağı.

Supabase olmadan tüm yayınlanmış bölümleri takip eder. GitHub'a commit
edildiğinde otomasyon ortamında da kalıcı olur.
"""
from __future__ import annotations

import json
from pathlib import Path

from .paths import ROOT

REGISTRY_PATH = ROOT / "episodes.json"


def load() -> list[dict]:
    if not REGISTRY_PATH.exists():
        return []
    try:
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def upsert(episode: dict) -> list[dict]:
    """Bölümü episode_number'a göre ekler/günceller, yeni→eski sıralı kaydeder."""
    eps = [e for e in load() if e.get("episode_number") != episode.get("episode_number")]
    eps.append(episode)
    eps.sort(key=lambda e: e.get("episode_number", 0), reverse=True)
    REGISTRY_PATH.write_text(
        json.dumps(eps, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return eps
