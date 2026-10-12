"""Passo: Angular uygulaması, liste verisini ticketingweb.passo.com.tr API'sinden alır.

Liste uç noktasının adı ve gövdesi zaman zaman değiştiği için onu sabit
kodlamıyoruz. Sayfayı açıp kaydırırken API'den dönen JSON yanıtlarını
dinliyor, içinde etkinliğe benzeyen nesneleri (isim + tarih alanı) topluyoruz.
API'den hiçbir şey gelmezse DOM'daki /etkinlik/ linklerine düşüyoruz.

Fiyat dört kademede aranır, ilk bulunan kullanılır:
1. Liste JSON'undaki fiyat alanları.
2. Etkinlik detay API'si (/api/passoweb/geteventdetails/{seo}/{id}/118), tarayıcı
   oturumunun çerezleriyle.
3. Etkinlik sayfası tarayıcıda açılır; sayfanın yüklediği TÜM Passo JSON yanıtları
   (kategori/koltuk/fiyat servisleri dahil) taranır.
4. Hâlâ yoksa sayfa metnindeki "₺/TL" okunur, gerekirse "Bilet Al"a tıklanıp tekrar bakılır.

"Fiyat alanı" geniş tutuldu: anahtarında price, fiyat, amount, tutar, ücret, bedel, cost
geçen; değeri sayı ya da "1.250,00 TL" gibi metin olan her alan. İlk birkaç ham JSON
yanıtı data/debug/passo/ altına yazılır ki alan isimleri değişirse görülebilsin.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re

from .common import (
    DEBUG_DIR, MIN_TICKET_PRICE, USER_AGENT, RawEvent, accept_cookies, best_price_text,
    browser_page, click_load_more, dump_debug, price_value, scroll_to_bottom,
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
PASSO_HOST_RE = re.compile(r"https://[^/]*passo\.com\.tr/")
# Tarayıcıda açılacak en fazla etkinlik sayfası ve aynı anda açık sekme sayısı.
MAX_RENDERED_PRICE_PAGES = 400
PAGE_CONCURRENCY = 4
DEBUG_SAMPLES = 3
PRICE_KEY_RE = re.compile(r"price|fiyat|amount|tutar|[uü]cret|bedel|cost|fare|tarife", re.I)
# İndirim, hizmet bedeli, tarih, sayaç vb. bilet fiyatı değildir; en düşüğü seçerken araya karışmasın.
NOT_PRICE_KEY_RE = re.compile(
    r"(?i:discount|fee|commission|tax|vat|indirim|komisyon|hizmet|count|id$|type|currency|"
    r"date|time|tarih|code|kod|status|name|visible|show)|^(is|has)[A-Z_]",
)
PRICE_TEXT_LOCATOR = "text=/\\d[\\d.]*(,\\d{2})?\\s*(₺|TL)/"
BUY_BUTTONS = ("Bilet Al", "Satın Al", "Hemen Al", "Biletler")
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
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and re.search(r"\d", v) and len(v) <= 40:
        return price_value(v)   # "1.250,00 TL", "₺900", "500 - 1500 TL" -> ilk sayı
    return None


def find_prices(obj, key: str = "") -> list[float]:
    """JSON ağacındaki tüm bilet fiyatı adaylarını toplar.

    Fiyat anahtarının altındaki iç içe yapıları da kapsar: {"price": {"amount": 900}},
    {"prices": [{"value": 900}]} gibi.
    """
    out: list[float] = []
    in_price = bool(key) and PRICE_KEY_RE.search(key) and not NOT_PRICE_KEY_RE.search(key)
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                out.extend(find_prices(v, k if not in_price or PRICE_KEY_RE.search(k) else key))
            elif (PRICE_KEY_RE.search(k) or (in_price and k in ("value", "min", "amount"))) \
                    and not NOT_PRICE_KEY_RE.search(k):
                n = _num(v)
                if n is not None and n >= MIN_TICKET_PRICE:
                    out.append(n)
    elif isinstance(obj, list):
        for v in obj:
            if in_price and not isinstance(v, (dict, list)):
                n = _num(v)
                if n is not None and n >= MIN_TICKET_PRICE:
                    out.append(n)
            else:
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


def _save_sample(name: str, url: str, payload) -> None:
    try:
        d = DEBUG_DIR / "passo"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.json").write_text(json.dumps({"url": url, "body": payload}, ensure_ascii=False, indent=1)[:500_000],
                                        encoding="utf-8")
    except Exception as exc:
        log.debug("örnek yazılamadı: %s", exc)


def detail_price(e: RawEvent, get_json) -> str:
    """get_json(url) -> dict | None. Tarayıcı oturumundan çağrılır (çerez/başlıklar sitedeki gibi)."""
    seo, eid = _seo_and_id(e.link)
    if not eid:
        return ""
    url = DETAIL_API.format(seo=seo, id=eid)
    body = get_json(url)
    if not isinstance(body, dict):
        return ""
    return min_price(body.get("value", body))


async def _event_page_price(context, e: RawEvent, sample: bool) -> str:
    payloads: list[tuple[str, object]] = []

    async def on_response(resp):
        if not PASSO_HOST_RE.match(resp.url) or "json" not in resp.headers.get("content-type", ""):
            return
        try:
            payloads.append((resp.url, await resp.json()))
        except Exception:
            pass

    page = await context.new_page()
    page.on("response", on_response)
    try:
        await page.goto(e.link, wait_until="domcontentloaded", timeout=30_000)
        try:
            await page.wait_for_load_state("networkidle", timeout=12_000)
        except Exception:
            pass
        prices = [p for _, body in payloads for p in find_prices(body)]
        text_price = best_price_text(await page.inner_text("body"))
        if not prices and not text_price:
            # Fiyatlar bazen sadece "Bilet Al" sonrası açılan adımda yükleniyor.
            for name in BUY_BUTTONS:
                btn = page.get_by_role("button", name=name)
                if not await btn.count():
                    btn = page.get_by_role("link", name=name)
                if await btn.count():
                    try:
                        await btn.first.click(timeout=3000)
                        await page.wait_for_load_state("networkidle", timeout=10_000)
                    except Exception:
                        pass
                    break
            prices = [p for _, body in payloads for p in find_prices(body)]
            text_price = best_price_text(await page.inner_text("body"))
        if sample:
            for i, (url, body) in enumerate(payloads[:15]):
                _save_sample(f"sayfa-{e.kaynak_id}-{i:02d}", url, body)
        if prices:
            return f"{min(prices):g}"
        return text_price
    except Exception as exc:
        log.debug("Passo sayfa %s: %s", e.link, exc)
        return ""
    finally:
        await page.close()


async def _fill_from_event_pages(events: list[RawEvent], headless: bool) -> None:
    from playwright.async_api import async_playwright

    sem = asyncio.Semaphore(PAGE_CONCURRENCY)
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless, executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None)
        context = await browser.new_context(user_agent=USER_AGENT, locale="tr-TR", timezone_id="Europe/Istanbul")
        # Görsel/font indirmek fiyatı etkilemiyor, sadece yavaşlatıyor.
        await context.route(re.compile(r"\.(png|jpe?g|webp|avif|gif|svg|woff2?|ttf)(\?|$)"), lambda r: r.abort())

        async def one(i, e):
            async with sem:
                e.fiyat_ham = await _event_page_price(context, e, sample=i < DEBUG_SAMPLES)

        await asyncio.gather(*(one(i, e) for i, e in enumerate(events)))
        await browser.close()


def _fill_prices_detail(page, events: list[RawEvent]) -> None:
    samples = {"n": 0}

    def get_json(url):
        try:
            r = page.request.get(url, headers=API_HEADERS, timeout=20_000)
            body = r.json() if r.ok else None
        except Exception:
            return None
        if samples["n"] < DEBUG_SAMPLES:
            samples["n"] += 1
            _save_sample(f"detay-{samples['n']}", url, body)
        return body

    todo = [e for e in events if not e.fiyat_ham]
    for e in todo:
        e.fiyat_ham = detail_price(e, get_json)
    log.info("Passo detay API: %d/%d fiyat bulundu", sum(1 for e in todo if e.fiyat_ham), len(todo))


def run_async(coro):
    """Ayrı bir thread'de çalıştırır: sync Playwright'ın event loop'u açıkken de güvenli."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


