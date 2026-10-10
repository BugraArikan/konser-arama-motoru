"""Adım 1 (Extract): tüm kaynakları çeker, data/ham_konserler.csv'ye yazar.

Bir kaynak hata verirse diğerleri yine çalışır; hiçbir kaynaktan veri gelmezse
çıkış kodu 1 olur ki zamanlanmış iş kırmızıya düşsün.
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

from scrapers import SCRAPERS
from scrapers.common import RAW_COLUMNS

log = logging.getLogger("scrape")


def run(sources: list[str], out: Path, headless: bool = True) -> int:
    rows: list[dict] = []
    for name in sources:
        try:
            events = SCRAPERS[name](headless=headless)
            log.info("%s: %d ham kayıt", name, len(events))
            rows.extend(e.to_dict() for e in events)
        except Exception:
            log.exception("%s scraper'ı başarısız oldu", name)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RAW_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    log.info("%d kayıt -> %s", len(rows), out)
    return len(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", nargs="+", default=list(SCRAPERS), choices=list(SCRAPERS))
    ap.add_argument("--out", type=Path, default=Path("data/ham_konserler.csv"))
    ap.add_argument("--headed", action="store_true", help="Tarayıcıyı görünür aç (hata ayıklama)")
    args = ap.parse_args()
    if run(args.sources, args.out, headless=not args.headed) == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
