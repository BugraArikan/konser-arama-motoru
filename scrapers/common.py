"""Scraper'ların ortak parçaları: ham kayıt şeması, tarayıcı açma, kaydırma."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from playwright.sync_api import Browser, Page, sync_playwright

log = logging.getLogger("scraper")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

# ham_konserler.csv sütunları. Temizleme burada yapılmaz, metinler olduğu gibi yazılır.
RAW_COLUMNS = [
    "kaynak", "baslik", "tarih_ham", "mekan", "sehir",
    "fiyat_ham", "link", "kaynak_id", "cekilme_zamani",
]


@dataclass
class RawEvent:
    kaynak: str
    baslik: str
    tarih_ham: str = ""
    mekan: str = ""
    sehir: str = ""
    fiyat_ham: str = ""
    link: str = ""
    kaynak_id: str = ""
    cekilme_zamani: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict:
        return asdict(self)


@contextmanager
def browser_page(headless: bool = True):
    """Türkçe yerel ayarlı tek bir sayfa açar ve iş bitince kapatır."""
    with sync_playwright() as p:
        browser: Browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="tr-TR",
            timezone_id="Europe/Istanbul",
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        page.set_default_timeout(30_000)
        try:
            yield page
        finally:
            context.close()
            browser.close()


def scroll_to_bottom(page: Page, max_rounds: int = 30, pause_ms: int = 1200) -> None:
    """Lazy-load listeler için sayfa yüksekliği değişmeyene kadar aşağı kaydırır."""
    last_height = 0
    for _ in range(max_rounds):
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(pause_ms)
        height = page.evaluate("document.body.scrollHeight")
        if height == last_height:
            break
        last_height = height


def click_load_more(page: Page, texts=("Daha Fazla", "Daha fazla", "Tümünü Gör"), max_clicks: int = 20) -> None:
    """'Daha fazla' tarzı butonlar varsa kaybolana kadar tıklar."""
    for _ in range(max_clicks):
        clicked = False
        for t in texts:
            btn = page.get_by_role("button", name=t)
            if btn.count() and btn.first.is_visible():
                btn.first.click()
                page.wait_for_timeout(1500)
                clicked = True
                break
        if not clicked:
            return
