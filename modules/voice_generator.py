"""Modül 3 — voice_generator (Faz 2)

Senaryo → ElevenLabs → voice_raw.mp3 + paragraf zaman damgaları.

- Voice ID: env'den (ELEVENLABS_VOICE_ID) — Serdar'ın klonu
- Model: eleven_multilingual_v2
- Paragraf bazında üretim; previous_text/next_text ile tonlama sürekliliği
- pronunciation_map.json ile telaffuz düzeltmesi (string replace)
- ffmpeg concat ile birleştirme

Bağımsız çalıştırma:
    python -m modules.voice_generator --date 2026-06-15
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from elevenlabs import VoiceSettings
from elevenlabs.client import ElevenLabs

from utils.config_loader import require_env, get_env, load_config
from utils import db
from utils.logging_utils import get_logger
from utils.paths import PRONUNCIATION_PATH, output_dir

log = get_logger("voice")

# Varsayılanlar (config.yaml 'voice' bölümü yoksa kullanılır)
_DEFAULT_MODEL = "eleven_v3"
_DEFAULT_FORMAT = "mp3_44100_128"
_DEFAULT_SETTINGS = {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0}


def _load_pronunciation() -> dict[str, str]:
    data = json.loads(PRONUNCIATION_PATH.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def apply_pronunciation(text: str, mapping: dict[str, str]) -> str:
    """Telaffuz sözlüğünü kelime sınırına saygılı şekilde uygular."""
    for term, repl in mapping.items():
        # Büyük/küçük harf duyarsız, kelime sınırlı (mümkünse)
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        text = pattern.sub(repl, text)
    return text


def split_paragraphs(script: str) -> list[str]:
    """Senaryoyu paragraflara böler (boş satır veya tek satır = paragraf)."""
    raw = [p.strip() for p in re.split(r"\n\s*\n", script) if p.strip()]
    if len(raw) <= 1:
        # Boş satır yoksa satır satır böl
        raw = [p.strip() for p in script.splitlines() if p.strip()]
    return raw


def _ffprobe_duration(path: Path) -> float:
    """MP3 süresini saniye olarak döndürür."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())
    except Exception:  # noqa: BLE001
        return 0.0


def _concat_mp3(parts: list[Path], out_path: Path) -> None:
    """ffmpeg concat demuxer ile MP3'leri birleştirir."""
    listfile = out_path.with_suffix(".txt")
    listfile.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-c", "copy", str(out_path)],
        capture_output=True, check=True,
    )
    listfile.unlink(missing_ok=True)


def generate_voice(date_str: str) -> dict:
    """script.json okur, voice_raw.mp3 + voice_timestamps.json üretir."""
    require_env("ELEVENLABS_API_KEY")
    voice_id = require_env("ELEVENLABS_VOICE_ID")

    vcfg = load_config().get("voice", {})
    model_id = vcfg.get("model", _DEFAULT_MODEL)
    output_format = vcfg.get("output_format", _DEFAULT_FORMAT)
    settings_dict = vcfg.get("settings", _DEFAULT_SETTINGS)
    log.info("Ses modeli: %s | ayarlar: %s", model_id, settings_dict)

    out_dir = output_dir(date_str)
    script_path = out_dir / "script.json"
    if not script_path.exists():
        raise FileNotFoundError(f"{script_path} yok. Önce script_writer çalıştırın.")
    data = json.loads(script_path.read_text(encoding="utf-8"))
    script = data["script"]

    mapping = _load_pronunciation()
    paragraphs = split_paragraphs(script)
    log.info("%d paragraf seslendirilecek.", len(paragraphs))

    client = ElevenLabs(api_key=get_env("ELEVENLABS_API_KEY"))
    settings = VoiceSettings(**settings_dict)
    # eleven_v3 previous_text/next_text desteklemiyor; diğer modeller destekliyor
    supports_context = "v3" not in model_id

    parts: list[Path] = []
    timestamps: list[dict] = []
    cursor = 0.0
    tmpdir = Path(tempfile.mkdtemp(prefix="fws_voice_"))

    for i, para in enumerate(paragraphs):
        spoken = apply_pronunciation(para, mapping)

        kwargs = dict(
            voice_id=voice_id,
            text=spoken,
            model_id=model_id,
            output_format=output_format,
            voice_settings=settings,
        )
        if supports_context:
            kwargs["previous_text"] = paragraphs[i - 1] if i > 0 else None
            kwargs["next_text"] = paragraphs[i + 1] if i < len(paragraphs) - 1 else None

        audio = client.text_to_speech.convert(**kwargs)
        part_path = tmpdir / f"part_{i:03d}.mp3"
        with open(part_path, "wb") as f:
            for chunk in audio:
                if chunk:
                    f.write(chunk)
        parts.append(part_path)

        dur = _ffprobe_duration(part_path)
        timestamps.append({
            "index": i,
            "start": round(cursor, 2),
            "end": round(cursor + dur, 2),
            "text": para[:120],
        })
        cursor += dur
        log.info("  [%d/%d] %.1fs — %s", i + 1, len(paragraphs), dur, para[:50])

    out_mp3 = out_dir / "voice_raw.mp3"
    _concat_mp3(parts, out_mp3)
    total = _ffprobe_duration(out_mp3)

    ts_path = out_dir / "voice_timestamps.json"
    ts_path.write_text(json.dumps({
        "date": date_str,
        "duration_sec": round(total, 2),
        "char_count": len(script),
        "paragraphs": timestamps,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # Geçici parçaları temizle
    for p in parts:
        p.unlink(missing_ok=True)
    try:
        tmpdir.rmdir()
    except OSError:
        pass

    log.info("voice_raw.mp3 yazıldı → %s (%.1fs, %d karakter).",
             out_mp3, total, len(script))
    db.log_step(date_str, "voice_generator", "ok", duration_sec=total)
    return {"mp3": str(out_mp3), "duration_sec": total, "char_count": len(script)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Future with Serdar — seslendirme")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    args = ap.parse_args()
    res = generate_voice(args.date)
    print(f"\nSes hazır: {res['mp3']}")
    print(f"Süre: {res['duration_sec']:.0f} sn (~{res['duration_sec']/60:.1f} dk) "
          f"| {res['char_count']} karakter")


if __name__ == "__main__":
    main()
