"""Modül 7 — orchestrator (Faz 1 sürümü)

Pipeline'ı sırayla çalıştırır. Faz 1'de yalnızca:
    news_collector → script_writer

Sonraki fazlarda voice → assembler → publishers eklenecek.

Kullanım:
    python orchestrator.py --dry-run                 # senaryoya kadar üret
    python orchestrator.py --date 2026-06-15 --dry-run
    python orchestrator.py --test-mode worldcup --dry-run   # (Faz 3 placeholder)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from modules import news_collector, script_writer, voice_generator, audio_assembler
from utils import db
from utils.claude_client import usage_summary
from utils.logging_utils import get_logger

log = get_logger("orchestrator")


def run(date_str: str, dry_run: bool, test_mode: str | None, episode: int = 1) -> int:
    log.info("=== Future with Serdar — pipeline başlıyor (date=%s, dry_run=%s, test_mode=%s) ===",
             date_str, dry_run, test_mode)

    if test_mode:
        log.warning("test_mode='%s' Faz 3'te uygulanacak; Faz 1'de normal akış çalışır.", test_mode)

    # 1) Haber toplama + puanlama + seçim
    try:
        news = news_collector.collect(date_str)
    except Exception as e:  # noqa: BLE001
        log.error("news_collector hata verdi: %s", e)
        db.log_step(date_str, "news_collector", "error", error_message=str(e))
        return 1

    # 2) Senaryo
    try:
        episode = script_writer.write_script(date_str)
    except Exception as e:  # noqa: BLE001
        log.error("script_writer hata verdi: %s", e)
        db.log_step(date_str, "script_writer", "error", error_message=str(e))
        return 1

    # Maliyet logu (CLAUDE.md)
    usage = usage_summary()
    log.info("Claude token kullanımı: girdi=%d, çıktı=%d",
             usage["input_tokens"], usage["output_tokens"])

    print("\n" + "=" * 70)
    print(f"✅ {episode['title']}")
    print(f"   {episode['_meta']['word_count']} kelime | {news['selected_count']} haber "
          f"| slow_day={news['slow_day']}")
    print("=" * 70)

    if dry_run:
        log.info("--dry-run: ses ve sonraki adımlar atlandı. Senaryo hazır.")
        print("\nSenaryo dosyası: output/%s/script.json" % date_str.replace("-", ""))
        print("İnsana göster ve ton onayı al (Faz 1 kabul kriteri).")
        return 0

    # 3) Seslendirme (ElevenLabs)
    try:
        voice = voice_generator.generate_voice(date_str)
    except Exception as e:  # noqa: BLE001
        log.error("voice_generator hata verdi: %s", e)
        db.log_step(date_str, "voice_generator", "error", error_message=str(e))
        return 1

    # 4) Montaj (podcast MP3 + YouTube MP4)
    try:
        media = audio_assembler.assemble(date_str, episode_no=episode)
    except Exception as e:  # noqa: BLE001
        log.error("audio_assembler hata verdi: %s", e)
        db.log_step(date_str, "audio_assembler", "error", error_message=str(e))
        return 1

    dur = media["duration_sec"]
    print("\n" + "=" * 70)
    print(f"🎧 {media['title']}")
    print(f"   Süre: {dur:.0f} sn (~{dur/60:.1f} dk) | "
          f"ElevenLabs: {voice['char_count']} karakter")
    print(f"   Podcast: {media['podcast_mp3']}")
    print(f"   YouTube: {media['video_mp4']}")
    if media.get("short_mp4"):
        print(f"   Shorts:  {media['short_mp4']}")
    print("=" * 70)

    # Süre kontrolü (CLAUDE.md: < 5 dk veya > 10 dk uyarı)
    if dur < 300 or dur > 600:
        log.warning("Süre hedef dışı (%.1f dk). İdeal: 5-10 dk.", dur / 60)

    log.warning("Yayın adımları (podcast/youtube publisher) Faz 3'te eklenecek.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Future with Serdar — pipeline orkestratörü")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                    help="YYYY-MM-DD (varsayılan: bugün)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Senaryo üret, ses üretme (Faz 1 ana mod)")
    ap.add_argument("--test-mode", choices=["worldcup"], default=None,
                    help="Markasız test bölümü modu (Faz 3'te aktif)")
    ap.add_argument("--episode", type=int, default=1, help="Bölüm numarası (varsayılan: 1)")
    args = ap.parse_args()
    sys.exit(run(args.date, args.dry_run, args.test_mode, args.episode))


if __name__ == "__main__":
    main()
