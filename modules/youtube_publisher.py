"""Modül 6 — youtube_publisher (Faz 3)

Bölüm videosunu (ve Shorts'u) YouTube'a yükler. YouTube Data API v3 + OAuth.

MANUEL yükleme kiti (Google/OAuth gerektirmez — önerilen):
    python -m modules.youtube_publisher --export --date 2026-06-12 --episode 1
    → youtube.txt üretir (başlık + açıklama + etiketler), elle yüklersin.

Otomatik yükleme (opsiyonel, OAuth gerekir):
    python -m modules.youtube_publisher --auth         # tek seferlik
    python -m modules.youtube_publisher --date 2026-06-12 --episode 1 --privacy unlisted
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from utils import db, registry
from utils.config_loader import require_env, get_env
from utils.logging_utils import get_logger
from utils.paths import ROOT, output_dir

log = get_logger("youtube")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CATEGORY_SCIENCE_TECH = "28"


# --------------------------------------------------------------------------- #
# Yetkilendirme
# --------------------------------------------------------------------------- #
def _client_config() -> dict:
    return {
        "installed": {
            "client_id": require_env("YOUTUBE_CLIENT_ID"),
            "client_secret": require_env("YOUTUBE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def authorize() -> None:
    """Tek seferlik OAuth akışı — refresh token alır ve .env'e yazar."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(_client_config(), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent",
                                  authorization_prompt_message="Tarayıcıda YouTube iznini ver...")
    if not creds.refresh_token:
        raise RuntimeError("Refresh token alınamadı. Tekrar deneyin (prompt=consent).")
    _write_env("YOUTUBE_REFRESH_TOKEN", creds.refresh_token)
    log.info("✅ Yetkilendirme tamam. YOUTUBE_REFRESH_TOKEN .env'e yazıldı.")


def _write_env(key: str, value: str) -> None:
    p = ROOT / ".env"
    s = p.read_text(encoding="utf-8") if p.exists() else ""
    if re.search(rf"^{key}=.*$", s, flags=re.M):
        s = re.sub(rf"^{key}=.*$", f"{key}={value}", s, flags=re.M)
    else:
        s = s.rstrip() + f"\n{key}={value}\n"
    p.write_text(s, encoding="utf-8")


def _credentials():
    from google.oauth2.credentials import Credentials
    refresh = get_env("YOUTUBE_REFRESH_TOKEN")
    if not refresh:
        raise RuntimeError(
            "YOUTUBE_REFRESH_TOKEN yok. Önce yetkilendir: "
            "python -m modules.youtube_publisher --auth"
        )
    return Credentials(
        token=None,
        refresh_token=refresh,
        client_id=require_env("YOUTUBE_CLIENT_ID"),
        client_secret=require_env("YOUTUBE_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )


def _service():
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=_credentials(), cache_discovery=False)


# --------------------------------------------------------------------------- #
# Açıklama / başlık üretimi
# --------------------------------------------------------------------------- #
def _build_description(data: dict, feed_hint: str = "") -> str:
    lines = [data.get("description", "").strip(), ""]
    chapters = data.get("chapters", [])
    if chapters:
        lines.append("Bölümler:")
        for ch in chapters:
            t = int(ch.get("t", 0))
            lines.append(f"{t // 60:02d}:{t % 60:02d} {ch.get('label', '')}")
        lines.append("")
    lines.append("Beni Instagram ve YouTube'da Future with Serdar olarak bulabilirsiniz.")
    lines.append("Bu bölüm, otomatik bir yapay zekâ sistemi tarafından üretildi.")
    if feed_hint:
        lines.append(f"\nPodcast: {feed_hint}")
    return "\n".join(lines)[:4900]  # YouTube açıklama limiti ~5000


_STOP = {"haber", "bölüm", "bolum", "günün", "gunun", "için", "icin",
         "olan", "daha", "gibi", "asıl", "asil"}


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-zçğıöşü0-9]{4,}", s.lower())} - _STOP


def _prefix_match(label_tok: set[str], para_tok: set[str]) -> int:
    """Türkçe eklerini tolere ederek (önek) eşleşen token sayısı."""
    score = 0
    for lt in label_tok:
        for pt in para_tok:
            if pt.startswith(lt) or lt.startswith(pt):
                score += 1
                break
    return score


