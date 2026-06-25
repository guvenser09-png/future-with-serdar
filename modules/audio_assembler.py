"""Modül 4 — audio_assembler (Faz 2)

voice_raw.mp3 → yayına hazır podcast MP3 + YouTube MP4.

- Görseller PIL ile otomatik üretilir (markalı arka plan + kapak).
- Ses: loudnorm (-16 LUFS), 128 kbps / 44.1 kHz / mono, ID3 + kapak.
- Video: 1920x1080 arka plan + showwaves ses dalgası + ses.
- (Opsiyonel) Shorts: 1080x1920 dikey kesit.

Bağımsız çalıştırma:
    python -m modules.audio_assembler --date 2026-06-15 --episode 1
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from utils import db
from utils.config_loader import get_env
from utils.logging_utils import get_logger
from utils.paths import output_dir

log = get_logger("assembler")

# Marka paleti
BG_TOP = (14, 18, 32)        # koyu lacivert
BG_BOTTOM = (6, 8, 16)       # neredeyse siyah
ACCENT = (245, 166, 35)      # amber (ses dalgası + vurgu)
TEXT = (240, 242, 248)
MUTED = (150, 158, 178)

FONT_BLACK = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"

BRAND = get_env("PODCAST_TITLE", "Future with Serdar")
AUTHOR = get_env("PODCAST_AUTHOR", "Serdar")

TR_MONTHS = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
             "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _vertical_gradient(w: int, h: int) -> Image.Image:
    """Dikey degrade arka plan."""
    base = Image.new("RGB", (w, h), BG_TOP)
    top = Image.new("RGB", (w, h), BG_TOP)
    bottom = Image.new("RGB", (w, h), BG_BOTTOM)
    mask = Image.new("L", (w, h))
    md = mask.load()
    for y in range(h):
        v = int(255 * (y / h))
        for x in range(w):
            md[x, y] = v
    return Image.composite(bottom, top, mask)


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        test = f"{cur} {wd}".strip()
        if draw.textlength(test, font=font) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def _clean_title(title: str) -> str:
    """Görselde gösterilecek başlık: 'Bölüm N:' önekini ve '| tarih' sonekini atar."""
    t = re.sub(r"^B[öo]l[üu]m\s*\d+\s*[:\-]\s*", "", title)
    t = re.split(r"\s*\|\s*", t)[0]
    return t.strip()


def _date_tr(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{d.day} {TR_MONTHS[d.month]} {d.year}"


# --------------------------------------------------------------------------- #
# Görsel üretimi
# --------------------------------------------------------------------------- #
def make_background(title: str, episode_no: int, date_str: str,
                    size: tuple[int, int], out_path: Path, vertical: bool = False) -> None:
    w, h = size
    img = _vertical_gradient(w, h)
    draw = ImageDraw.Draw(img)
    scale = w / 1920 if not vertical else w / 1080

    # Üst marka çubuğu
    brand_f = _font(FONT_BLACK, int(54 * scale))
    draw.text((int(90 * scale), int(80 * scale)), BRAND.upper(),
              font=brand_f, fill=TEXT)
    # accent alt çizgi
    bw = draw.textlength(BRAND.upper(), font=brand_f)
    draw.rectangle([int(92 * scale), int(150 * scale),
                    int(92 * scale + bw), int(158 * scale)], fill=ACCENT)

    # Bölüm etiketi
    ep_f = _font(FONT_BOLD, int(34 * scale))
    draw.text((int(92 * scale), int(190 * scale)),
              f"BÖLÜM {episode_no}  ·  {_date_tr(date_str).upper()}",
              font=ep_f, fill=MUTED)

    # Başlık (ortada, sarılı)
    clean = _clean_title(title)
    title_size = int((92 if not vertical else 78) * scale)
    title_f = _font(FONT_BOLD, title_size)
    max_w = w - int(180 * scale)
    lines = _wrap(draw, clean, title_f, max_w)
    line_h = int(title_size * 1.18)
    total_h = line_h * len(lines)
    y = (h - total_h) // 2 - int(40 * scale)
    for ln in lines:
        draw.text((int(90 * scale), y), ln, font=title_f, fill=TEXT)
        y += line_h

    # Alt bilgi (ses dalgasına yer bırak)
    foot_f = _font(FONT_REG, int(30 * scale))
    draw.text((int(92 * scale), h - int(90 * scale)),
              "Yapay zeka tarafından üretildi · günlük AI bülteni",
              font=foot_f, fill=MUTED)

    img.save(out_path, quality=92)
    log.info("Arka plan üretildi → %s (%dx%d)", out_path, w, h)


def _fit_font(draw, text, path, max_w, start_size, min_size=20):
    """Metni max_w genişliğine sığdıracak en büyük fontu bulur."""
    size = start_size
    while size > min_size:
        f = _font(path, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 6
    return _font(path, min_size)


def make_show_cover(out_path: Path, subtitle: str = "") -> None:
    """3000x3000 KANAL kapağı (markaya özel, bölüm numarası yok)."""
    s = 3000
    margin = 200
    avail = s - 2 * margin
    img = _vertical_gradient(s, s)
    draw = ImageDraw.Draw(img)

    parts = BRAND.upper().split()
    line1 = parts[0] if parts else BRAND.upper()       # FUTURE
    line2 = " ".join(parts[1:]) if len(parts) > 1 else ""  # WITH SERDAR

    # En uzun satıra göre ortak font boyutu (taşmayı önler)
    longest = max([line1, line2], key=lambda t: len(t)) or line1
    brand_f = _fit_font(draw, longest, FONT_BLACK, avail, 360)
    lh = int(brand_f.size * 1.12)

    block_h = lh * (2 if line2 else 1) + int(0.5 * lh)  # + alt çizgi payı
    y = (s - block_h) // 2 - 150   # hafif yukarı

    draw.text((margin, y), line1, font=brand_f, fill=TEXT)
    if line2:
        draw.text((margin, y + lh), line2, font=brand_f, fill=ACCENT)
        uy = y + 2 * lh + int(0.18 * lh)
    else:
        uy = y + lh + int(0.18 * lh)

    # accent alt çizgi (line2 genişliği kadar)
    ulen = draw.textlength(line2 or line1, font=brand_f)
    draw.rectangle([margin, uy, margin + int(ulen), uy + 22], fill=ACCENT)

    # Alt başlık (sarılı)
    if subtitle:
        sf = _font(FONT_BOLD, 92)
        sy = uy + 120
        for ln in _wrap(draw, subtitle, sf, avail):
            draw.text((margin, sy), ln, font=sf, fill=MUTED)
            sy += int(92 * 1.25)

    # En alt imza
    ff = _font(FONT_REG, 52)
    draw.text((margin, s - 220), "Günlük AI bülteni · yapay zeka üretimi",
              font=ff, fill=MUTED)

    img.convert("RGB").save(out_path, "JPEG", quality=90)
    log.info("Kanal kapağı üretildi → %s (3000x3000)", out_path)


def make_cover(title: str, episode_no: int, date_str: str, out_path: Path) -> None:
    """3000x3000 podcast kapağı."""
    s = 3000
    img = _vertical_gradient(s, s)
    draw = ImageDraw.Draw(img)
    scale = s / 1080

    brand_f = _font(FONT_BLACK, int(120 * scale))
    # Marka iki satır: FUTURE / WITH SERDAR
    parts = BRAND.upper().split()
    line1 = parts[0] if parts else BRAND.upper()
    line2 = " ".join(parts[1:]) if len(parts) > 1 else ""
    draw.text((int(140 * scale), int(180 * scale)), line1, font=brand_f, fill=TEXT)
    if line2:
        draw.text((int(140 * scale), int(320 * scale)), line2, font=brand_f, fill=ACCENT)

    # Orta başlık
    clean = _clean_title(title)
    tf = _font(FONT_BOLD, int(96 * scale))
    lines = _wrap(draw, clean, tf, s - int(280 * scale))
    lh = int(96 * scale * 1.2)
    y = (s - lh * len(lines)) // 2 + int(120 * scale)
    for ln in lines:
        draw.text((int(140 * scale), y), ln, font=tf, fill=TEXT)
        y += lh

    # Alt
    ef = _font(FONT_BOLD, int(56 * scale))
    draw.text((int(140 * scale), s - int(260 * scale)),
              f"BÖLÜM {episode_no}", font=ef, fill=ACCENT)
    df = _font(FONT_REG, int(48 * scale))
    draw.text((int(140 * scale), s - int(180 * scale)),
              _date_tr(date_str), font=df, fill=MUTED)

    img.convert("RGB").save(out_path, "JPEG", quality=90)
    log.info("Kapak üretildi → %s (3000x3000)", out_path)


# --------------------------------------------------------------------------- #
# Ses / video
# --------------------------------------------------------------------------- #
def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg hata:\n{proc.stderr[-1500:]}")


def build_podcast_mp3(voice_raw: Path, cover: Path, out_mp3: Path,
                      title: str, episode_no: int) -> None:
    """loudnorm + ID3 + kapak gömülü yayına hazır MP3."""
    norm = out_mp3.with_name("_norm.mp3")
    _run(["ffmpeg", "-y", "-i", str(voice_raw),
          "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
          "-ar", "44100", "-ac", "1", "-b:a", "128k", str(norm)])

    _run(["ffmpeg", "-y", "-i", str(norm), "-i", str(cover),
          "-map", "0:a", "-map", "1:v", "-c:a", "copy", "-c:v", "mjpeg",
          "-id3v2_version", "3",
          "-metadata", f"title={title}",
          "-metadata", f"artist={AUTHOR}",
          "-metadata", f"album={BRAND}",
          "-metadata", f"track={episode_no}",
          "-metadata:s:v", "title=Album cover",
          "-metadata:s:v", "comment=Cover (front)",
          str(out_mp3)])
    norm.unlink(missing_ok=True)
    log.info("Podcast MP3 hazır → %s", out_mp3)


def build_video(bg: Path, podcast_mp3: Path, out_mp4: Path) -> None:
    """Markalı arka plan + showwaves ses dalgası + ses → YouTube MP4."""
    color = f"0x{ACCENT[0]:02X}{ACCENT[1]:02X}{ACCENT[2]:02X}"
    filt = (
        f"[1:a]showwaves=s=1920x260:mode=cline:colors={color}:rate=25,format=yuva420p[w];"
        f"[0:v][w]overlay=(W-w)/2:H-h-70:shortest=1,format=yuv420p[v]"
    )
    _run(["ffmpeg", "-y", "-loop", "1", "-i", str(bg), "-i", str(podcast_mp3),
          "-filter_complex", filt, "-map", "[v]", "-map", "1:a",
          "-c:v", "libx264", "-preset", "medium", "-crf", "20",
          "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
          "-shortest", str(out_mp4)])
    log.info("YouTube videosu hazır → %s", out_mp4)


def build_shorts(bg_v: Path, podcast_mp3: Path, out_mp4: Path,
                 start: float, duration: float) -> None:
    """Dikey 1080x1920 Shorts kesiti (ses dalgalı)."""
    color = f"0x{ACCENT[0]:02X}{ACCENT[1]:02X}{ACCENT[2]:02X}"
    filt = (
        f"[1:a]showwaves=s=1080x320:mode=cline:colors={color}:rate=25,format=yuva420p[w];"
        f"[0:v][w]overlay=(W-w)/2:(H-h)/2+300:shortest=1,format=yuv420p[v]"
    )
    _run(["ffmpeg", "-y", "-loop", "1", "-i", str(bg_v),
          "-ss", str(start), "-t", str(duration), "-i", str(podcast_mp3),
          "-filter_complex", filt, "-map", "[v]", "-map", "1:a",
          "-c:v", "libx264", "-preset", "medium", "-crf", "20",
          "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p",
          "-shortest", str(out_mp4)])
    log.info("Shorts hazır → %s", out_mp4)


def _ffprobe_duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True)
        return float(out.stdout.strip())
    except Exception:  # noqa: BLE001
        return 0.0


def assemble(date_str: str, episode_no: int = 1, make_short: bool = True,
             audio_only: bool = False) -> dict:
    out_dir = output_dir(date_str)
    script_path = out_dir / "script.json"
    voice_raw = out_dir / "voice_raw.mp3"
    if not script_path.exists():
        raise FileNotFoundError(f"{script_path} yok.")
    if not voice_raw.exists():
        raise FileNotFoundError(f"{voice_raw} yok. Önce voice_generator çalıştırın.")

    data = json.loads(script_path.read_text(encoding="utf-8"))
    # Bölüm numarasını başlığa doğru yansıt: "Bölüm[ N][:]" önekini her durumda
    # (numarasız "Bölüm:" ya da öneksiz başlık dahil) doğru numarayla yeniden kur.
    _t = re.sub(r"^\s*B[öo]l[üu]m\s*\d*\s*[:\-–—]?\s*", "", data["title"]).strip()
    title = f"Bölüm {episode_no}: {_t}"

    nnn = f"{episode_no:03d}"
    cover = out_dir / "cover.jpg"
    bg = out_dir / "background.png"
    bg_v = out_dir / "background_vertical.png"
    podcast_mp3 = out_dir / f"episode_{nnn}.mp3"
    video_mp4 = out_dir / f"episode_{nnn}.mp4"

    # Podcast için her zaman: kapak + ses
    make_cover(title, episode_no, date_str, cover)
    build_podcast_mp3(voice_raw, cover, podcast_mp3, title, episode_no)

    result = {
        "episode_no": episode_no,
        "title": title,
        "podcast_mp3": str(podcast_mp3),
        "cover": str(cover),
        "duration_sec": round(_ffprobe_duration(podcast_mp3), 1),
    }

    if audio_only:
        # Otomasyon (podcast-only): video/shorts üretme
        db.log_step(date_str, "audio_assembler", "ok", duration_sec=result["duration_sec"])
        log.info("Montaj (sadece ses): %.0f sn (~%.1f dk).",
                 result["duration_sec"], result["duration_sec"] / 60)
        return result

    # Video (YouTube)
    make_background(title, episode_no, date_str, (1920, 1080), bg)
    build_video(bg, podcast_mp3, video_mp4)
    result["video_mp4"] = str(video_mp4)

    if make_short:
        try:
            short_mp4 = out_dir / f"short_{nnn}.mp4"
            make_background(title, episode_no, date_str, (1080, 1920), bg_v, vertical=True)
            # Shorts kesimi: shorts_segment ipucu yoksa 20. saniyeden 50 sn
            seg = data.get("shorts_segment", {})
            start = 20.0
            # chapters'tan ipucuna en yakın başlangıcı bul
            hint = (seg.get("start_hint") or "").lower()
            for ch in data.get("chapters", []):
                if hint and hint in ch["label"].lower():
                    start = float(ch["t"])
                    break
            build_shorts(bg_v, podcast_mp3, short_mp4, start, 50.0)
            result["short_mp4"] = str(short_mp4)
        except Exception as e:  # noqa: BLE001
            log.warning("Shorts üretilemedi (atlanıyor): %s", e)

    db.log_step(date_str, "audio_assembler", "ok", duration_sec=result["duration_sec"])
    log.info("Montaj tamam: %.0f sn (~%.1f dk).",
             result["duration_sec"], result["duration_sec"] / 60)
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Future with Serdar — montaj")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--episode", type=int, default=1)
    ap.add_argument("--no-short", action="store_true")
    args = ap.parse_args()
    res = assemble(args.date, args.episode, make_short=not args.no_short)
    print("\n=== ÇIKTILAR ===")
    for k in ("podcast_mp3", "video_mp4", "short_mp4", "cover"):
        if k in res:
            print(f"  {k}: {res[k]}")
    print(f"  süre: {res['duration_sec']:.0f} sn (~{res['duration_sec']/60:.1f} dk)")


if __name__ == "__main__":
    main()
