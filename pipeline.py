"""Uçtan uca ETL: scrape -> clean -> load.

  python pipeline.py                 # hepsi
  python pipeline.py --skip-scrape   # mevcut data/ham_konserler.csv ile
  python pipeline.py --dry-run       # Supabase'e yazmadan sadece CSV üret
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from etl.clean import clean
from etl.load import load

DATA = Path("data")
RAW = DATA / "ham_konserler.csv"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-scrape", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.skip_scrape:
        from scrape import run
        from scrapers import SCRAPERS
        if run(list(SCRAPERS), RAW) == 0:
            logging.error("Hiçbir kaynaktan veri gelmedi, durduruluyor.")
            sys.exit(1)

    konserler, ilanlar = clean(pd.read_csv(RAW, dtype=str))
    konserler.to_csv(DATA / "konserler.csv", index=False)
    ilanlar.to_csv(DATA / "ilanlar.csv", index=False)
    logging.info("%d ilan, %d konser (%d tanesi birden fazla sitede)",
                 len(ilanlar), len(konserler), int((konserler["kaynak_sayisi"] > 1).sum()))

    if not args.dry_run:
        load(konserler, ilanlar)


if __name__ == "__main__":
    main()
