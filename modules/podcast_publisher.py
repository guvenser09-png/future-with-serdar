"""Modül 5 — podcast_publisher (Faz 3)

Bölüm MP3'ünü Supabase Storage'a yükler, episodes tablosunu günceller ve
RSS 2.0 + iTunes feed'ini (feed.xml) yeniden üretip yayınlar.

- MP3 + kapak → public bucket
- feed.xml → sabit public URL (Spotify/Apple bu URL'i izler)
- Bölüm episodes tablosuna işlenir

Bağımsız çalıştırma:
    python -m modules.podcast_publisher --date 2026-06-12 --episode 1
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

from utils import db, storage, registry
from utils.config_loader import load_config, get_env
from utils.logging_utils import get_logger
from utils.paths import output_dir, OUTPUT_ROOT

log = get_logger("podcast")

OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
ROOT_TMP_COVER = OUTPUT_ROOT / "show_cover.jpg"

TR_TZ = timezone(timedelta(hours=3))  # TSİ


def _hhmmss(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _build_feed(meta: dict, brand: str, author: str, cover_url: str,
                feed_self_url: str, episodes: list[dict]) -> bytes:
    """episodes listesinden RSS 2.0 + iTunes feed üretir."""
    now = format_datetime(datetime.now(TR_TZ))
    items_xml = []
    for ep in episodes:
        # pubDate: bölüm tarihi 08:30 TSİ
        try:
            d = datetime.strptime(ep["date"], "%Y-%m-%d").replace(
                hour=8, minute=30, tzinfo=TR_TZ)
            pub = format_datetime(d)
        except Exception:  # noqa: BLE001
            pub = now
        dur = _hhmmss(ep.get("duration_sec") or 0)
        guid = f"fws-ep-{ep.get('episode_number')}"
        mp3 = ep.get("mp3_url", "")
        length = ep.get("mp3_bytes") or 0
        items_xml.append(f"""    <item>
      <title>{escape(ep.get('title',''))}</title>
      <description>{escape(ep.get('description',''))}</description>
      <enclosure url="{escape(mp3)}" length="{length}" type="audio/mpeg"/>
      <guid isPermaLink="false">{guid}</guid>
      <pubDate>{pub}</pubDate>
      <itunes:author>{escape(author)}</itunes:author>
      <itunes:duration>{dur}</itunes:duration>
      <itunes:episode>{ep.get('episode_number','')}</itunes:episode>
      <itunes:explicit>{'yes' if meta.get('explicit') else 'no'}</itunes:explicit>
    </item>""")

    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{escape(brand)}</title>
    <link>{escape(meta.get('link',''))}</link>
    <atom:link href="{escape(feed_self_url)}" rel="self" type="application/rss+xml"/>
    <language>{meta.get('language','tr')}</language>
    <description>{escape(meta.get('description','').strip())}</description>
    <itunes:author>{escape(author)}</itunes:author>
    <itunes:subtitle>{escape(meta.get('subtitle',''))}</itunes:subtitle>
    <itunes:summary>{escape(meta.get('description','').strip())}</itunes:summary>
    <itunes:keywords>{escape(','.join(meta.get('keywords', [])))}</itunes:keywords>
    <itunes:type>episodic</itunes:type>
    <itunes:explicit>{'yes' if meta.get('explicit') else 'no'}</itunes:explicit>
    <itunes:image href="{escape(cover_url)}"/>
    <itunes:category text="{escape(meta.get('category','Technology'))}"/>
    <itunes:owner>
      <itunes:name>{escape(author)}</itunes:name>
      <itunes:email>{escape(meta.get('email',''))}</itunes:email>
    </itunes:owner>
    <lastBuildDate>{now}</lastBuildDate>
{chr(10).join(items_xml)}
  </channel>
</rss>
"""
    return feed.encode("utf-8")


