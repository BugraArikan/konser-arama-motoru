from datetime import date

import pandas as pd

from etl.clean import clean
from etl.load import load, to_records
from tests.test_clean import TODAY, _raw


class FakeClient:
    def __init__(self):
        self.calls = []

    def table(self, name):
        client = self

        class Q:
            def upsert(self, rows, on_conflict):
                client.calls.append((name, rows, on_conflict))
                return self

            def execute(self):
                return None
        return Q()


def test_load_writes_konserler_first_with_json_safe_values():
    raw = _raw([
        ("biletix", "Duman", "2026-11-21T17:30:00Z", "Zorlu PSM", "İstanbul", "", "https://b/1", "1", ""),
        ("bubilet", "Duman Konseri", "21 Kasım Cts 20:30", "Zorlu PSM", "İstanbul", "900₺", "https://u/1", "1", ""),
    ])
    konserler, ilanlar = clean(raw, TODAY)
    fake = FakeClient()
    load(konserler, ilanlar, client=fake)

    assert [c[0] for c in fake.calls] == ["konserler", "konser_ilanlari"]
    k = fake.calls[0][1][0]
    assert k["tarih"] == "2026-11-21" and k["kaynaklar"] == ["biletix", "bubilet"]
    biletix_row = next(r for r in fake.calls[1][1] if r["kaynak"] == "biletix")
    assert biletix_row["fiyat"] is None   # NaN JSON'a None olarak gitmeli
    assert isinstance(k["kaynak_sayisi"], int)


def test_to_records_handles_nan():
    df = pd.DataFrame({"a": [1.0, float("nan")], "d": [date(2026, 1, 1), None]})
    assert to_records(df) == [{"a": 1.0, "d": "2026-01-01"}, {"a": None, "d": None}]
