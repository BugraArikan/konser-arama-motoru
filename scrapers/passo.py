"""Passo: Angular uygulaması, liste verisini ticketingweb.passo.com.tr API'sinden alır.

Liste uç noktasının adı ve gövdesi zaman zaman değiştiği için onu sabit
kodlamıyoruz. Sayfayı açıp kaydırırken API'den dönen JSON yanıtlarını
dinliyor, içinde etkinliğe benzeyen nesneleri (isim + tarih alanı) topluyoruz.
API'den hiçbir şey gelmezse DOM'daki /etkinlik/ linklerine düşüyoruz.
"""
from __future__ import annotations

import logging
import re

from .common import RawEvent, browser_page, click_load_more, scroll_to_bottom

log = logging.getLogger("scraper.passo")

BASE = "https://www.passo.com.tr"
API_HOST = "ticketingweb.passo.com.tr"
CATEGORY_URL = BASE + "/tr/kategori/muzik-konser-bileti/8615"

NAME_KEYS = ("name", "eventName", "title")
DATE_KEYS = ("date", "eventDate", "startDate", "eventStartDate", "beginDate")
VENUE_KEYS = ("venueName", "venue", "placeName", "locationName")
CITY_KEYS = ("cityName", "city")
PRICE_KEYS = ("minPrice", "lowestPrice", "price", "minimumPrice")
ID_KEYS = ("id", "eventId")
SEO_KEYS = ("seoUrl", "seoName", "url")


def _pick(d: dict, keys) -> str:
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            if isinstance(v, dict):  # ör. venue: {name: ...}
                v = v.get("name", "")
            return str(v)
    return ""


def find_events(obj) -> list[dict]:
    """JSON ağacında isim ve tarih alanı olan sözlükleri bulur."""
    found = []
    if isinstance(obj, dict):
        if _pick(obj, NAME_KEYS) and _pick(obj, DATE_KEYS):
            found.append(obj)
        else:
            for v in obj.values():
                found.extend(find_events(v))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(find_events(v))
    return found


def api_obj_to_event(o: dict) -> RawEvent:
    eid = _pick(o, ID_KEYS)
    seo = _pick(o, SEO_KEYS)
    if seo.startswith("http"):
        link = seo
    elif seo and eid:
        link = f"{BASE}/tr/etkinlik/{seo.strip('/')}/{eid}"
    else:
        link = ""
    return RawEvent(
        kaynak="passo",
        baslik=_pick(o, NAME_KEYS),
        tarih_ham=_pick(o, DATE_KEYS),
        mekan=_pick(o, VENUE_KEYS),
        sehir=_pick(o, CITY_KEYS),
        fiyat_ham=_pick(o, PRICE_KEYS),
        link=link,
        kaynak_id=eid,
    )


DOM_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  for (const a of document.querySelectorAll('a[href*="/etkinlik/"]')) {
    const href = a.href.split('?')[0];
    if (seen.has(href)) continue;
    seen.add(href);
    let card = a;
    while (card.parentElement && card.parentElement.querySelectorAll('a[href*="/etkinlik/"]').length === 1) {
      card = card.parentElement;
    }
    const lines = [];
    const w = document.createTreeWalker(card, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      const t = n.textContent.replace(/\s+/g, ' ').trim();
      if (t) lines.push(t);
    }
    out.push({ link: href, lines });
  }
  return out;
}
"""

DATE_RE = re.compile(r"\d{1,2}[./]\d{1,2}[./]\d{4}|\d{1,2}\s+(Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)")
PRICE_RE = re.compile(r"\d[\d.,]*\s*(₺|TL)")


def dom_card_to_event(card: dict) -> RawEvent | None:
    lines = card["lines"]
    if not lines:
        return None
    date = next((l for l in lines if DATE_RE.search(l)), "")
    price = next((l for l in lines if PRICE_RE.search(l)), "")
    rest = [l for l in lines if l not in (date, price)]
    m = re.search(r"/(\d+)/?$", card["link"])
    return RawEvent(
        kaynak="passo",
        baslik=rest[0] if rest else "",
        tarih_ham=date,
        mekan=rest[1] if len(rest) > 1 else "",
        fiyat_ham=price,
        link=card["link"],
        kaynak_id=m.group(1) if m else "",
    )


def scrape(headless: bool = True) -> list[RawEvent]:
    api_objs: dict[str, dict] = {}

    def on_response(resp):
        if API_HOST not in resp.url or "json" not in resp.headers.get("content-type", ""):
            return
        try:
            for o in find_events(resp.json()):
                key = _pick(o, ID_KEYS) or (_pick(o, NAME_KEYS) + _pick(o, DATE_KEYS))
                api_objs[key] = o
        except Exception:
            pass

    with browser_page(headless) as page:
        page.on("response", on_response)
        page.goto(CATEGORY_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_selector('a[href*="/etkinlik/"]', timeout=30_000)
        except Exception:
            log.warning("Passo: etkinlik linkleri görünmedi, API yanıtlarına güveniliyor")
        click_load_more(page, texts=("Daha Fazla Göster", "Daha Fazla", "Daha fazla"))
        scroll_to_bottom(page)
        page.wait_for_timeout(2000)

        if api_objs:
            events = [api_obj_to_event(o) for o in api_objs.values()]
            log.info("Passo (API): %d etkinlik", len(events))
            return events

        cards = page.evaluate(DOM_JS)
        events = [e for c in cards if (e := dom_card_to_event(c))]
        log.info("Passo (DOM): %d etkinlik", len(events))
        return events
