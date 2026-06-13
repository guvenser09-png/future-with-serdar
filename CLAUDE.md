# FUTURE WITH SERDAR — Otomatik Günlük AI Podcast + YouTube Sistemi

## Proje Özeti

"Future with Serdar" markası altında, her sabah otomatik üretilen ve yayınlanan Türkçe günlük yapay zekâ bülteni. Sistem gece boyunca küresel AI gündemini tarar, en önemli 3-4 gelişmeyi seçer, senaryoyu Claude API ile sahibin tonunda yazar, ElevenLabs ile sahibin klonlanmış sesiyle seslendirir, ffmpeg ile monte eder ve hem podcast platformlarına (RSS) hem YouTube'a otomatik yayınlar.

**Hedef:** İnsan müdahalesi olmadan her sabah 08:30'da (TSİ) yayında olan 6-8 dakikalık bölüm + YouTube videosu + 1 Shorts.

**Marka konumu:** Türkçe'de günlük sesli AI bülteni neredeyse yok — ilk olma avantajı hedefleniyor. İçeriğin kendisi sistemin kanıtıdır: "Bu bölümü yapay zekâ üretti, sesim klonlandı, her sabah otomatik yayınlanıyor" anlatısı markanın parçasıdır.

**Test modu:** Sistem canlıya alınmadan önce, deneme bölümleri Dünya Kupası 2026 gündemiyle liste dışı (unlisted/draft) üretilip test edilebilir (`--test-mode worldcup` flag'i). Hatalar markasız ortamda yapılır; "Future with Serdar" temiz lansmanla açılır.

---

## Teknoloji Yığını

- **Dil:** Python 3.11+
- **Veri:** RSS feed'leri + kaynak siteler (aşağıda liste) + Claude ile önem puanlama
- **Senaryo:** Anthropic Claude API (claude-sonnet-4-6)
- **Seslendirme:** ElevenLabs API — Professional Voice Clone, model: `eleven_multilingual_v2`
- **Montaj:** ffmpeg (ses + video şablonu)
- **Veritabanı/Log:** Supabase (Postgres)
- **Dosya barındırma:** Supabase Storage (MP3 + RSS XML)
- **YouTube:** YouTube Data API v3 (OAuth, resumable upload)
- **Zamanlama:** GitHub Actions cron (yedek: VPS crontab)
- **Bildirim:** Telegram Bot API

---

## Mimari: 7 Modül

```
[1. news_collector] → [2. script_writer] → [3. voice_generator]
        ↓                                          ↓
   [Supabase log]                          [4. audio_assembler]
                                            ↓             ↓
                              [5. podcast_publisher]  [6. youtube_publisher]
                                            ↓             ↓
                                   [7. orchestrator + Telegram]
```

### Modül 1 — `news_collector.py`

**Görev:** AI gündemini toplar, puanlar, günün 3-4 haberini seçer.

**Kaynak listesi (config'de tutulur, kolayca genişletilebilir):**
- Resmî bloglar: Anthropic, OpenAI, Google DeepMind, Meta AI, Mistral, xAI
- Teknoloji medyası: TechCrunch AI, The Verge AI, VentureBeat AI, Ars Technica
- Topluluk: Hacker News (AI etiketli, puan > 100), Hugging Face blog
- Türkiye: Webrazzi, ShiftDelete AI kategorisi
- Akademik (haftalık özet için): arXiv cs.AI/cs.CL öne çıkanlar

**Akış:**
1. Tüm RSS feed'lerinden son 24 saatin başlıklarını + özetlerini çek (`feedparser`)
2. Dedup: aynı haberin farklı kaynaklardaki kopyalarını birleştir (başlık benzerliği)
3. Claude API ile puanlama: her habere 0-100 önem skoru + tek cümle gerekçe. Kriterler: Türk dinleyici için pratik etki, büyüklük (model lansmanı > minör güncelleme), tazelik, "Future with Serdar" kitlesine uygunluk (AI ile üretkenlik/gelir açısı bonus puan)
4. En yüksek 3-4 haberi seç; her biri için kaynak makalenin tam metnini çek (senaryo derinliği için)
5. Çıktı: `daily_news.json` — sonraki modüllerin tek veri kaynağı
6. Supabase `news_items` tablosuna yaz (tekrar kullanım ve "bu haberi daha önce işledik mi" kontrolü için)

**Kurallar:**
- Aynı haber iki bölümde işlenmez (Supabase kontrolü)
- Doğrulanamayan/tek kaynaklı sansasyonel iddialar elenmez ama senaryoda "iddia" olarak işaretlenir
- Yavaş gün senaryosu: 24 saatte önemli haber yoksa `slow_day: true` → script_writer "derinlemesine tek konu" moduna geçer (bir aracın incelemesi, bir kavramın anlatımı)

### Modül 2 — `script_writer.py`

**Görev:** `daily_news.json` → Claude API → Türkçe podcast senaryosu.

Bölüm yapısı (~1.100-1.300 kelime ≈ 6-8 dakika):

1. **Açılış** (sabit kalıp): "Merhaba, ben Serdar. Future with Serdar'a hoş geldiniz. Bugün [tarih], işte yapay zekâ dünyasında son 24 saat." + günün en çarpıcı gelişmesinden tek cümle kanca
2. **Günün Haberleri** (3-4 haber × ~1,5 dk): Her haber için — ne oldu (2-3 cümle), neden önemli (1-2 cümle), "senin için anlamı" (1-2 cümle: Türk kullanıcı/üretici/girişimci perspektifinden pratik çıkarım). Bu son kısım programın imzasıdır — kuru haber değil, yorumlu bülten.
3. **Günün Aracı / İpucu** (~45 sn, opsiyonel): Kısa, uygulanabilir bir AI aracı veya kullanım önerisi
4. **Kapanış** (sabit kalıp): Yarına teaser + "Beni Instagram ve YouTube'da Future with Serdar olarak bulabilirsiniz" CTA + "Bu bölüm, kendi geliştirdiğim yapay zekâ sistemi tarafından otomatik üretildi" imza cümlesi

**Ton talimatları (system prompt'a gömülecek):**
- Bilgili ama kibirli değil — teknolojiyi arkadaşına anlatan mühendis tonu
- Konuşma Türkçesi: "Bakın bu önemli", "Açıkçası ben buna şaşırdım", "Şimdi gelelim asıl bombaya"
- Sesli okunmak için yazılır: kısa cümleler, parantez içi açıklama yok
- İngilizce terimler ilk geçişte tek cümleyle Türkçeleştirilir ("context window, yani modelin tek seferde işleyebildiği metin miktarı")
- Abartı ve clickbait dili yok; "devrim", "çığır" kelimeleri ancak gerçekten hak edildiğinde
- Spekülasyon ile doğrulanmış bilgi net ayrılır ("X iddia ediyor ki..." vs "X duyurdu")

**Çıktı (JSON şemayla istenir):**
```json
{
  "title": "Bölüm 12: Claude'a Yeni Rakip | 24 Haziran",
  "description": "...",
  "script": "...",
  "chapters": [{"t": 0, "label": "Açılış"}, {"t": 95, "label": "Haber 1: ..."}],
  "shorts_segment": {"start_hint": "Haber 2", "hook_line": "..."},
  "youtube_tags": ["yapay zeka", "ai haberleri", "..."]
}
```
`chapters` YouTube bölüm zaman damgaları için, `shorts_segment` günün Shorts kesimi için kullanılır.

### Modül 3 — `voice_generator.py`

**Görev:** Senaryo → ElevenLabs → ham ses dosyası.

- Voice ID: env'den (`ELEVENLABS_VOICE_ID`) — Serdar'ın Professional Voice Clone'u
- Model: `eleven_multilingual_v2`
- Ayarlar başlangıç: `stability: 0.5`, `similarity_boost: 0.75`, `style: 0.3` (config'de; ilk bölümlerde A/B testle ayarlanır)
- Uzun metin paragraf bazında parçalanır, `previous_text`/`next_text` ile tonlama sürekliliği korunarak sırayla üretilir, ffmpeg concat ile birleştirilir
- **Telaffuz sözlüğü** (`pronunciation_map.json`): senaryoya girmeden string replace. AI alanına özel: "GPT" → "ci-pi-ti", "API" → "ey-pi-ay", "LLM" → "el-el-em", "OpenAI" → "öupın-ey-ay", "Claude" → "klod", "Hugging Face" → "haging feys"... Sözlük her bölüm sonrası dinleme notlarıyla büyütülür.
- Çıktı: `voice_raw.mp3` + paragraf zaman damgaları (video senkronu için)

### Modül 4 — `audio_assembler.py`

**Görev:** Ses montajı + YouTube video render'ı, tamamen ffmpeg ile.

**Ses:**
- `intro.mp3` (5-7 sn jingle) + 0.5 sn sessizlik + `voice_raw.mp3` + 0.5 sn sessizlik + `outro.mp3`
- Loudness: `-16 LUFS`, `loudnorm` iki geçişli
- MP3, 128 kbps, 44.1 kHz, mono; ID3 etiketleri + `cover.jpg` (3000×3000)
- Süre kontrolü: < 5 dk veya > 10 dk ise Telegram uyarısı

**Video (YouTube için):**
- 1920×1080 şablon: "Future with Serdar" marka arka planı + bölüm başlığı + aktif haber başlığı kartı (chapters verisiyle senkron değişir) + dalga formu animasyonu (`showwaves` filtresi)
- PIL ile haber kartı PNG'leri üretilir, ffmpeg ile zaman damgalarına göre bindirilir
- Çıktı: `episode_NNN.mp4` (H.264, ~6-8 dk)

**Shorts:**
- `shorts_segment` ipucuyla 45-60 sn'lik dikey (1080×1920) kesit: büyük altyazı (senaryodan, kelime kelime vurgulu), kanca cümle başta
- Çıktı: `short_NNN.mp4`

### Modül 5 — `podcast_publisher.py`

**Görev:** MP3'ü yayınla, RSS'i güncelle.

- MP3 → Supabase Storage public bucket
- `feed.xml` (RSS 2.0 + iTunes namespace) yeniden üretilir; sabit URL — Spotify/Apple bu URL'i izler
- İlk kurulumda feed bir kere manuel olarak Spotify for Creators ve Apple Podcasts Connect'e tanıtılır; sonrası otomatik
- Bölüm Supabase `episodes` tablosuna işlenir

### Modül 6 — `youtube_publisher.py`

**Görev:** Video + Shorts'u YouTube'a otomatik yükle.

- YouTube Data API v3, OAuth refresh token ile (ilk yetkilendirme manuel, tek seferlik; token GitHub Secrets'ta)
- Uzun video: başlık, açıklama (chapters zaman damgalarıyla), etiketler `youtube_tags`'ten, kategori: Science & Technology, dil: tr
- Shorts: aynı gün, uzun videoya açıklamadan link
- Test modunda `privacyStatus: unlisted`, canlıda `public`
- Kota notu: video upload ~1600 birim/adet, günlük kota 10.000 — günde 2 yükleme rahat sığar
- Yükleme sonrası video ID'leri Supabase'e yazılır

### Modül 7 — `orchestrator.py` + GitHub Actions

**Görev:** Pipeline'ı sırayla çalıştır, hata yönet, raporla.

- Akış: collector → writer → voice → assembler → (podcast_publisher ∥ youtube_publisher)
- Her adım `pipeline_logs` tablosuna yazılır
- Hata: 1 retry (60 sn), yine hata → pipeline durur + Telegram'a detaylı hata. Yarım bölüm asla yayınlanmaz.
- Başarıda Telegram özeti: "✅ Bölüm 12 yayında — 7 dk 10 sn — 4 haber — Podcast: [link] — YouTube: [link] — Shorts: [link] — ElevenLabs: 11.2K karakter"
- GitHub Actions: `.github/workflows/daily.yml`, cron `30 4 * * *` (UTC 04:30 = TSİ 07:30; yayın hedefi 08:30)
- Flag'ler: `--dry-run` (senaryo üret, ses üretme), `--test-mode worldcup` (Dünya Kupası gündemiyle unlisted test bölümü), `--date YYYY-MM-DD`

---

## Supabase Şeması

```sql
news_items (id, source, url, title, summary, importance_score,
            score_reasoning, used_in_episode, collected_at)

episodes (id, episode_number, date, title, description, duration_sec,
          mp3_url, youtube_video_id, youtube_short_id, status, created_at)

pipeline_logs (id, run_date, step, status, error_message, duration_sec, created_at)

metrics (id, episode_id, platform, plays, likes, captured_at)  -- Faz 4
```

---

## Ortam Değişkenleri (.env / GitHub Secrets)

```
ANTHROPIC_API_KEY=
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_REFRESH_TOKEN=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
PODCAST_TITLE="Future with Serdar"
PODCAST_AUTHOR="Serdar"
PODCAST_BASE_URL=
```

---

## Geliştirme Fazları

### Faz 1 — Veri + Senaryo (ses yok)
1. Proje iskeleti, config, Supabase tabloları
2. `news_collector.py` — RSS toplama, dedup, Claude puanlama; bugünün gerçek AI gündemiyle test
3. `script_writer.py` — ilk senaryoyu üret, ÇIKTIYI İNSANA GÖSTER (ton onayı şart)
4. Kabul kriteri: `python orchestrator.py --dry-run` ile günün gerçek haberlerinden okunabilir senaryo

### Faz 2 — Ses + Montaj
5. `voice_generator.py` — 1 paragraf test, telaffuz sözlüğü iskeleti
6. `audio_assembler.py` — ses montajı + temel video şablonu
7. Kabul kriteri: dinlenebilir tam MP3 + izlenebilir MP4

### Faz 3 — Yayın + Otomasyon
8. `podcast_publisher.py` — Storage + RSS, feed validator'dan geçir (podba.se/validate)
9. `youtube_publisher.py` — OAuth kurulumu, unlisted test yüklemesi
10. `orchestrator.py` + Telegram + GitHub Actions cron
11. Test: `--test-mode worldcup` ile 2-3 unlisted deneme bölümü (hatalar markasız ortamda)
12. Spotify/Apple feed kaydı + YouTube kanalı public ilk bölüm
13. Kabul kriteri: insan dokunmadan uçtan uca 1 bölümün her platformda yayınlanması

### Faz 4 — İyileştirme (yayın sürerken)
- Shorts şablonunu zenginleştirme (kelime vurgulu altyazı animasyonu)
- `metrics` tablosu: Spotify/YouTube istatistiklerini günlük çekme → hangi haber türü tutuyor analizi
- Haftalık "Pazar derinlemesine" özel bölüm formatı
- Telaffuz sözlüğü genişletme
- B2B versiyonlama: pipeline'ı farklı marka/konfigürasyonla çalıştırılabilir hale getirme (çoklu config desteği)

---

## Kurallar ve Kısıtlar

- Haberler asla LLM bilgisinden yazılmaz; tek kaynak toplanan gerçek makalelerdir. Senaryodaki her iddia `daily_news.json` içindeki bir kaynağa dayanmalıdır.
- Doğrulanmamış iddialar senaryoda açıkça "iddia/söylenti" olarak işaretlenir.
- Telif: bölümlerde yalnızca lisanslı/royalty-free intro-outro müziği; kaynak makalelerden uzun alıntı yapılmaz, her şey özgün dille yeniden anlatılır.
- Abartı/clickbait dili yok — marka güveni uzun vadeli varlıktır.
- Her modül bağımsız çalıştırılabilir (`python -m modules.script_writer --date 2026-06-15`).
- Tüm ara çıktılar `output/YYYYMMDD/` klasöründe saklanır.
- Maliyet logu: her bölümde ElevenLabs karakter sayısı ve Claude token kullanımı loglanır.
