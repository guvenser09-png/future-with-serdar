"""Modül 7 — orchestrator

Pipeline'ı sırayla çalıştırır.

Akışlar:
  collector → writer                          (--dry-run: burada durur)
  → voice → assembler                         (ses + montaj)
  → podcast_publisher                         (--publish: podcast yayını)

Kullanım:
    python orchestrator.py --dry-run                  # senaryoya kadar
    python orchestrator.py --episode 1                # ses + montaj (video dahil)
    python orchestrator.py --publish                  # podcast üret + yayınla (sadece ses)
    python orchestrator.py --publish --date 2026-06-15

YouTube videosu otomasyona dahil DEĞİL (manuel): modules.youtube_publisher --export
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from modules import news_collector, script_writer, voice_generator, audio_assembler
from utils import db, registry
from utils.claude_client import usage_summary
from utils.logging_utils import get_logger

log = get_logger("orchestrator")


def _next_episode_number() -> int:
    eps = registry.load()
    if not eps:
        return 1
    return max((e.get("episode_number", 0) for e in eps), default=0) + 1


def run(date_str: str, dry_run: bool, test_mode: str | None,
        episode: int | None, publish: bool, audio_only: bool) -> int:
    # Aynı gün mükerrer yayını engelle (GitHub cron gecikmesi / çift tetikleme koruması)
    if publish and any(e.get("date") == date_str for e in registry.load()):
        log.info("Bugün (%s) zaten bir bölüm yayınlanmış — atlanıyor (ElevenLabs harcanmaz).",
                 date_str)
        return 0

    episode = episode or _next_episode_number()
    log.info("=== Future with Serdar — pipeline (date=%s, ep=%s, dry_run=%s, publish=%s) ===",
             date_str, episode, dry_run, publish)
    if test_mode:
        log.warning("test_mode='%s' Faz 3 ilerisinde uygulanacak.", test_mode)

    # 1) Haber toplama + puanlama + seçim
    try:
        news = news_collector.collect(date_str)
    except Exception as e:  # noqa: BLE001
        log.error("news_collector hata: %s", e)
        db.log_step(date_str, "news_collector", "error", error_message=str(e))
        return 1

    # 2) Senaryo
    try:
        episode_data = script_writer.write_script(date_str)
    except Exception as e:  # noqa: BLE001
        log.error("script_writer hata: %s", e)
        db.log_step(date_str, "script_writer", "error", error_message=str(e))
        return 1

    usage = usage_summary()
    log.info("Claude token: girdi=%d, çıktı=%d", usage["input_tokens"], usage["output_tokens"])

    if dry_run:
        log.info("--dry-run: ses/yayın atlandı. Senaryo hazır: output/%s/script.json",
                 date_str.replace("-", ""))
        return 0

    # 3) Seslendirme
    try:
        voice = voice_generator.generate_voice(date_str)
    except Exception as e:  # noqa: BLE001
        log.error("voice_generator hata: %s", e)
        db.log_step(date_str, "voice_generator", "error", error_message=str(e))
        return 1

    # 4) Montaj (podcast için sadece ses; video isteniyorsa audio_only=False)
    try:
        media = audio_assembler.assemble(date_str, episode_no=episode, audio_only=audio_only)
    except Exception as e:  # noqa: BLE001
        log.error("audio_assembler hata: %s", e)
        db.log_step(date_str, "audio_assembler", "error", error_message=str(e))
        return 1

    dur = media["duration_sec"]
    if dur < 300 or dur > 600:
        log.warning("Süre hedef dışı (%.1f dk). İdeal 5-10 dk.", dur / 60)

    # 5) Podcast yayını
    feed_url = None
    if publish:
        try:
            from modules import podcast_publisher
            pub = podcast_publisher.publish_podcast(date_str, episode)
            feed_url = pub["feed_url"]
        except Exception as e:  # noqa: BLE001
            log.error("podcast_publisher hata: %s", e)
            db.log_step(date_str, "podcast_publisher", "error", error_message=str(e))
            return 1

    print("\n" + "=" * 70)
    print(f"✅ {media['title']}")
    print(f"   Süre: {dur:.0f}s (~{dur/60:.1f} dk) | {news['selected_count']} haber "
          f"| ElevenLabs: {voice['char_count']} karakter")
    print(f"   Podcast MP3: {media['podcast_mp3']}")
    if feed_url:
        print(f"   Feed: {feed_url}")
    if media.get("video_mp4"):
        print(f"   Video: {media['video_mp4']}")
    print("=" * 70)

    # Bildirim (opsiyonel — Telegram ayarlıysa)
    try:
        from utils import notify
        notify.send(
            f"✅ Bölüm {episode} hazır — {dur/60:.1f} dk — {news['selected_count']} haber"
            + (f"\nFeed: {feed_url}" if feed_url else "")
        )
    except Exception as e:  # noqa: BLE001
        log.debug("Bildirim atlandı: %s", e)

    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Future with Serdar — pipeline orkestratörü")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--dry-run", action="store_true", help="Senaryo üret, ses üretme")
    ap.add_argument("--publish", action="store_true", help="Podcast'i üret ve yayınla")
    ap.add_argument("--episode", type=int, default=None,
                    help="Bölüm no (varsayılan: otomatik = son+1)")
    ap.add_argument("--with-video", action="store_true",
                    help="Montajda YouTube videosu da üret (yayın hariç)")
    ap.add_argument("--test-mode", choices=["worldcup"], default=None)
    args = ap.parse_args()
    # Yayın modunda varsayılan: sadece ses (hızlı). --with-video ile video da üretilir.
    audio_only = not args.with_video
    sys.exit(run(args.date, args.dry_run, args.test_mode,
                 args.episode, args.publish, audio_only))


if __name__ == "__main__":
    main()
