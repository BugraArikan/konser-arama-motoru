"""Scraper ayrıştırma mantığı, canlı siteye gitmeden örnek HTML/JSON ile test edilir."""
import pytest

from scrapers import biletix, bubilet, passo

BUBILET_HTML = """
<div class="grid">
  <div class="card">
    <a href="/istanbul/etkinlik/selda-bagcan-konseri"><img src="x.jpg"><h3>Selda Bağcan Konseri</h3></a>
    <a href="/mekan/bostanci-gosteri-merkezi">Bostancı Gösteri Merkezi</a>
    <span>21 Kasım Cts 20:30</span><span>1450₺'den itibaren</span>
  </div>
  <div class="card">
    <a href="/istanbul/etkinlik/harry-potter"><h3>Harry Potter In Concert</h3></a>
    <a href="/istanbul/etkinlik/harry-potter">Bilet Al</a>
    <a href="/mekan/volkswagen-arena">Volkswagen Arena</a>
    <p>28 Kasım Cts 15:00, 20:00</p><p>2895₺'den itibaren</p>
  </div>
</div>
"""


@pytest.fixture(scope="module")
def page():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"Chromium yok: {exc}")
        pg = browser.new_page()
        yield pg
        browser.close()


def test_bubilet_cards(page):
    page.set_content(BUBILET_HTML)
    cards = page.evaluate(bubilet.EXTRACT_JS)
    events = [bubilet.card_to_event(c, "İstanbul") for c in cards]
    assert len(events) == 2
    e = events[0]
    assert e.baslik == "Selda Bağcan Konseri"
    assert e.mekan == "Bostancı Gösteri Merkezi"
    assert e.tarih_ham == "21 Kasım Cts 20:30"
    assert e.fiyat_ham == "1450₺'den itibaren"
    assert events[1].tarih_ham.startswith("28 Kasım")


def test_biletix_doc():
    doc = {"name": ["Duman"], "start": "2026-11-21T17:30:00Z", "venue": ["Zorlu PSM"],
           "city": ["İstanbul"], "id": "123", "type": "performance"}
    e = biletix.doc_to_event(doc)
    assert (e.baslik, e.mekan, e.sehir) == ("Duman", "Zorlu PSM", "İstanbul")
    assert e.link == "https://www.biletix.com/etkinlik/123/TURKIYE/tr"
    assert biletix.doc_to_event({**doc, "type": "group"}).link.endswith("/etkinlik-grup/123/TURKIYE/tr")


def test_passo_find_events_in_nested_json():
    payload = {"isError": False, "value": {"events": [
        {"id": 77, "name": "Mabel Matiz", "date": "2026-12-05T20:30:00", "venueName": "KüçükÇiftlik",
         "cityName": "İstanbul", "minPrice": 900, "seoUrl": "mabel-matiz-konseri"},
        {"id": 78, "name": "Kategori başlığı"},   # tarihi yok, etkinlik değil
    ]}}
    found = passo.find_events(payload)
    assert len(found) == 1
    e = passo.api_obj_to_event(found[0])
    assert e.link == "https://www.passo.com.tr/tr/etkinlik/mabel-matiz-konseri/77"
    assert (e.fiyat_ham, e.sehir) == ("900", "İstanbul")
