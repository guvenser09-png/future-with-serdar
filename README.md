# Future with Serdar — Otomatik Günlük AI Podcast Sistemi

Detaylı tasarım için **[CLAUDE.md](./CLAUDE.md)**'ye bakın. Bu dosya hızlı başlangıç içindir.

## Durum: Faz 1 (Veri + Senaryo)

- [x] Proje iskeleti, config, Supabase şeması
- [x] `news_collector` — RSS toplama, dedup, Claude puanlama
- [x] `script_writer` — Türkçe senaryo üretimi
- [x] Kabul kriteri: `python orchestrator.py --dry-run` ile okunabilir senaryo
- [ ] Faz 2 — ses + montaj (ElevenLabs, ffmpeg)
- [ ] Faz 3 — yayın + otomasyon (RSS, YouTube, Telegram, GitHub Actions)

## Kurulum

```bash
cd ~/future-with-serdar
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env içine en azından ANTHROPIC_API_KEY yazın.
# Supabase opsiyonel — boş bırakırsanız DB loglama atlanır, dry-run yine çalışır.
```

## Kullanım

```bash
# Tüm Faz 1 akışı: haber topla → puanla → seç → senaryo yaz
python orchestrator.py --dry-run

# Belirli tarih
python orchestrator.py --date 2026-06-15 --dry-run

# Modülleri tek tek (CLAUDE.md: her modül bağımsız çalışır)
python -m modules.news_collector --date 2026-06-15
python -m modules.script_writer  --date 2026-06-15
```

Çıktılar `output/YYYYMMDD/` altında:
- `daily_news.json` — toplanan + puanlanan + seçilen haberler
- `script.json` — üretilen senaryo (title, description, script, chapters, shorts_segment, youtube_tags)

## Supabase (opsiyonel)

`db/schema.sql` içeriğini Supabase SQL Editor'da çalıştırın, ardından `.env`'e
`SUPABASE_URL` ve `SUPABASE_SERVICE_KEY` ekleyin. Böylece haberler `news_items`'a,
adımlar `pipeline_logs`'a yazılır ve aynı haber iki bölümde tekrar işlenmez.

## Yapılandırma

- Kaynak listesi ve eşik değerleri: `config.yaml`
- Telaffuz sözlüğü (Faz 2): `pronunciation_map.json`
- Model: CLAUDE.md uyarınca `claude-sonnet-4-6` (config.yaml `model` altında).
