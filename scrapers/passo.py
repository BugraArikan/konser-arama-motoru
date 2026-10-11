"""Passo: Angular uygulaması, liste verisini ticketingweb.passo.com.tr API'sinden alır.

Liste uç noktasının adı ve gövdesi zaman zaman değiştiği için onu sabit
kodlamıyoruz. Sayfayı açıp kaydırırken API'den dönen JSON yanıtlarını
dinliyor, içinde etkinliğe benzeyen nesneleri (isim + tarih alanı) topluyoruz.
API'den hiçbir şey gelmezse DOM'daki /etkinlik/ linklerine düşüyoruz.

Fiyat üç kademede aranır:
1. Liste JSON'undaki fiyat alanları (anahtarında price/fiyat geçen sayılar).
2. Bulunamazsa etkinlik detay API'si: /api/passoweb/geteventdetails/{seo}/{id}/118
3. O da boşsa etkinlik sayfası tarayıcıda açılıp DOM'daki "₺" metni okunur.
"""
from __future__ import annotations

import json
import logging
import re

from .common import (
    RawEvent, accept_cookies, best_price_text, browser_page, click_load_more, dump_debug,
    http_get, map_concurrent, scroll_to_bottom,
)

log = logging.getLogger("scraper.passo")

BASE = "https://www.passo.com.tr"
API_HOST = "ticketingweb.passo.com.tr"
CATEGORY_URL = BASE + "/tr/kategori/muzik-konser-bileti/8615"

NAME_KEYS = ("name", "eventName", "title")
DATE_KEYS = ("date", "eventDate", "startDate", "eventStartDate", "beginDate")
VENUE_KEYS = ("venueName", "venue", "placeName", "locationName")
CITY_KEYS = ("cityName", "city")
DETAIL_API = "https://" + API_HOST + "/api/passoweb/geteventdetails/{seo}/{id}/118"
API_HEADERS = {"Accept": "application/json", "Origin": BASE, "Referer": BASE + "/"}
MAX_RENDERED_PRICE_PAGES = 150
PRICE_KEY_RE = re.compile(r"price|fiyat|amount|tutar", re.I)
# İndirim, hizmet bedeli vb. bilet fiyatı değildir; en düşüğü seçerken araya karışmasın.
NOT_PRICE_KEY_RE = re.compile(r"discount|fee|commission|tax|vat|indirim|komisyon|hizmet|count|id$|type|currency", re.I)
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


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and re.fullmatch(r"\s*\d+(?:[.,]\d+)?\s*", v):
        return float(v.replace(",", "."))
    return None


def find_prices(obj, key: str = "") -> list[float]:
    """JSON ağacındaki tüm bilet fiyatı adaylarını toplar (minPrice, prices[].price, ...)."""
    out: list[float] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                out.extend(find_prices(v, k))
            elif PRICE_KEY_RE.search(k) and not NOT_PRICE_KEY_RE.search(k):
                n = _num(v)
                if n and n > 0:
                    out.append(n)
    elif isinstance(obj, list):
        for v in obj:
            out.extend(find_prices(v, key))
    return out


def min_price(obj) -> str:
    prices = find_prices(obj)
    return f"{min(prices):g}" if prices else ""


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
        fiyat_ham=min_price(o),
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
EVENT_LINK = 'a[href*="/etkinlik/"]'


def dom_card_to_event(card: dict) -> RawEvent | None:
    lines = card["lines"]
    if not lines:
        return None
    date = next((l for l in lines if DATE_RE.search(l)), "")
    price = best_price_text(" ".join(lines))
    rest = [l for l in lines if l != date and not PRICE_RE.search(l)]
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


def _seo_and_id(link: str) -> tuple[str, str]:
    m = re.search(r"/etkinlik/([^/]+)/(\d+)", link)
    return (m.group(1), m.group(2)) if m else ("", "")


def detail_price(e: RawEvent) -> str:
    seo, eid = _seo_and_id(e.link)
    if not eid:
        return ""
    body = http_get(DETAIL_API.format(seo=seo, id=eid), headers=API_HEADERS)
    if not body:
        return ""
    try:
        return min_price(json.loads(body).get("value") or {})
    except (ValueError, AttributeError):
        return ""


def _fill_prices(page, events: list[RawEvent]) -> None:
    todo = [e for e in events if not e.fiyat_ham]
    for e, p in zip(todo, map_concurrent(detail_price, todo)):
        e.fiyat_ham = p
    log.info("Passo detay API: %d/%d fiyat bulundu", sum(1 for e in todo if e.fiyat_ham), len(todo))

    todo = [e for e in events if not e.fiyat_ham and e.link][:MAX_RENDERED_PRICE_PAGES]
    for e in todo:
        try:
            page.goto(e.link, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_selector("text=/\\d[\\d.]*(,\\d{2})?\\s*(₺|TL)/", state="attached", timeout=15_000)
            e.fiyat_ham = best_price_text(page.inner_text("body"))
        except Exception:
            continue
    if todo:
        log.info("Passo DOM yedeği: %d/%d sayfada fiyat bulundu", sum(1 for e in todo if e.fiyat_ham), len(todo))


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
        page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=45_000)
        accept_cookies(page)
        try:
            page.wait_for_selector(EVENT_LINK, state="attached", timeout=30_000)
        except Exception:
            log.warning("Passo: etkinlik linkleri görünmedi, API yanıtlarına güveniliyor")
            dump_debug(page, "passo-kategori")
        click_load_more(page, texts=("Daha Fazla Göster", "Daha Fazla", "Daha fazla"))
        scroll_to_bottom(page)
        page.wait_for_timeout(2000)

        if api_objs:
            events = [api_obj_to_event(o) for o in api_objs.values()]
            source = "API"
        else:
            cards = page.evaluate(DOM_JS)
            events = [e for c in cards if (e := dom_card_to_event(c))]
            source = "DOM"
        page.remove_listener("response", on_response)
        log.info("Passo (%s): %d etkinlik, %d tanesinde listede fiyat var", source, len(events),
                 sum(1 for e in events if e.fiyat_ham))
        _fill_prices(page, events)
    return events
