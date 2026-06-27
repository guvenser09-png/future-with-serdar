"""Modül 2 — script_writer

daily_news.json → Claude API → Türkçe podcast senaryosu (yapılandırılmış JSON).

Bağımsız çalıştırma:
    python -m modules.script_writer --date 2026-06-15
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

from pydantic import BaseModel, Field

from utils.claude_client import parse as claude_parse
from utils.config_loader import load_config
from utils import db
from utils.logging_utils import get_logger
from utils.paths import output_dir

log = get_logger("writer")

TR_MONTHS = [
    "", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]


# --------------------------------------------------------------------------- #
# Çıktı şeması (CLAUDE.md Modül 2)
# --------------------------------------------------------------------------- #
class Chapter(BaseModel):
    t: int = Field(description="Bölümün başlangıç saniyesi (yaklaşık)")
    label: str = Field(description="Bölüm etiketi, örn. 'Haber 1: ...'")


class ShortsSegment(BaseModel):
    start_hint: str = Field(description="Shorts için hangi bölümden kesilecek, örn. 'Haber 2'")
    hook_line: str = Field(description="Shorts'un başına konacak çarpıcı kanca cümlesi")


class Episode(BaseModel):
    title: str = Field(description="Bölüm başlığı, örn. \"Bölüm 12: ... | 24 Haziran\"")
    description: str = Field(description="Podcast/YouTube açıklaması (2-4 cümle)")
    script: str = Field(description="Tam Türkçe senaryo metni (sesli okunacak)")
    chapters: list[Chapter]
    shorts_segment: ShortsSegment
    youtube_tags: list[str] = Field(description="YouTube etiketleri (8-15 adet)")


# --------------------------------------------------------------------------- #
# Ton talimatları (CLAUDE.md Modül 2)
# --------------------------------------------------------------------------- #
TONE_SYSTEM = """Sen "Future with Serdar" adlı Türkçe günlük yapay zeka podcast'inin senaristisin.
Serdar'ın ağzından, sesli okunmak üzere bir bölüm senaryosu yazıyorsun.

TON:
- Bilgili ama kibirli değil — teknolojiyi arkadaşına anlatan mühendis tonu.
- Konuşma Türkçesi: "Bakın bu önemli", "Açıkçası ben buna şaşırdım", "Şimdi gelelim asıl bombaya".
- Sesli okunmak için yaz: kısa cümleler, parantez içi açıklama YOK.
- İngilizce terimler ilk geçişte tek cümleyle Türkçeleştirilir ("context window, yani modelin tek seferde işleyebildiği metin miktarı").
- Abartı/clickbait yok; "devrim", "çığır" sadece gerçekten hak edildiğinde.
- Spekülasyon ile doğrulanmış bilgi net ayrılır ("X iddia ediyor ki..." vs "X duyurdu").
- SADECE ŞAPKA (inceltme) İŞARETİNİ KULLANMA: yalnızca â, î, û → şapkasız yaz (zekâ→zeka, kâr→kar, âdeta→adeta, hâlâ→hala). ÇOK ÖNEMLİ — diğer TÜM Türkçe harfleri NORMAL ve EKSİKSİZ kullan: ç, ş, ğ, ı, ö, ü, İ (ve büyükleri) MUTLAKA yazılmalı. Metni ASLA ASCII'ye / İngilizce harflere çevirme. Doğru: "hoş geldiniz", "işte", "çok", "güvenlik", "Türkiye", "geliştirici", "başlayalım". Yanlış: "hos geldiniz", "iste", "cok", "guvenlik", "Turkiye". Yani: sadece şapka yok; Türkçe karakterler tam. Başlık, açıklama ve senaryonun tamamı için geçerli.

DUYGU / SESLENDİRME (eleven_v3 etiketleri):
- Ses motoru, metne gömülü köşeli parantez etiketlerini okumaz ama o duyguyu sese yansıtır.
- Doğru anlara, ÖLÇÜLÜ kullan (tüm bölümde toplam 3-6 etiket; her cümleye DEĞİL). Marka tonu abartısız.
- İzinli etiketler (İngilizce yaz, bunların dışına çıkma): [curious] [excited] [surprised] [thoughtful] [serious] [skeptical]
- Tipik yerleşim: kanca/çarpıcı haberde [excited] ya da [surprised]; analiz/derinleşmede [thoughtful]; doğrulanmamış iddiada [skeptical].
- Etiketi cümlenin BAŞINA koy. Örnek: "[surprised] Açıkçası buna ben de şaşırdım."
- Yabancı marka/terimleri (OpenAI, ChatGPT, Gemini, Claude, Nvidia, GPT, API...) İngilizce yazımıyla bırak; Türkçe heceleme yapma.

BÖLÜM YAPISI (480-580 kelime ≈ 3-4 dakika — DOLU DOLU ama net):
ÖNEMLİ: Hedef kelime sayısının ALTINA İNME. Her haberi gerçekten aç; 2 dakikalık
yarım bölüm KABUL EDİLMEZ. Akıcı konuş ama 3-4 dakikayı doldur.
1. AÇILIŞ (sabit kalıp): "Merhaba, ben Serdar. Future with Serdar'a hoş geldiniz. Bugün {tarih}, işte yapay zeka dünyasında son 24 saat." + günün en çarpıcı gelişmesinden tek cümle kanca.
2. GÜNÜN HABERLERİ (her haber ~50-70 sn): ne oldu (2-3 cümle) → neden önemli (1-2 cümle) → "senin için anlamı" (1-2 cümle: Türk kullanıcı/üretici/girişimci perspektifinden pratik çıkarım). Bu son kısım programın imzasıdır — kuru haber değil, yorumlu bülten. Her habere yeterince yer ver.
3. GÜNÜN ARACI / İPUCU (~30 sn): kısa ama gerçek bir AI aracı/kullanım önerisi ekle (bölümü doldurmaya da yardımcı olur).
4. KAPANIŞ (sabit kalıp): yarına tek cümle teaser + "Beni Instagram ve YouTube'da Future with Serdar olarak bulabilirsiniz" + "Bu bölüm, kendi geliştirdiğim yapay zeka sistemi tarafından otomatik üretildi."

