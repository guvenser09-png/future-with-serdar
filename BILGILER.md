# Future with Serdar — Hızlı Başvuru

Her şeyin özeti burada. (Detaylı tasarım: `CLAUDE.md`)

## 🔗 Linkler
- **Ana sayfa (paylaş/dinle):** https://guvenser09-png.github.io/future-with-serdar/
- **RSS Feed (sadece Spotify/Apple için):** https://guvenser09-png.github.io/future-with-serdar/feed.xml
- **GitHub repo:** https://github.com/guvenser09-png/future-with-serdar
- **GitHub Actions (otomasyon durumu):** https://github.com/guvenser09-png/future-with-serdar/actions
- **Spotify for Creators:** https://creators.spotify.com
- **Spotify'da ara:** https://open.spotify.com/search/Future%20with%20Serdar

## ⚙️ Nasıl çalışıyor
- **Her gün 07:30 (TSİ)** GitHub Actions otomatik çalışır: haber topla → senaryo → seslendir (ElevenLabs eleven_v3, Serdar'ın sesi) → podcast MP3 → feed'e ekle → GitHub'a push.
- Spotify/Apple feed'i izlediği için **yeni bölüm otomatik görünür** (manuel yükleme yok).
- Aynı haber iki kez yayınlanmaz (`processed_urls.json`).
- **YouTube otomasyona dahil DEĞİL** — istediğinde manuel: aşağıdaki `--export` komutu.

## 💻 Sık kullanılan komutlar
Önce ortamı aç:
```bash
cd ~/future-with-serdar && source .venv/bin/activate
```
| İş | Komut |
|----|-------|
| Sadece senaryo (test, ücretsiz-ish) | `python orchestrator.py --dry-run` |
| Tam bölüm üret + yayınla | `python orchestrator.py --publish` |
| Belirli tarih | `python orchestrator.py --publish --date 2026-06-20` |
| Feed/kanal kapağını güncelle (yeni bölüm üretmeden) | `python -m modules.podcast_publisher --refresh-feed` |
| YouTube yükleme kiti (başlık/açıklama/etiket + mp4) | `python -m modules.youtube_publisher --export --date <tarih> --episode <N>` |

Marka/açıklama değiştirmek: `config.yaml` → `podcast_meta` düzenle → `--refresh-feed`.

## 🔑 Anahtarlar nerede
- **Yerel:** `.env` dosyası (ANTHROPIC_API_KEY, ELEVENLABS_*, R2/GITHUB/PAGES, ...). Bu dosya git'e GİRMEZ (gizli). Bilgisayarda yedekle.
- **Otomasyon (GitHub):** repo → Settings → Secrets → Actions: `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`.
- Anahtar değişirse: hem `.env` hem GitHub secret güncellenmeli.

## 🛠️ Sorun giderme
- **Yeni bölüm gelmedi:** GitHub → Actions → "Günlük Podcast" çalışmasına bak. Kırmızıysa loga bak.
- **Spotify'da görünmüyor:** RSS sahiplik doğrulaması bitmemiş olabilir → `guvenser09@gmail.com`'a gelen Spotify e-postasındaki bağlantıya tıkla. Yeni programda yayına girmesi birkaç saat sürebilir.
- **feed.xml tarayıcıda kod gibi görünüyor:** Normal — o sayfa Spotify içindir, insan için değil.
- **Ses çok "yapay":** Daha doğal için ElevenLabs'te Professional Voice Clone'a geç, Voice ID'yi `.env`'de değiştir. Ayarlar: `config.yaml > voice`.
- **Otomasyonu durdur:** GitHub → Actions → "Günlük Podcast" → "..." → Disable workflow.
- **Manuel/test çalıştırma (bulutta):** Actions → "Günlük Podcast" → "Run workflow" (varsayılan güvenli dry-run; "publish" kutusu = gerçek yayın).

## 📌 Yapılacaklar / ileride
- [ ] Spotify görünürlük doğrulaması (e-posta onayı)
- [ ] (Opsiyonel) Apple Podcasts'e aynı feed'i ekle: podcastsconnect.apple.com
- [ ] (Opsiyonel) Telegram bildirimi: `.env`'e TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
- [ ] İleride: YouTube otomasyonu, Professional Voice Clone, Shorts zenginleştirme

## Durum
✅ Faz 1 (haber+senaryo) · ✅ Faz 2 (ses+montaj) · ✅ Faz 3 podcast (canlı + her sabah otomatik)
⏸️ YouTube (manuel, hazır) — beklemede