def publish_podcast(date_str: str, episode_no: int = 1) -> dict:
    cfg = load_config()
    meta = cfg.get("podcast_meta", {})
    brand = get_env("PODCAST_TITLE", "Future with Serdar")
    author = get_env("PODCAST_AUTHOR", "Serdar")

    if not storage.configured():
        raise RuntimeError(
            "GitHub Pages ayarlı değil. .env'e PAGES_BASE_URL, GITHUB_TOKEN, "
            "GITHUB_USER, GITHUB_REPO ekleyin."
        )

    out_dir = output_dir(date_str)
    nnn = f"{episode_no:03d}"
    mp3 = out_dir / f"episode_{nnn}.mp3"
    cover = out_dir / "cover.jpg"
    script_path = out_dir / "script.json"
    for p in (mp3, cover, script_path):
        if not p.exists():
            raise FileNotFoundError(f"{p} yok. Önce montaj (audio_assembler) çalıştırın.")

    data = json.loads(script_path.read_text(encoding="utf-8"))
    import subprocess
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(mp3)],
        capture_output=True, text=True).stdout.strip() or 0)

    storage.ensure_bucket()

    # 1) MP3 + kapak yükle
    log.info("MP3 yükleniyor (%d bölüm)...", episode_no)
    mp3_url = storage.upload(dest_path=f"episodes/episode_{nnn}.mp3",
                             local_path=mp3, content_type="audio/mpeg")
    cover_url = storage.upload(dest_path="cover.jpg",
                               local_path=cover, content_type="image/jpeg")
    log.info("MP3 → %s", mp3_url)

    # 2) Yerel bölüm kaydını güncelle (feed kaynağı) + DB'ye de yaz (varsa)
    episode_row = {
        "episode_number": episode_no,
        "date": date_str,
        "title": data["title"],
        "description": data.get("description", ""),
        "duration_sec": int(dur),
        "mp3_url": mp3_url,
        "mp3_bytes": mp3.stat().st_size,
    }
    episodes = registry.upsert(episode_row)
    db.upsert_episode({**episode_row, "status": "published"})

    # 3) feed.xml üret + yükle
    feed_self_url = storage._public_url("feed.xml")
    feed_bytes = _build_feed(meta, brand, author, cover_url, feed_self_url, episodes)
    # Yerel kopya (doğrulama için)
    (out_dir / "feed.xml").write_bytes(feed_bytes)
    feed_url = storage.upload_bytes("feed.xml", feed_bytes, "application/rss+xml")

    # Bu bölümde kullanılan haberleri "işlenmiş" işaretle (tekrar yayınlanmasın)
    news_path = out_dir / "daily_news.json"
    if news_path.exists():
        news = json.loads(news_path.read_text(encoding="utf-8"))
        used_urls = [item.get("url") for item in news.get("selected", []) if item.get("url")]
        registry.mark_processed(used_urls)
        log.info("%d haber 'işlenmiş' olarak kaydedildi.", len(used_urls))

    # 4) Her şeyi GitHub'a push et (Pages yayınlar)
    storage.push_site(f"Bölüm {episode_no} yayınla ({date_str})")

    log.info("RSS feed yayınlandı → %s", feed_url)
    db.log_step(date_str, "podcast_publisher", "ok", duration_sec=dur)
    return {
        "mp3_url": mp3_url,
        "cover_url": cover_url,
        "feed_url": feed_url,
        "episode_count": len(episodes),
    }


def refresh_feed() -> dict:
    """Yeni bölüm üretmeden kanal kapağını + feed.xml'i günceller ve yayınlar.

    Marka/açıklama (config.yaml > podcast_meta) değiştiğinde kullanılır.
    """
    cfg = load_config()
    meta = cfg.get("podcast_meta", {})
    brand = get_env("PODCAST_TITLE", "Future with Serdar")
    author = get_env("PODCAST_AUTHOR", "Serdar")
    if not storage.configured():
        raise RuntimeError("GitHub Pages ayarlı değil (.env: PAGES_BASE_URL vb.).")

    storage.ensure_bucket()

    # Kanal kapağı (markaya özel) üret + yükle
    from modules.audio_assembler import make_show_cover
    tmp_cover = ROOT_TMP_COVER
    make_show_cover(tmp_cover, meta.get("subtitle", ""))
    cover_url = storage.upload(dest_path="cover.jpg", local_path=tmp_cover,
                              content_type="image/jpeg")

    episodes = registry.load()
    feed_self_url = storage._public_url("feed.xml")
    feed_bytes = _build_feed(meta, brand, author, cover_url, feed_self_url, episodes)
    feed_url = storage.upload_bytes("feed.xml", feed_bytes, "application/rss+xml")
    storage.push_site("Kanal bilgileri / feed güncellendi")
    log.info("Feed güncellendi → %s", feed_url)
    return {"feed_url": feed_url, "cover_url": cover_url, "episode_count": len(episodes)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Future with Serdar — podcast yayıncısı")
    ap.add_argument("--refresh-feed", action="store_true",
                    help="Yeni bölüm üretmeden kanal kapağı + feed'i güncelle")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--episode", type=int, default=1)
    args = ap.parse_args()

    if args.refresh_feed:
        r = refresh_feed()
        print("\n=== FEED GÜNCELLENDİ ===")
        print(f"  Feed: {r['feed_url']}")
        print(f"  Kapak: {r['cover_url']}")
        print(f"  Bölüm sayısı: {r['episode_count']}")
        return

    res = publish_podcast(args.date, args.episode)
    print("\n=== PODCAST YAYINLANDI ===")
    print(f"  MP3:  {res['mp3_url']}")
    print(f"  Feed: {res['feed_url']}")
    print(f"  Bölüm sayısı: {res['episode_count']}")
    print("\n👉 Bu feed URL'ini Spotify for Creators ve Apple Podcasts Connect'e gir.")


if __name__ == "__main__":
    main()
