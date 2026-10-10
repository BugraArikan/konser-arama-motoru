"""Bubilet: şehir bazlı konser etiket sayfaları sunucuda render ediliyor.

Kart sınıf isimleri sık değiştiği için CSS class'ına bağlanmıyoruz. Her
`/etkinlik/` linkinden yukarı çıkıp tek bir etkinliği kapsayan en büyük kutuyu
kart sayıyor, metin satırlarından tarih ve fiyatı ayıklıyoruz.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from .common import RawEvent, browser_page, click_load_more, scroll_to_bottom

log = logging.getLogger("scraper.bubilet")

BASE = "https://www.bubilet.com.tr"
# Şehir slug'ı -> görünen ad. İhtiyaca göre genişletin.
CITIES = {
    "istanbul": "İstanbul",
    "ankara": "Ankara",
    "izmir": "İzmir",
    "antalya": "Antalya",
    "bursa": "Bursa",
    "eskisehir": "Eskişehir",
}

MONTHS = "Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık"
DATE_RE = re.compile(rf"\b\d{{1,2}}\s+({MONTHS})\b")
PRICE_RE = re.compile(r"\d[\d.,]*\s*(₺|TL)")

# Tarayıcıda çalışır: her etkinlik linki için kartı bulur ve satırları döndürür.
EXTRACT_JS = r"""
() => {
  const textNodes = root => {
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const res = [];
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      const t = n.textContent.replace(/\s+/g, ' ').trim();
      if (t) res.push(t);
    }
    return res;
  };
  const out = [];
  const seen = new Set();
  const links = [...document.querySelectorAll('a[href*="/etkinlik/"]')];
  const distinctEventLinks = el => new Set(
    [...el.querySelectorAll('a[href*="/etkinlik/"]')].map(a => a.getAttribute('href'))
  ).size;
  for (const a of links) {
    const href = a.href.split('?')[0];
    if (seen.has(href)) continue;
    seen.add(href);
    let card = a;
    while (card.parentElement && distinctEventLinks(card.parentElement) === 1) {
      card = card.parentElement;
    }
    const venueEl = card.querySelector('a[href*="/mekan/"]');
    const heading = card.querySelector('h1,h2,h3,h4,h5');
    out.push({
      link: href,
      title: (heading ? heading.innerText : a.innerText || '').trim(),
      venue: venueEl ? venueEl.innerText.trim() : '',
      // innerText bitişik inline öğeleri birleştirebildiği için metin düğümlerini tek tek alıyoruz.
      lines: textNodes(card),
    });
  }
  return out;
}
"""


def card_to_event(card: dict, city: str) -> RawEvent | None:
    lines = card.get("lines", [])
    date = next((l for l in lines if DATE_RE.search(l)), "")
    pm = PRICE_RE.search(date)
    if pm:  # tarih ve fiyat aynı metin düğümündeyse fiyatı ayır
        date = date[:pm.start()].strip()
    price = next((l for l in lines if PRICE_RE.search(l)), "")
    if price:
        price = price[PRICE_RE.search(price).start():]
    title = card.get("title") or next(
        (l for l in lines if l not in (date, price, card.get("venue"))), ""
    )
    # Başlık satırına tarih/fiyat karışmışsa ilk satırı al.
    title = title.split("\n")[0].strip()
    if not title:
        return None
    link = urljoin(BASE + "/", card["link"])
    slug = link.rstrip("/").split("/")[-1]
    return RawEvent(
        kaynak="bubilet",
        baslik=title,
        tarih_ham=date,
        mekan=card.get("venue", ""),
        sehir=city,
        fiyat_ham=price,
        link=link,
        kaynak_id=slug,
    )


def scrape(headless: bool = True, cities: dict[str, str] | None = None) -> list[RawEvent]:
    events: list[RawEvent] = []
    with browser_page(headless) as page:
        for slug, city in (cities or CITIES).items():
            url = f"{BASE}/{slug}/etiket/konser"
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_selector('a[href*="/etkinlik/"]', timeout=20_000)
            except Exception as exc:  # şehir sayfası yoksa veya boşsa diğerine geç
                log.warning("Bubilet %s atlandı: %s", url, exc)
                continue
            click_load_more(page)
            scroll_to_bottom(page)
            cards = page.evaluate(EXTRACT_JS)
            city_events = [e for c in cards if (e := card_to_event(c, city))]
            log.info("Bubilet %s: %d etkinlik", city, len(city_events))
            events.extend(city_events)
    return events
