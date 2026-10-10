# Konser ETL

Bubilet, Biletix ve Passo'daki konserleri her gün çeker, temizleyip tekilleştirir ve
Supabase PostgreSQL'e yükler.

```
scrape.py      -> data/ham_konserler.csv        (Extract, Playwright)
etl/clean.py   -> data/konserler.csv, ilanlar.csv (Transform, Pandas)
etl/load.py    -> Supabase: konserler, konser_ilanlari (Load, upsert)
pipeline.py    hepsini sırayla çalıştırır
```

## Kaynaklar nasıl çekiliyor

| Site | Yöntem | Not |
|---|---|---|
| Bubilet | Şehir bazlı `/{sehir}/etiket/konser` sayfaları, DOM'dan kart ayrıştırma | Şehir listesi `scrapers/bubilet.py` içindeki `CITIES` |
| Biletix | Sayfanın kendi kullandığı Solr arama servisi (`/solr/tr/select`), tarayıcı oturumu içinden | Listede fiyat yok, `fiyat` boş kalır |
| Passo | Kategori sayfası açılır, `ticketingweb.passo.com.tr` API'sinden dönen JSON dinlenir; gelmezse DOM'a düşülür | Kategori: Müzik/Konser (8615) |

Scraper'lar CSS class isimlerine bağlı değil (`/etkinlik/` linklerinden kart çıkarıyor),
yine de siteler değişirse ilk bakılacak yer `scrapers/` klasörü. Bir site hata verirse
diğerleri çalışmaya devam eder.

## Temizleme ve tekilleştirme

- Fiyat: `"2895₺'den itibaren"`, `"1.450,50 TL"` gibi metinler sayıya çevrilir.
- Tarih: `"28 Kasım Cts 15:00"`, `"05.12.2026"`, ISO zaman damgası → `tarih` (date) + `saat`.
  Yıl yazmıyorsa en yakın gelecek yıl alınır.
- Site içi tekrar: aynı link bir kez kalır.
- Siteler arası eşleştirme: normalize başlık (Türkçe karakter, "konseri", yıl vb. atılır)
  + gün + şehir aynıysa aynı konserdir. Sonuç `konserler` tablosunda tek satır,
  her sitedeki ilan `konser_ilanlari` tablosunda.
- `fiyat_karsilastirma` view'ı her konser için site başına en düşük fiyatı yan yana verir.

## Kurulum

1. **Supabase**: yeni proje açın, SQL Editor'da `sql/schema.sql` dosyasını çalıştırın.
2. **GitHub**: bu klasörün içeriğini kendi reponuza koyun. Repo > Settings > Secrets and
   variables > Actions altına iki secret ekleyin:
   - `SUPABASE_URL` (ör. `https://xxxx.supabase.co`)
   - `SUPABASE_SERVICE_ROLE_KEY` (Supabase > Project Settings > API > service_role)
3. Workflow (`.github/workflows/daily-etl.yml`) her gün 06:00 (İstanbul) çalışır. İlk denemeyi
   Actions sekmesinden **Run workflow** ile elle yapabilirsiniz. Ham ve temiz CSV'ler her
   çalışmada 14 gün saklanan artifact olarak indirilebilir.

## Yerelde çalıştırma

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env   # değerleri doldurun
set -a; source .env; set +a

pytest                                  # testler
python scrape.py --sources bubilet --headed   # tek siteyi tarayıcıyı görerek dene
python pipeline.py --dry-run            # Supabase'e yazmadan CSV üret
python pipeline.py                      # tam çalıştırma
```

Service role anahtarı tam yetkilidir: `.env` dosyası `.gitignore`'da, repoya girmemeli.
Web arayüzü gibi okuyucu taraflar `anon` anahtarını kullanmalı; tablolarda sadece okuma
izni açık.
