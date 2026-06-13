"""Supabase sarmalayıcı — OPSİYONEL.

SUPABASE_URL / SUPABASE_SERVICE_KEY ayarlı değilse tüm işlemler sessizce
atlanır (no-op). Böylece --dry-run DB olmadan çalışır.
"""
from __future__ import annotations

from typing import Any

from .config_loader import get_env
from .logging_utils import get_logger

log = get_logger("db")

_client = None
_checked = False


def _get():
    """Supabase istemcisini (varsa) döndürür, yoksa None."""
    global _client, _checked
    if _checked:
        return _client
    _checked = True

    url = get_env("SUPABASE_URL")
    key = get_env("SUPABASE_SERVICE_KEY")
    if not url or not key:
        log.info("Supabase ayarlı değil — DB işlemleri atlanacak.")
        return None
    try:
        from supabase import create_client

        _client = create_client(url, key)
        log.info("Supabase bağlantısı hazır.")
    except Exception as e:  # noqa: BLE001
        log.warning("Supabase istemcisi kurulamadı (%s) — DB atlanacak.", e)
        _client = None
    return _client


def enabled() -> bool:
    return _get() is not None


def already_processed_urls(urls: list[str]) -> set[str]:
    """Verilen URL'lerden daha önce işlenmiş (used_in_episode dolu) olanları döndürür."""
    client = _get()
    if not client or not urls:
        return set()
    try:
        res = (
            client.table("news_items")
            .select("url")
            .in_("url", urls)
            .not_.is_("used_in_episode", "null")
            .execute()
        )
        return {row["url"] for row in (res.data or [])}
    except Exception as e:  # noqa: BLE001
        log.warning("already_processed_urls başarısız: %s", e)
        return set()


def upsert_news_items(items: list[dict[str, Any]]) -> None:
    """news_items tablosuna upsert (url unique)."""
    client = _get()
    if not client or not items:
        return
    try:
        client.table("news_items").upsert(items, on_conflict="url").execute()
        log.info("Supabase: %d haber kaydı yazıldı.", len(items))
    except Exception as e:  # noqa: BLE001
        log.warning("upsert_news_items başarısız: %s", e)


def upsert_episode(data: dict[str, Any]) -> int | None:
    """episodes tablosuna upsert (episode_number unique varsayımı). id döndürür."""
    client = _get()
    if not client:
        return None
    try:
        res = (client.table("episodes")
               .upsert(data, on_conflict="episode_number")
               .execute())
        if res.data:
            return res.data[0].get("id")
    except Exception as e:  # noqa: BLE001
        log.warning("upsert_episode başarısız: %s", e)
    return None


def list_published_episodes() -> list[dict[str, Any]]:
    """mp3_url'i dolu tüm bölümleri (yeni→eski) döndürür — RSS feed için."""
    client = _get()
    if not client:
        return []
    try:
        res = (client.table("episodes")
               .select("*")
               .not_.is_("mp3_url", "null")
               .order("episode_number", desc=True)
               .execute())
        return res.data or []
    except Exception as e:  # noqa: BLE001
        log.warning("list_published_episodes başarısız: %s", e)
        return []


def log_step(run_date: str, step: str, status: str,
             error_message: str | None = None, duration_sec: float | None = None) -> None:
    """pipeline_logs tablosuna bir adım kaydı yazar."""
    client = _get()
    if not client:
        return
    try:
        client.table("pipeline_logs").insert({
            "run_date": run_date,
            "step": step,
            "status": status,
            "error_message": error_message,
            "duration_sec": duration_sec,
        }).execute()
    except Exception as e:  # noqa: BLE001
        log.warning("log_step başarısız: %s", e)
