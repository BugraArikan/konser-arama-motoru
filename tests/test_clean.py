from datetime import date

import pandas as pd
import pytest

from etl.clean import clean, normalize_title, parse_date, parse_price

TODAY = date(2026, 10, 3)


@pytest.mark.parametrize("raw,expected", [
    ("2895₺'den itibaren", 2895.0),
    ("1.450,50 TL", 1450.5),
    ("1.450 TL", 1450.0),
    ("750", 750.0),
    ("1450,5", 1450.5),
    ("", None),
    ("Tükendi", None),
    (None, None),
])
def test_parse_price(raw, expected):
    assert parse_price(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("28 Kasım Cts 15:00, 20:00", (date(2026, 11, 28), "15:00")),
    ("15 Ekim", (date(2026, 10, 15), None)),
    ("04 Ekim, 18 Ekim", (date(2026, 10, 4), None)),
    ("12 Şubat Per 21:00", (date(2027, 2, 12), "21:00")),      # yıl atlaması
    ("2026-07-24T17:00:00Z", (date(2026, 7, 24), "20:00")),   # UTC -> İstanbul
    ("05.12.2026 20:30", (date(2026, 12, 5), "20:30")),
    ("", (None, None)),
])
def test_parse_date(raw, expected):
    assert parse_date(raw, TODAY) == expected


def test_normalize_title():
    assert normalize_title("Selda Bağcan Konseri") == "selda bagcan"
    assert normalize_title("SELDA BAĞCAN - Bostancı Gösteri Merkezi") == "selda bagcan"
    assert normalize_title("Duman Konseri 2026") == "duman"


def _raw(rows):
    cols = ["kaynak", "baslik", "tarih_ham", "mekan", "sehir", "fiyat_ham", "link", "kaynak_id", "cekilme_zamani"]
    return pd.DataFrame([dict(zip(cols, r)) for r in rows])


def test_clean_groups_across_sites_and_dedupes():
    raw = _raw([
        ("bubilet", "Selda Bağcan Konseri", "21 Kasım Cts 20:30", "Bostancı Gösteri Merkezi", "İstanbul", "1450₺'den itibaren", "https://bubilet/a", "a", ""),
        ("bubilet", "Selda Bağcan Konseri", "21 Kasım Cts 20:30", "Bostancı Gösteri Merkezi", "İstanbul", "1450₺'den itibaren", "https://bubilet/a", "a", ""),
        ("biletix", "SELDA BAĞCAN", "2026-11-21T17:30:00Z", "Bostancı GM", "İstanbul", "", "https://biletix/1", "1", ""),
        ("passo", "Selda Bağcan", "21.11.2026 20:30", "Bostancı Gösteri Merkezi", "", "1.300,00 TL", "https://passo/9", "9", ""),
        ("passo", "Selda Bağcan", "22.11.2026 20:30", "Bostancı Gösteri Merkezi", "", "1.300,00 TL", "https://passo/10", "10", ""),
        ("bubilet", "", "21 Kasım", "", "", "", "https://bubilet/bos", "", ""),   # başlıksız, atılır
    ])
    konserler, ilanlar = clean(raw, TODAY)

    assert len(ilanlar) == 4                      # tekrar ve başlıksız satır düştü
    assert len(konserler) == 2                    # 21 ve 22 Kasım
    k21 = konserler[konserler["tarih"] == date(2026, 11, 21)].iloc[0]
    assert k21["kaynak_sayisi"] == 3
    assert k21["kaynaklar"] == ["biletix", "bubilet", "passo"]
    assert k21["min_fiyat"] == 1300.0 and k21["max_fiyat"] == 1450.0
    assert k21["sehir"] == "İstanbul"
    assert ilanlar["id"].is_unique
