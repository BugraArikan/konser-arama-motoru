"""Biletix: liste sayfası JS ile Solr arama servisinden doldurulur.

Sayfanın kendisi boş bir kabuk olduğu için DOM yerine aynı Solr uç noktasını
tarayıcı oturumu içinden (çerezlerle) sayfa sayfa çekiyoruz. Solr yanıtında fiyat
alanı yok, bu yüzden fiyat_ham boş kalır.
"""
from __future__ import annotations

import logging
from urllib.parse import urlencode

from .common import RawEvent, browser_page

log = logging.getLogger("scraper.biletix")

BASE = "https://www.biletix.com"
SOLR = BASE + "/solr/tr/select/"
PAGE_SIZE = 200


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


def scrape(headless: bool = True, max_events: int = 5000) -> list[RawEvent]:
    events: list[RawEvent] = []
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
            docs = data.get("docs", [])
            events.extend(doc_to_event(d) for d in docs)
            log.info("Biletix: %s/%s", start + len(docs), data.get("numFound"))
            if not docs or start + len(docs) >= data.get("numFound", 0):
                break
            start += PAGE_SIZE
    return events
