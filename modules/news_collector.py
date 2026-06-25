"""Modül 1 — news_collector

AI gündemini RSS'lerden toplar, dedup yapar, Claude ile puanlar, günün 3-4
haberini seçer, seçilenler için tam metni çeker ve daily_news.json üretir.

Bağımsız çalıştırma:
    python -m modules.news_collector --date 2026-06-15
"""
from __future__ import annotations

import argparse
import html
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

import feedparser
import requests
from pydantic import BaseModel, Field

from utils.claude_client import parse as claude_parse
from utils.config_loader import load_config
from utils import db
from utils.logging_utils import get_logger
from utils.paths import output_dir

log = get_logger("collector")

USER_AGENT = "FutureWithSerdar/1.0 (+podcast news collector)"


# --------------------------------------------------------------------------- #
# Veri modelleri
# --------------------------------------------------------------------------- #
@dataclass
class Candidate:
    source: str
    category: str
    title: str
    url: str
    summary: str
    published: str | None = None          # ISO string
    importance_score: int | None = None
    score_reasoning: str | None = None
    full_text: str | None = None
    dup_sources: list[str] = field(default_factory=list)


class ScoreItem(BaseModel):
    index: int = Field(description="Puanlanan haberin listedeki sıra numarası (0 tabanlı)")
    score: int = Field(ge=0, le=100, description="0-100 önem skoru")
    reasoning: str = Field(description="Tek cümle Türkçe gerekçe")


class ScoreResult(BaseModel):
    items: list[ScoreItem]


