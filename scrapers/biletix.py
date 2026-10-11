"""Biletix: liste sayfası JS ile Solr arama servisinden doldurulur.

Etkinlik listesini sayfanın kendi kullandığı Solr uç noktasından, tarayıcı
oturumu içinden (çerezlerle) sayfa sayfa çekiyoruz. Solr yanıtında fiyat yok;
fiyatı her etkinliğin kendi sayfasından alıyoruz. Etkinlik sayfası sunucuda
render edildiği için ("1.100,00₺'den itibaren") HTML'i doğrudan indirmek yetiyor,
bulunamayanlar için sayfa tarayıcıda açılıp DOM'dan okunuyor.
"""
from __future__ import annotations

import logging
from urllib.parse import urlencode

from .common import RawEvent, best_price_text, browser_page, fill_prices_from_pages

log = logging.getLogger("scraper.biletix")

BASE = "https://www.biletix.com"
SOLR = BASE + "/solr/tr/select/"
PAGE_SIZE = 200
# DOM yedeğinde tarayıcıda açılacak en fazla sayfa (her biri birkaç saniye sürer).
MAX_RENDERED_PRICE_PAGES = 150
PRICE_SELECTOR = "text=/\\d[\\d.]*(,\\d{2})?\\s*₺/"


def _first(v):
    if isinstance(v, list):
        return v[0] if v else ""
    return v or ""


def _link(doc: dict) -> str:
    if doc.get("link_url"):
        return doc["link_url"]
    kind = "etkinlik-grup" if doc.get("type") == "group" else "etkinlik"
    return f"{BASE}/{kind}/{doc['id']}/TURKIYE/tr"


def doc_to_event(doc: dict) -> RawEvent:
    return RawEvent(
        kaynak="biletix",
        baslik=_first(doc.get("name")) or doc.get("sname", ""),
        tarih_ham=doc.get("start", ""),
        mekan=_first(doc.get("venue")) or doc.get("svenue", ""),
        sehir=_first(doc.get("city")),
        fiyat_ham="",
        link=_link(doc),
        kaynak_id=str(doc.get("id", "")),
    )


def drop_covered_groups(docs: list[dict]) -> list[dict]:
    """Grup kayıtları (çok tarihli turneler) alt etkinlikleriyle birlikte de geliyor.

    Alt etkinliği listede olan grubu atıyoruz, yoksa aynı konser iki ilan olur.
    """
    child_groups = {g.strip() for d in docs if d.get("type") != "group" for g in d.get("group", [])}
    return [d for d in docs if d.get("type") != "group" or _first(d.get("name")).strip() not in child_groups]


def _fill_prices_rendered(page, events: list[RawEvent]) -> None:
    todo = [e for e in events if not e.fiyat_ham][:MAX_RENDERED_PRICE_PAGES]
    for e in todo:
        try:
            page.goto(e.link, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_selector(PRICE_SELECTOR, state="attached", timeout=10_000)
            e.fiyat_ham = best_price_text(page.inner_text("body"))
        except Exception:
            continue  # tükenmiş veya fiyatı henüz açıklanmamış etkinlik
    log.info("Biletix DOM yedeği: %d/%d sayfada fiyat bulundu", sum(1 for e in todo if e.fiyat_ham), len(todo))


def scrape(headless: bool = True, max_events: int = 5000) -> list[RawEvent]:
    docs: list[dict] = []
    with browser_page(headless) as page:
        # Ana sayfayı açıp çerezleri/bot kontrolünü geçiyoruz.
        page.goto(BASE + "/search/TURKIYE/tr?category_sb=MUSIC", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        start = 0
        while start < max_events:
            params = {
                "q": "*:*",
                "fq": ["category:MUSIC", "end:[NOW TO NOW+1YEAR]"],
                "sort": "start asc",
                "start": str(start),
                "rows": str(PAGE_SIZE),
                "wt": "json",
            }
            # Aynı isimli iki fq parametresi gerektiği için URL'i elle kuruyoruz.
            url = SOLR + "?" + urlencode(params, doseq=True)
            resp = page.request.get(url, headers={"Referer": BASE + "/"})
            if not resp.ok:
                log.warning("Biletix Solr %s döndü (start=%s)", resp.status, start)
                break
            data = resp.json().get("response", {})
            batch = data.get("docs", [])
            docs.extend(batch)
            log.info("Biletix: %s/%s", start + len(batch), data.get("numFound"))
            if not batch or start + len(batch) >= data.get("numFound", 0):
                break
            start += PAGE_SIZE

        events = [doc_to_event(d) for d in drop_covered_groups(docs)]
        # Tükenmiş etkinliklerin sayfasında fiyat yok, boşuna istek atmıyoruz.
        soldout = {str(d.get("id")) for d in docs if str(d.get("status", "")).startswith("s02")}
        on_sale = [e for e in events if e.kaynak_id not in soldout]
        fill_prices_from_pages(on_sale)
        _fill_prices_rendered(page, on_sale)
    return events