KURALLAR:
- Senaryodaki HER iddia sana verilen haber verisine dayanmalı. LLM bilginden haber uydurma.
- Doğrulanmamış iddiaları "iddia/söylenti" olarak işaretle.
- chapters: senaryodaki bölümlerin yaklaşık saniye zaman damgaları (konuşma hızı ~150 kelime/dk varsay).
- shorts_segment: en çarpıcı 45-60 sn'lik kesit için ipucu + kanca cümlesi.
- script alanı düz metin olsun; markdown başlık (#) kullanma."""

SLOW_DAY_NOTE = """
NOT — YAVAŞ GÜN: Bugün öne çıkan az sayıda/zayıf haber var. "Derinlemesine tek konu" moduna geç:
elindeki en güçlü haberi veya kavramı al, onu daha detaylı anlat (bir aracın incelemesi ya da bir
kavramın açıklaması). Yapıyı koru ama haber sayısını zorlamadan derinleş."""


def _format_date_tr(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{d.day} {TR_MONTHS[d.month]} {d.year}"


def _build_user_prompt(news: dict, date_str: str, target_words: list[int]) -> str:
    parts = [
        f"Tarih: {_format_date_tr(date_str)}",
        f"Hedef uzunluk: {target_words[0]}-{target_words[1]} kelime.",
        "",
        "İşte bugünün seçilmiş haberleri (önem sırasına göre):",
        "",
    ]
    for i, item in enumerate(news["selected"], 1):
        parts.append(f"### Haber {i} — {item['source']} (skor {item.get('importance_score')})")
        parts.append(f"Başlık: {item['title']}")
        if item.get("dup_sources"):
            parts.append(f"Diğer kaynaklar: {', '.join(item['dup_sources'])}")
        parts.append(f"URL: {item['url']}")
        body = item.get("full_text") or item.get("summary") or "—"
        parts.append(f"İçerik:\n{body}")
        parts.append("")
    parts.append("Bu verilere dayanarak bölüm senaryosunu üret.")
    return "\n".join(parts)


def write_script(date_str: str) -> dict:
    """daily_news.json okur, senaryo üretir, script.json yazar."""
    cfg = load_config()
    out_dir = output_dir(date_str)
    news_path = out_dir / "daily_news.json"
    if not news_path.exists():
        raise FileNotFoundError(
            f"{news_path} yok. Önce news_collector çalıştırın "
            f"(python -m modules.news_collector --date {date_str})."
        )
    news = json.loads(news_path.read_text(encoding="utf-8"))
    if not news.get("selected"):
        raise RuntimeError("daily_news.json içinde seçili haber yok.")

    system = TONE_SYSTEM
    if news.get("slow_day"):
        system += "\n" + SLOW_DAY_NOTE

    user = _build_user_prompt(news, date_str, cfg["podcast"]["target_words"])

    log.info("Senaryo üretiliyor (%d haber, slow_day=%s)...",
             news["selected_count"], news.get("slow_day"))

    # Senaryonun çok kısa/kesik gelmesine karşı koruma: model bazen (özellikle
    # uzun girdilerde) script alanını yarıda bırakıp metadatayı tam üretiyor.
    # Hedefin %55'inin altı "kesik" sayılır; bir kez yeniden denenir, yine
    # kısaysa HATA verilir (yarım bölüm asla yayınlanmaz — CLAUDE.md kuralı).
    min_words = max(400, int(cfg["podcast"]["target_words"][0] * 0.70))
    episode = None
    for attempt in range(1, 3):
        episode = claude_parse(
            model=cfg["model"]["script"],
            system=system,
            user=user,
            schema=Episode,
            max_tokens=8000,
        )
        wc = len(episode.script.split())
        if wc >= min_words:
            break
        log.warning("Senaryo çok kısa (%d kelime < %d) — kesik olabilir. Deneme %d/2.",
                    wc, min_words, attempt)
    if episode is None or len(episode.script.split()) < min_words:
        got = len(episode.script.split()) if episode else 0
        raise RuntimeError(
            f"Senaryo yeterli uzunlukta üretilemedi ({got} kelime < {min_words}). "
            "Yayın durduruldu — yarım bölüm yayınlanmaz."
        )

    data = episode.model_dump()
    word_count = len(episode.script.split())
    data["_meta"] = {
        "date": date_str,
        "word_count": word_count,
        "slow_day": news.get("slow_day", False),
        "source_count": news["selected_count"],
        "generated_at": datetime.now().isoformat(),
    }

    out = out_dir / "script.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("script.json yazıldı → %s (%d kelime).", out, word_count)
    db.log_step(date_str, "script_writer", "ok")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Future with Serdar — senaryo yazıcı")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    args = ap.parse_args()
    data = write_script(args.date)
    print("\n" + "=" * 70)
    print(data["title"])
    print("=" * 70)
    print(data["script"])
    print("\n--- Bölümler ---")
    for ch in data["chapters"]:
        print(f"  {ch['t']:>4}s  {ch['label']}")
    print(f"\nKelime: {data['_meta']['word_count']} | Etiketler: {', '.join(data['youtube_tags'])}")


if __name__ == "__main__":
    main()