def accurate_chapters(out_dir, data: dict) -> list[dict]:
    """script.json bölümlerini voice_timestamps.json'daki gerçek sürelerle eşler.

    voice_timestamps yoksa orijinal (tahmini) bölümleri döndürür.
    """
    ts_path = Path(out_dir) / "voice_timestamps.json"
    chapters = data.get("chapters", [])
    if not ts_path.exists() or not chapters:
        return chapters
    ts = json.loads(ts_path.read_text(encoding="utf-8"))
    paras = ts.get("paragraphs", [])
    duration = ts.get("duration_sec", 0)
    if not paras:
        return chapters

    result = []
    last_idx = 0
    for i, ch in enumerate(chapters):
        if i == 0:
            result.append({"t": 0, "label": ch["label"]})
            continue
        ltok = _tokens(ch["label"])
        scores = [_prefix_match(ltok, _tokens(paras[pidx]["text"]))
                  for pidx in range(last_idx, len(paras))]
        best_score = max(scores) if scores else 0
        if best_score > 0:
            # Bölüm BAŞINA yakınlaşmak için: en yüksek değil, eşiği geçen EN ERKEN paragraf
            threshold = min(2, best_score)
            rel = next(i for i, s in enumerate(scores) if s >= threshold)
            chosen = last_idx + rel
            last_idx = chosen
            result.append({"t": int(paras[chosen]["start"]), "label": ch["label"]})
        else:
            result.append({"t": result[-1]["t"] + 1, "label": ch["label"]})

    # Kesin artan + süre içinde olacak şekilde temizle
    cleaned, prev = [], -1
    for ch in result:
        t = ch["t"]
        if duration and t >= duration - 2:
            continue
        if t <= prev:
            t = prev + 1
        cleaned.append({"t": t, "label": ch["label"]})
        prev = t
    return cleaned


def export_kit(date_str: str, episode_no: int = 1) -> dict:
    """Google gerektirmeden manuel yükleme kiti üretir: youtube.txt + dosya yolları."""
    out_dir = output_dir(date_str)
    nnn = f"{episode_no:03d}"
    script_path = out_dir / "script.json"
    data = json.loads(script_path.read_text(encoding="utf-8"))
    title = re.sub(r"^B[öo]l[üu]m\s*\d+", f"Bölüm {episode_no}", data["title"])
    data["chapters"] = accurate_chapters(out_dir, data)  # gerçek seslere göre düzelt

    feed_hint = ""
    if get_env("PAGES_BASE_URL"):
        feed_hint = f"{get_env('PAGES_BASE_URL').rstrip('/')}/feed.xml"
    description = _build_description(data, feed_hint)
    tags = data.get("youtube_tags", [])
    seg = data.get("shorts_segment", {})

    txt = f"""=== YOUTUBE YÜKLEME KİTİ — Bölüm {episode_no} ({date_str}) ===

----- BAŞLIK (kopyala) -----
{title}

----- AÇIKLAMA (kopyala) -----
{description}

----- ETİKETLER (virgülle, kopyala) -----
{', '.join(tags)}

----- AYARLAR -----
Kategori: Bilim ve Teknoloji
Dil: Türkçe
Çocuklara yönelik: Hayır

----- DOSYALAR -----
Uzun video : {out_dir / f'episode_{nnn}.mp4'}
Shorts     : {out_dir / f'short_{nnn}.mp4'}
Kapak/thumb: {out_dir / 'cover.jpg'}

----- SHORTS BAŞLIĞI önerisi -----
{(seg.get('hook_line') or title)[:90]} #Shorts
"""
    kit_path = out_dir / "youtube.txt"
    kit_path.write_text(txt, encoding="utf-8")
    return {
        "kit": str(kit_path),
        "video": str(out_dir / f"episode_{nnn}.mp4"),
        "short": str(out_dir / f"short_{nnn}.mp4"),
        "title": title,
    }


