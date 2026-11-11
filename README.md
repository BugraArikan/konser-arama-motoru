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

| Site | Liste | Fiyat |
|---|---|---|
| Bubilet | Şehir bazlı `/{sehir}/etiket/konser` sayfaları, DOM'dan kart ayrıştırma. Tarayıcı açamazsa sayfanın HTML'i doğrudan indirilir. | Karttaki "2250₺"; yoksa etkinlik sayfası. Bubilet sunucu IP'lerine Cloudflare doğrulaması gösteriyor; bu durumda o gün atlanır (aşağıya bakın). |
| Biletix | Sayfanın kendi kullandığı Solr arama servisi (`/solr/tr/select`) | Her etkinliğin sayfasındaki "…₺'den itibaren"; HTML'de yoksa sayfa tarayıcıda açılır. Tükenenler atlanır. |
| Passo | Kategori sayfası açılır, `ticketingweb.passo.com.tr` JSON yanıtları dinlenir; gelmezse DOM | Liste JSON'u → `geteventdetails` detay API'si → etkinlik sayfasının yüklediği tüm JSON'lar → sayfa metni. İlk ham JSON örnekleri `data/debug/passo/` altına yazılır. |

Bir seçici bulunamazsa sayfanın HTML'i ve ekran görüntüsü `data/debug/` altına yazılır ve
Actions artifact'ına eklenir. Hata ayıklarken önce ona bakın.

Scraper'lar CSS class isimlerine bağlı değil (`/etkinlik/` linklerinden kart çıkarıyor),
yine de siteler değişirse ilk bakılacak yer `scrapers/` klasörü. Bir site hata verirse
diğerleri çalışmaya devam eder.

### Bubilet ve Cloudflare

Bubilet, otomatik trafiği Cloudflare doğrulamasıyla durduruyor. Scraper bu doğrulamayı
aşmaya çalışmaz; doğrulama gelince loga yazar, ekran görüntüsünü `data/debug/` altına koyar
ve Bubilet'i atlar. Bubilet verisi için en sağlam yol Bubilet'ten veri erişimi (API ya da
iş ortaklığı akışı) istemektir.

## Temizleme ve tekilleştirme

- Fiyat: `"2895₺'den itibaren"`, `"1.450,50 TL"` gibi metinler sayıya çevrilir.
- Tarih: `"28 Kasım Cts 15:00"`, `"05.12.2026"`, ISO zaman damgası → `tarih` (date) + `saat`.
  Yıl yazmıyorsa en yakın gelecek yıl alınır.
- Şehir: kaynak boş bırakırsa `etl/sehir.py` mekan ve başlık metninde il adı arar
  ("FiBa Salon IKSV - Istanbul", "Birsen Tezer | Mersin"), bulamazsa bilinen mekan
  sözlüğüne (`VENUE_CITY`) bakar. Yeni mekan eklemek için o sözlüğe bir satır yeterli.
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

## Otomatik temizlik

Her yüklemeden sonra `etl/load.py` içindeki `cleanup_stale` çalışır:

1. Bu çalıştırmada güncellenmeyen ilanları (`son_guncelleme` < çalıştırmanın başladığı an) siler.
2. Hiç ilanı kalmayan konserleri siler.

Silme kaynak bazında ve korumalıdır: bir site o gün hiç veri getirmediyse (ör. Bubilet
Cloudflare'e takıldı) ya da gelecek tarihli ilanlarının yarısından fazlası birden
kaybolduysa o sitenin eski ilanları silinmez, logda uyarı çıkar. Eşik `STALE_MIN_RATIO`
ortam değişkeniyle ayarlanır (varsayılan `0.5`, `0` kontrolü kapatır). Temizliği
atlamak için: `python pipeline.py --no-cleanup`.

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
