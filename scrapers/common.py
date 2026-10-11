"""Scraper'ların ortak parçaları: ham kayıt şeması, tarayıcı açma, kaydırma."""
from __future__ import annotations

import html as _html
import logging
import os
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

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
        # PLAYWRIGHT_CHROMIUM_EXECUTABLE: hazır kurulu bir Chromium'u kullanmak için (opsiyonel).
        exe = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None
        browser: Browser = p.chromium.launch(headless=headless, executable_path=exe)
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


# ---------- fiyat yardımcıları ----------

# "2250₺", "1.100,00₺'den itibaren", "750 TL". Saatin hemen arkasına yapışık fiyatı da
# ("22:002250₺") doğru böler: rakam ya da ':' ile başlayan bir sayının ortasından başlamaz,
# ama "SS:DD" saatinin bittiği yerden başlayabilir.
PRICE_TEXT_RE = re.compile(
    r"(?:(?<=:\d\d)|(?<![\d:.,]))(\d[\d.]*(?:,\d{1,2})?)\s*(?:₺|TL(?![A-Za-zÇĞİÖŞÜçğıöşü]))"
    r"(\s*['’]?\s*(?:den|dan)\s+(?:itibaren|başlayan))?",
)
TAG_RE = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.S | re.I)
# Sayfadaki fiyat-dışı küçük rakamları (ör. "1 TL bağış") elemek için alt sınır.
MIN_TICKET_PRICE = 20.0


def html_to_text(html: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(TAG_RE.sub(" ", html)))


def price_value(raw: str) -> float | None:
    from etl.clean import parse_price  # temizleme kuralı tek yerde dursun
    return parse_price(raw)


def best_price_text(text: str) -> str:
    """Metindeki en düşük bilet fiyatını ham haliyle döndürür.

    "...'den itibaren" ile biten fiyatlar sitenin kendi "en düşük fiyat" bilgisidir,
    varsa onlar tercih edilir. Yoksa metindeki tüm fiyatların en düşüğü alınır.
    """
    found = []
    for m in PRICE_TEXT_RE.finditer(text or ""):
        v = price_value(m.group(1))
        if v is not None and v >= MIN_TICKET_PRICE:
            found.append((not m.group(2), v, m.group(0).strip()))
    if not found:
        return ""
    return min(found)[2]


def http_get(url: str, headers: dict | None = None, timeout: int = 20, retries: int = 2) -> str | None:
    """Basit GET. Sunucuda render edilen sayfalar ve JSON API'ler için tarayıcıdan çok daha hızlı."""
    h = {"User-Agent": USER_AGENT, "Accept-Language": "tr-TR,tr;q=0.9"}
    h.update(headers or {})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
                return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):
                log.debug("GET %s -> %s", url, e.code)
                return None
        except Exception as e:  # ağ hatası: kısa bekleyip tekrar dene
            log.debug("GET %s hata: %s", url, e)
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    return None


def map_concurrent(fn, items, workers: int = 8) -> list:
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))


def fill_prices_from_pages(events: list[RawEvent], workers: int = 8, limit: int | None = None) -> int:
    """fiyat_ham'ı boş olan etkinliklerin detay sayfasını indirip fiyatı oradan alır."""
    todo = [e for e in events if not e.fiyat_ham and e.link][:limit]
    if not todo:
        return 0
    prices = map_concurrent(lambda e: best_price_text(html_to_text(http_get(e.link) or "")), todo, workers)
    filled = 0
    for e, p in zip(todo, prices):
        if p:
            e.fiyat_ham = p
            filled += 1
    log.info("Detay sayfalarından %d/%d fiyat bulundu", filled, len(todo))
    return filled


DEBUG_DIR = Path(os.environ.get("SCRAPE_DEBUG_DIR", "data/debug"))


def dump_debug(page: Page, name: str) -> None:
    """Seçici bulunamadığında sayfanın HTML'ini ve ekran görüntüsünü saklar (Actions artifact'ına girer)."""
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        (DEBUG_DIR / f"{name}.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(DEBUG_DIR / f"{name}.png"), full_page=True)
        log.warning("Hata ayıklama dökümü: %s/%s.(html|png), sayfa başlığı: %r", DEBUG_DIR, name, page.title())
    except Exception as exc:
        log.warning("Döküm alınamadı: %s", exc)


def accept_cookies(page: Page) -> None:
    """Çerez banner'ı tıklamaları engelleyebiliyor; varsa kapatır."""
    for name in ("Kabul Et", "Tümünü Kabul Et", "Kabul et", "Accept", "Tamam", "Anladım"):
        try:
            btn = page.get_by_role("button", name=name, exact=True)
            if btn.count() and btn.first.is_visible():
                btn.first.click(timeout=2000)
                return
        except Exception:
            pass