def _upload(service, file: Path, title: str, description: str,
            tags: list[str], privacy: str) -> str:
    from googleapiclient.http import MediaFileUpload
    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags[:30],
            "categoryId": CATEGORY_SCIENCE_TECH,
            "defaultLanguage": "tr",
            "defaultAudioLanguage": "tr",
        },
        "status": {
            "privacyStatus": privacy,         # unlisted | public | private
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(str(file), chunksize=-1, resumable=True,
                            mimetype="video/mp4")
    req = service.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            log.info("  yükleniyor... %%%d", int(status.progress() * 100))
    return resp["id"]


# --------------------------------------------------------------------------- #
# Ana akış
# --------------------------------------------------------------------------- #
def publish_youtube(date_str: str, episode_no: int = 1,
                    privacy: str = "unlisted", shorts: bool = True) -> dict:
    out_dir = output_dir(date_str)
    nnn = f"{episode_no:03d}"
    video = out_dir / f"episode_{nnn}.mp4"
    script_path = out_dir / "script.json"
    if not video.exists():
        raise FileNotFoundError(f"{video} yok. Önce montaj (audio_assembler) çalıştırın.")
    data = json.loads(script_path.read_text(encoding="utf-8"))
    title = re.sub(r"^B[öo]l[üu]m\s*\d+", f"Bölüm {episode_no}", data["title"])
    data["chapters"] = accurate_chapters(out_dir, data)  # gerçek seslere göre düzelt

    feed_hint = ""
    if get_env("PAGES_BASE_URL"):
        feed_hint = f"{get_env('PAGES_BASE_URL').rstrip('/')}/feed.xml"

    service = _service()
    log.info("Ana video yükleniyor (%s)...", privacy)
    video_id = _upload(service, video, title,
                       _build_description(data, feed_hint),
                       data.get("youtube_tags", []), privacy)
    video_url = f"https://youtu.be/{video_id}"
    log.info("✅ Video yüklendi → %s", video_url)

    result = {"video_id": video_id, "video_url": video_url}

    short = out_dir / f"short_{nnn}.mp4"
    if shorts and short.exists():
        try:
            log.info("Shorts yükleniyor...")
            seg = data.get("shorts_segment", {})
            hook = seg.get("hook_line", "") or title
            short_desc = f"{hook}\n\nTam bölüm: {video_url}\n#Shorts #yapayzeka"
            short_id = _upload(service, short, f"{hook[:80]} #Shorts",
                               short_desc, data.get("youtube_tags", []), privacy)
            result["short_id"] = short_id
            result["short_url"] = f"https://youtu.be/{short_id}"
            log.info("✅ Shorts yüklendi → %s", result["short_url"])
        except Exception as e:  # noqa: BLE001
            log.warning("Shorts yüklenemedi (atlanıyor): %s", e)

    # Kayıtları güncelle
    eps = registry.load()
    for ep in eps:
        if ep.get("episode_number") == episode_no:
            ep["youtube_video_id"] = video_id
            ep["youtube_short_id"] = result.get("short_id")
            break
    else:
        eps = registry.upsert({"episode_number": episode_no, "date": date_str,
                               "title": title, "youtube_video_id": video_id,
                               "youtube_short_id": result.get("short_id")})
    if eps:
        (ROOT / "episodes.json").write_text(
            json.dumps(eps, ensure_ascii=False, indent=2), encoding="utf-8")

    db.log_step(date_str, "youtube_publisher", "ok")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Future with Serdar — YouTube yayıncısı")
    ap.add_argument("--export", action="store_true",
                    help="Manuel yükleme kiti üret (Google gerektirmez)")
    ap.add_argument("--auth", action="store_true", help="Tek seferlik OAuth yetkilendirme")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--episode", type=int, default=1)
    ap.add_argument("--privacy", choices=["unlisted", "public", "private"],
                    default="unlisted", help="Görünürlük (varsayılan: unlisted)")
    ap.add_argument("--no-short", action="store_true")
    args = ap.parse_args()

    if args.auth:
        authorize()
        return

    if args.export:
        res = export_kit(args.date, args.episode)
        print("\n=== MANUEL YÜKLEME KİTİ HAZIR ===")
        print(f"  Kit (başlık/açıklama/etiket): {res['kit']}")
        print(f"  Uzun video: {res['video']}")
        print(f"  Shorts:     {res['short']}")
        return

    res = publish_youtube(args.date, args.episode, args.privacy, shorts=not args.no_short)
    print("\n=== YOUTUBE'A YÜKLENDİ ===")
    print(f"  Video:  {res['video_url']}  ({args.privacy})")
    if res.get("short_url"):
        print(f"  Shorts: {res['short_url']}")


if __name__ == "__main__":
    main()