def _fill_prices_pages(events: list[RawEvent], headless: bool) -> None:
    todo = [e for e in events if not e.fiyat_ham and e.link][:MAX_RENDERED_PRICE_PAGES]
    if todo:
        run_async(_fill_from_event_pages(todo, headless))
        log.info("Passo etkinlik sayfaları: %d/%d fiyat bulundu", sum(1 for e in todo if e.fiyat_ham), len(todo))
    log.info("Passo: %d etkinliğin %d tanesi fiyatsız kaldı", len(events), sum(1 for e in events if not e.fiyat_ham))


def scrape(headless: bool = True) -> list[RawEvent]:
    api_objs: dict[str, dict] = {}
    list_samples: list[tuple[str, object]] = []

    def on_response(resp):
        if API_HOST not in resp.url or "json" not in resp.headers.get("content-type", ""):
            return
        try:
            body = resp.json()
            found = find_events(body)
            if found and len(list_samples) < DEBUG_SAMPLES:
                list_samples.append((resp.url, body))
            for o in found:
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
        page.remove_listener("response", on_response)
        for i, (url, body) in enumerate(list_samples):
            _save_sample(f"liste-{i + 1}", url, body)

        if api_objs:
            events = [api_obj_to_event(o) for o in api_objs.values()]
            source = "API"
        else:
            cards = page.evaluate(DOM_JS)
            events = [e for c in cards if (e := dom_card_to_event(c))]
            source = "DOM"
        log.info("Passo (%s): %d etkinlik, %d tanesinde listede fiyat var", source, len(events),
                 sum(1 for e in events if e.fiyat_ham))
        _fill_prices_detail(page, events)
    _fill_prices_pages(events, headless)
    return events
