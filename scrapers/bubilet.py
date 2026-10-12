"""Bubilet: şehir bazlı konser etiket sayfaları sunucuda render ediliyor.

Kart sınıf isimleri sık değiştiği için CSS class'ına bağlanmıyoruz. Her
`/etkinlik/` linkinden yukarı çıkıp tek bir etkinliği kapsayan en büyük kutuyu
kart sayıyor, metin satırlarından tarih ve fiyatı ayıklıyoruz.

Sayfa açılmazsa aynı sayfanın sunucu HTML'ini doğrudan indirip JS kapalı bir
sekmede ayrıştırıyoruz. Kartta fiyat yoksa etkinliğin kendi sayfasından tamamlanıyor.

Bubilet, GitHub Actions gibi sunucu IP'lerinden gelen otomatik trafiğe Cloudflare
doğrulaması gösteriyor. Bu doğrulamayı aşmaya çalışmıyoruz: sayfa doğrulama olarak
gelirse bunu açıkça loglayıp Bubilet'i o gün için atlıyoruz, diğer kaynaklar çalışmaya
devam ediyor. Zaman aşımı beklemesi de yaşanmıyor.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from .common import (
    PRICE_TEXT_RE, BotChallenge, RawEvent, is_bot_challenge, accept_cookies, best_price_text, browser_page, click_load_more,
    dump_debug, fill_prices_from_pages, http_get, scroll_to_bottom,
)

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
EVENT_LINK = 'a[href*="/etkinlik/"]'

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
    // a.href yerine ham attribute: HTML JS kapalı sekmeye yüklendiğinde de çalışsın.
    const href = (a.getAttribute('href') || '').split('?')[0];
    if (!href) continue;
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
    joined = " ".join(lines)
    date = next((l for l in lines if DATE_RE.search(l)), "")
    pm = PRICE_TEXT_RE.search(date)
    if pm:  # tarih ve fiyat aynı metin düğümündeyse fiyatı ayır
        date = date[:pm.start()].strip()
    # "₺" ayrı düğümdeyse fiyatın rakamları saate yapışık kalır: "22:002250" -> "22:00"
    date = re.sub(r"(\d{1,2}:\d{2})\d[\d.,]*$", r"\1", date)
    # "2250" ve "₺" ayrı düğümlerde olabildiği için birleşik metinde arıyoruz.
    price = best_price_text(joined)
    title = card.get("title") or next(
        (l for l in lines if not DATE_RE.search(l) and not PRICE_TEXT_RE.search(l)
         and l != card.get("venue")), ""
    )
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


def _cards_rendered(page, url: str) -> list[dict]:
    page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    if is_bot_challenge(page.title()) or is_bot_challenge(page.content()):
        raise BotChallenge(url)
    accept_cookies(page)
    # state="attached": ilk eşleşen link gizli bir menüde olsa bile beklemeyi bitirir.
    # Varsayılan "visible" beklemesi Actions'taki zaman aşımının sebebiydi.
    page.wait_for_selector(EVENT_LINK, state="attached", timeout=30_000)
    click_load_more(page)
    scroll_to_bottom(page)
    return page.evaluate(EXTRACT_JS)


def _cards_from_html(page, url: str) -> list[dict]:
    html = http_get(url)
    if not html:
        return []
    if is_bot_challenge(html):
        raise BotChallenge(url)
    ctx = page.context.browser.new_context(java_script_enabled=False)
    try:
        p = ctx.new_page()
        p.set_content(html, wait_until="domcontentloaded")
        return p.evaluate(EXTRACT_JS)
    finally:
        ctx.close()


def scrape(headless: bool = True, cities: dict[str, str] | None = None) -> list[RawEvent]:
    events: list[RawEvent] = []
    with browser_page(headless) as page:
        for slug, city in (cities or CITIES).items():
            url = f"{BASE}/{slug}/etiket/konser"
            cards: list[dict] = []
            try:
                try:
                    cards = _cards_rendered(page, url)
                except BotChallenge:
                    raise
                except Exception as exc:
                    log.warning("Bubilet %s tarayıcıda açılamadı (%s), HTML'den deneniyor", url, exc)
                    dump_debug(page, f"bubilet-{slug}")
                if not cards:
                    cards = _cards_from_html(page, url)
            except BotChallenge:
                dump_debug(page, f"bubilet-{slug}-dogrulama")
                log.error("Bubilet bu IP'den gelen otomatik erişimi Cloudflare doğrulamasıyla durdurdu; "
                          "Bubilet bugün atlanıyor (%d etkinlik toplanmıştı).", len(events))
                break
            city_events = [e for c in cards if (e := card_to_event(c, city))]
            log.info("Bubilet %s: %d etkinlik, %d tanesinde fiyat var", city, len(city_events),
                     sum(1 for e in city_events if e.fiyat_ham))
            events.extend(city_events)

    # Aynı etkinlik birden çok şehir sayfasında görünebilir.
    events = list({e.link: e for e in events}.values())
    fill_prices_from_pages(events)
    return events