# --------------------------------------------------------------------------- #
# RSS toplama
# --------------------------------------------------------------------------- #
def _entry_datetime(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _matches_ai(text: str, keywords: list[str]) -> bool:
    low = f" {text.lower()} "
    return any(k.lower() in low for k in keywords)


def fetch_sources(cfg: dict) -> list[Candidate]:
    """Tüm kaynaklardan son N saatin başlıklarını toplar."""
    c = cfg["collector"]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=c["hours_lookback"])
    keywords = cfg.get("ai_keywords", [])
    candidates: list[Candidate] = []

    for src in cfg["sources"]:
        if src.get("weekly_only"):
            continue  # günlük akışta atlanır (haftalık özet modülü ileride)
        name = src["name"]
        try:
            # feed'i requests ile indir (feedparser'ın kendi urllib'i macOS'ta
            # SSL sertifika hatası veriyor); içeriği feedparser'a ver.
            resp = requests.get(
                src["url"],
                timeout=c["request_timeout"],
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except Exception as e:  # noqa: BLE001
            log.warning("[%s] feed alınamadı: %s", name, e)
            continue

        if not feed.entries:
            log.warning("[%s] feed boş/hatalı, atlanıyor.", name)
            continue

        kept = 0
        # Önce tarih/AI filtresi uygula, SONRA kaynak başına sınırla — böylece
        # eskiden-yeniye sıralı feed'lerde güncel haberler kaçmaz.
        for entry in feed.entries:
            if kept >= c["per_source_limit"]:
                break
            title = html.unescape((entry.get("title") or "").strip())
            url = (entry.get("link") or "").strip()
            if not title or not url:
                continue

            dt = _entry_datetime(entry)
            if dt and dt < cutoff:
                continue  # 24 saatten eski

            summary = (entry.get("summary") or entry.get("description") or "").strip()
            # HTML etiketlerini kabaca temizle
            summary = html.unescape(_strip_html(summary))[:600]

            if src.get("ai_filter") and not _matches_ai(f"{title} {summary}", keywords):
                continue

            candidates.append(Candidate(
                source=name,
                category=src.get("category", "other"),
                title=title,
                url=url,
                summary=summary,
                published=dt.isoformat() if dt else None,
            ))
            kept += 1
        log.info("[%s] %d başlık alındı.", name, kept)

    log.info("Toplam %d aday başlık toplandı.", len(candidates))
    return candidates


def _strip_html(text: str) -> str:
    import re
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# --------------------------------------------------------------------------- #
# Dedup
# --------------------------------------------------------------------------- #
def dedup(cands: list[Candidate], threshold: float) -> list[Candidate]:
    """Başlık benzerliğine göre kopya haberleri birleştirir."""
    unique: list[Candidate] = []
    for cand in cands:
        match = None
        for u in unique:
            ratio = SequenceMatcher(None, cand.title.lower(), u.title.lower()).ratio()
            if ratio >= threshold:
                match = u
                break
        if match:
            if cand.source not in match.dup_sources and cand.source != match.source:
                match.dup_sources.append(cand.source)
        else:
            unique.append(cand)
    log.info("Dedup sonrası %d benzersiz haber.", len(unique))
    return unique


# --------------------------------------------------------------------------- #
# Puanlama (Claude)
# --------------------------------------------------------------------------- #
SCORING_SYSTEM = """Sen "Future with Serdar" adlı Türkçe günlük yapay zeka podcast'inin haber editörüsün.
Sana ham haber başlıkları ve özetleri verilecek. Her birine 0-100 arası bir ÖNEM SKORU ver.

Skorlama kriterleri:
- Türk dinleyici için pratik etki (üretkenlik, iş, gelir açısı yüksek puan)
- Büyüklük: yeni model lansmanı / büyük yatırım > minör güncelleme
- Tazelik ve genel önem
- "Future with Serdar" kitlesine uygunluk (AI ile üretkenlik/gelir bonus)

Sansasyonel ama tek kaynaklı iddiaları düşürme, ama orta puanla.

ÇEŞİTLİLİK / TEKRAR (önemli):
- Sana "son bölümlerde işlenen konular" verilebilir. Bu konuların DEVAMI/tekrarı olan
  haberleri belirgin şekilde DÜŞÜR (yeni ve büyük bir gelişme yoksa 30 puanın altına çek).
  Dinleyici her gün aynı sagayı (örn. aynı şirketin süregelen davası) dinlemek istemez.
- Aynı olayın farklı kaynaklardaki kopyalarında yalnızca EN GÜÇLÜsüne yüksek puan ver,
  diğerlerini düşür — bölümde aynı konudan iki haber olmasın.
- Farklı şirket/tema çeşitliliğini ödüllendir (tek bir şirkete boğulma).

Her habere tek cümlelik Türkçe gerekçe yaz. Tüm haberleri puanla, hiçbirini atlama."""


def score(cands: list[Candidate], model: str, recent_titles: list[str] | None = None) -> list[Candidate]:
    """Adayları Claude ile tek çağrıda puanlar."""
    if not cands:
        return cands

    lines = []
    for i, c in enumerate(cands):
        lines.append(f"[{i}] ({c.source}) {c.title}\n    Özet: {c.summary or '—'}")
    user = ""
    if recent_titles:
        user += ("SON BÖLÜMLERDE İŞLENEN KONULAR (bunların devamı/tekrarı olan haberleri düşür):\n"
                 + "\n".join(f"- {t}" for t in recent_titles) + "\n\n")
    user += "Aşağıdaki haberleri puanla:\n\n" + "\n\n".join(lines)

    result = claude_parse(
        model=model,
        system=SCORING_SYSTEM,
        user=user,
        schema=ScoreResult,
        max_tokens=4000,
    )

    by_index = {it.index: it for it in result.items}
    for i, c in enumerate(cands):
        it = by_index.get(i)
        if it:
            c.importance_score = it.score
            c.score_reasoning = it.reasoning
        else:
            c.importance_score = 0
            c.score_reasoning = "Puanlanmadı."
    log.info("Puanlama tamam (%d haber).", len(cands))
    return cands


# --------------------------------------------------------------------------- #
# Tam metin çekme
# --------------------------------------------------------------------------- #
def fetch_full_text(cand: Candidate, timeout: int, max_chars: int) -> None:
    try:
        import trafilatura
        resp = requests.get(cand.url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        text = trafilatura.extract(resp.text, include_comments=False, include_tables=False)
        if text:
            cand.full_text = text.strip()[:max_chars]
            return
    except Exception as e:  # noqa: BLE001
        log.warning("[%s] tam metin alınamadı: %s", cand.source, e)
    # Düşüş: özet kullan
    cand.full_text = cand.summary or None


# --------------------------------------------------------------------------- #
# Ana akış
# --------------------------------------------------------------------------- #
def collect(date_str: str) -> dict:
    """Tüm collector akışını çalıştırır, daily_news.json yazar ve sözlük döndürür."""
    t0 = time.time()
    cfg = load_config()
    c = cfg["collector"]

    cands = fetch_sources(cfg)
    if not cands:
        raise RuntimeError("Hiç haber toplanamadı. Feed'leri / internet bağlantısını kontrol edin.")

    cands = dedup(cands, c["dedup_threshold"])

    # Daha önce yayınlanmış haberleri ele (yerel kayıt + Supabase varsa)
    from utils import registry
    processed = registry.load_processed_urls() | db.already_processed_urls([c_.url for c_ in cands])
    if processed:
        before = len(cands)
        cands = [c_ for c_ in cands if c_.url not in processed]
        if before - len(cands):
            log.info("Daha önce yayınlanmış %d haber elendi.", before - len(cands))

    # Son bölüm başlıklarını puanlayıcıya ver (aynı sagayı tekrar seçmeyi önlemek için)
    recent_titles = [e.get("title", "") for e in
                     sorted(registry.load(), key=lambda x: x.get("episode_number", 0))[-4:]]
    cands = score(cands, cfg["model"]["scoring"], recent_titles)
    cands.sort(key=lambda x: x.importance_score or 0, reverse=True)

    # Seçim
    num_news = cfg["podcast"]["num_news"]
    eligible = [c_ for c_ in cands if (c_.importance_score or 0) >= c["min_score"]]

    # Öncelikli (sabitlenmiş) haberler: feed'de görülen ve priority_keywords ile
    # eşleşen adaylar, skorlarına bakılmaksızın bölüme alınır (kullanıcının
    # istediği belirli bir haber için). Kaynak kuralı korunur — bu yalnızca
    # GERÇEKTEN toplanmış bir feed makalesini öne çeker, haber uydurmaz.
    priority_kw = [k.lower() for k in cfg["podcast"].get("priority_keywords", [])]
    pinned: list[Candidate] = []
    if priority_kw:
        for c_ in cands:
            text = f"{c_.title} {c_.summary}".lower()
            if any(k in text for k in priority_kw):
                pinned.append(c_)
        if pinned:
            log.info("Öncelikli haber(ler) sabitlendi: %s",
                     " | ".join(p.title for p in pinned))

    selected = list(pinned[:num_news])
    for c_ in eligible:
        if len(selected) >= num_news:
            break
        if c_ not in selected:
            selected.append(c_)

    # Yavaş gün, sabitlenenler hariç gerçek skorlu havuza göre belirlenir
    top_score = cands[0].importance_score if cands else 0
    scored_in_selection = [c_ for c_ in selected if (c_.importance_score or 0) >= c["min_score"]]
    slow_day = len(scored_in_selection) < cfg["podcast"]["min_news"] or top_score < c["slow_day_threshold"]
    if slow_day:
        log.info("YAVAŞ GÜN: en yüksek skor %s, seçilen haber %d. slow_day=true.",
                 top_score, len(selected))
        # Yavaş günde elde olanı kullan (en az 1 haber)
        if not selected and cands:
            selected = cands[:1]

    # Seçilenler için tam metin
    if c.get("fetch_full_text", True):
        for cand in selected:
            fetch_full_text(cand, c["request_timeout"], c["max_full_text_chars"])
            log.info("[%s] tam metin: %d karakter.", cand.source,
                     len(cand.full_text or ""))

    # Supabase'e tüm puanlanan haberleri yaz
    db.upsert_news_items([{
        "source": cand.source,
        "url": cand.url,
        "title": cand.title,
        "summary": cand.summary,
        "importance_score": cand.importance_score,
        "score_reasoning": cand.score_reasoning,
    } for cand in cands])

    payload = {
        "date": date_str,
        "slow_day": slow_day,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selected_count": len(selected),
        "selected": [asdict(c_) for c_ in selected],
        "all_scored": [
            {"source": c_.source, "title": c_.title, "url": c_.url,
             "score": c_.importance_score, "reasoning": c_.score_reasoning}
            for c_ in cands
        ],
    }

    out = output_dir(date_str) / "daily_news.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    dur = time.time() - t0
    log.info("daily_news.json yazıldı → %s (%.1fs, %d haber seçildi).",
             out, dur, len(selected))
    db.log_step(date_str, "news_collector", "ok", duration_sec=dur)
    return payload


def main() -> None:
    ap = argparse.ArgumentParser(description="Future with Serdar — haber toplayıcı")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                    help="YYYY-MM-DD (varsayılan: bugün)")
    args = ap.parse_args()
    payload = collect(args.date)
    print("\n=== SEÇİLEN HABERLER ===")
    for c_ in payload["selected"]:
        print(f"  [{c_['importance_score']}] ({c_['source']}) {c_['title']}")
        print(f"        {c_['score_reasoning']}")


if __name__ == "__main__":
    main()
