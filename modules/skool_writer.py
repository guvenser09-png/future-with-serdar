"""Modül — skool_writer

Bölüm içeriğinden Skool topluluk duyurusu üretir (kopyala-yapıştır formatı).
Kullanıcı Skool'da başlığı kendisi giriyor ("Günlük yapay zeka haberleri");
bu modül yalnızca gövde metnini üretir.

- Yayın sırasında podcast_publisher çağırır; HATA YAYININ ÖNÜNÜ KESMEZ.
- Malzeme önceliği: output/<tarih>/script.json (tam senaryo) → yoksa
  episodes.json'daki başlık+açıklama (bulut bölümleri için yeterli).
- Çıktılar: output/<tarih>/skool.md, docs/skool/episode_NNN.md,
  docs/skool/latest.md, docs/skool/latest.json (bildirim görevi bunu izler).

Bağımsız çalıştırma:
    python -m modules.skool_writer --date 2026-09-15 --episode 59
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

from pydantic import BaseModel, Field

from utils.claude_client import parse as claude_parse
from utils.config_loader import load_config
from utils import registry
from utils.logging_utils import get_logger
from utils.paths import output_dir
from utils.storage import DOCS_DIR

log = get_logger("skool")


class SkoolPost(BaseModel):
    post: str = Field(description="Skool duyurusunun gövde metni (başlıksız, kopyala-yapıştır)")


SKOOL_SYSTEM = """Sen "Future with Serdar" adlı Türkçe günlük yapay zeka podcast'inin topluluk editörüsün.
Sana bir bölümün içeriği verilecek; Skool topluluğuna girilecek KISA duyuru gövdesini yazacaksın.

FORMAT (sıkı uy):
- BAŞLIK YAZMA — kullanıcı başlığı Skool'da kendisi giriyor.
- 1 kanca cümleyle başla (günün en çarpıcı gelişmesi, merak uyandır, clickbait yapmadan).
- Her haber için bir blok: emoji + **kalın mini başlık** + 1-2 cümle ne oldu + 1 cümle
  "senin için anlamı" (pratik çıkarım). Haber sayısı malzemedeki kadar (genelde 3).
- Sonda topluluğa TEK kısa soru (tartışma başlatsın).
- Toplam 130-200 kelime. Konuşma Türkçesi, samimi ama profesyonel.
- ŞAPKALI HARF KULLANMA (â/î/û yok): "zeka", "adeta" diye düz yaz.
- Abartı/clickbait yok; doğrulanmamış iddiayı "iddia" olarak işaretle.
- Dinleme linki EKLEME — o kısım koda ait, sen sadece gövdeyi yaz."""


def _material(date_str: str, episode_no: int) -> tuple[str, str]:
    """(başlık, malzeme) döndürür: tam senaryo varsa onu, yoksa kayıttan açıklamayı."""
    script_path = output_dir(date_str) / "script.json"
    if script_path.exists():
        data = json.loads(script_path.read_text(encoding="utf-8"))
        return data.get("title", ""), data.get("script", "")
    for ep in registry.load():
        if ep.get("episode_number") == episode_no:
            return ep.get("title", ""), ep.get("description", "")
    raise FileNotFoundError(
        f"Bölüm {episode_no} için ne script.json ne episodes.json kaydı bulundu.")


def _links_block(cfg: dict) -> str:
    """Dinleme linkleri — model değil kod üretir (uydurma URL riski olmasın)."""
    meta = cfg.get("podcast_meta", {})
    lines = ["🎧 Bölümün tamamı (3-4 dk):"]
    spotify = meta.get("spotify_url", "").strip()
    apple = meta.get("apple_url", "").strip()
    if spotify:
        lines.append(f"▶️ Spotify: {spotify}")
    if apple:
        lines.append(f"🍎 Apple Podcasts: {apple}")
    if not (spotify or apple):
        lines.append('Spotify ve Apple Podcasts\'te "Future with Serdar" aratman yeterli.')
    return "\n".join(lines)


def generate_skool_post(date_str: str, episode_no: int) -> str:
    """Skool duyuru metnini üretir, dosyalara yazar ve metni döndürür."""
    cfg = load_config()
    title, material = _material(date_str, episode_no)
    if not material.strip():
        raise RuntimeError("Duyuru için malzeme boş.")

    user = (f"Bölüm {episode_no} — {title}\n\n"
            f"BÖLÜM İÇERİĞİ:\n{material[:6000]}\n\n"
            "Bu içerikten Skool duyuru gövdesini üret.")
    result = claude_parse(
        model=cfg["model"]["script"],
        system=SKOOL_SYSTEM,
        user=user,
        schema=SkoolPost,
        max_tokens=1500,
    )
    post = result.post.strip() + "\n\n" + _links_block(cfg) + \
        "\n\n🤖 Bu bülten, kendi geliştirdiğim yapay zeka sistemi tarafından otomatik üretildi."

    # Dosyalara yaz
    out = output_dir(date_str) / "skool.md"
    out.write_text(post, encoding="utf-8")
    skool_dir = DOCS_DIR / "skool"
    skool_dir.mkdir(parents=True, exist_ok=True)
    (skool_dir / f"episode_{episode_no:03d}.md").write_text(post, encoding="utf-8")
    (skool_dir / "latest.md").write_text(post, encoding="utf-8")
    (skool_dir / "latest.json").write_text(json.dumps({
        "episode_number": episode_no,
        "date": date_str,
        "title": title,
        "generated_at": datetime.now().isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Skool duyurusu hazır → %s (%d kelime).", out, len(post.split()))
    return post


def main() -> None:
    ap = argparse.ArgumentParser(description="Future with Serdar — Skool duyuru üretici")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--episode", type=int, required=True)
    args = ap.parse_args()
    print(generate_skool_post(args.date, args.episode))


if __name__ == "__main__":
    main()
