"""Adım 3 (Load): temiz tabloları Supabase'e upsert eder, ardından bayat veriyi temizler.

Temizlik (cleanup_stale):
1. Bu çalıştırmada güncellenmeyen (son_guncelleme < run_start) ilanlar silinir.
   Güvenlik için kaynak bazında yapılır: bir kaynak bu çalıştırmada hiç veri
   getirmediyse (ör. Bubilet Cloudflare'e takıldı, Passo çöktü) ya da gelecek tarihli
   ilanlarının yarısından fazlası birden kaybolduysa o kaynağın eski ilanlarına dokunulmaz. Yoksa tek bir
   başarısız gün o sitenin tüm ilanlarını silerdi.
2. Hiç ilanı kalmayan (yetim) konserler silinir.

Gerekli ortam değişkenleri (asla koda veya repoya yazmayın):
  SUPABASE_URL                 ör. https://xxxx.supabase.co
  SUPABASE_SERVICE_ROLE_KEY    Project Settings > API > service_role
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone

import pandas as pd

log = logging.getLogger("load")
BATCH = 500
PAGE = 1000          # PostgREST bir istekte en fazla 1000 satır döndürür
DELETE_BATCH = 200   # id listesi URL'de gittiği için küçük tutuluyor
# Bir kaynağın bu çalıştırmada getirdiği ilan sayısı, (bu çalıştırma + silinecekler)
# toplamının bu oranından azsa o kaynak için silme atlanır. 0 verilirse kontrol kapanır.
STALE_MIN_RATIO = float(os.environ.get("STALE_MIN_RATIO", "0.5"))


def _jsonable(v):
    if isinstance(v, (list, dict)) or v is None:
        return v
    if isinstance(v, (date, datetime, pd.Timestamp)):
        return v.isoformat()
    if pd.isna(v):
        return None
    return v.item() if hasattr(v, "item") else v


def to_records(df: pd.DataFrame) -> list[dict]:
    return [{k: _jsonable(v) for k, v in row.items()} for row in df.to_dict(orient="records")]


def get_client():
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL ve SUPABASE_SERVICE_ROLE_KEY ortam değişkenleri tanımlı olmalı.")
    return create_client(url, key)


def upsert(client, table: str, records: list[dict]) -> None:
    for i in range(0, len(records), BATCH):
        client.table(table).upsert(records[i:i + BATCH], on_conflict="id").execute()
    log.info("%s: %d satır upsert edildi", table, len(records))


def load(konserler: pd.DataFrame, ilanlar: pd.DataFrame, client=None, now: str | None = None) -> None:
    client = client or get_client()
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    k = konserler.assign(son_guncelleme=now)
    i = ilanlar.assign(son_guncelleme=now)
    # İlanlar konserlere foreign key ile bağlı, önce konserler yazılmalı.
    upsert(client, "konserler", to_records(k))
    upsert(client, "konser_ilanlari", to_records(i))


def _fetch_column(client, table: str, column: str) -> list:
    """Tablodaki bir sütunun tüm değerleri, 1000'lik sayfalarla."""
    out, start = [], 0
    while True:
        rows = client.table(table).select(column).range(start, start + PAGE - 1).execute().data or []
        out.extend(r[column] for r in rows)
        if len(rows) < PAGE:
            return out
        start += PAGE


def _delete_ids(client, table: str, ids: list) -> None:
    for i in range(0, len(ids), DELETE_BATCH):
        client.table(table).delete().in_("id", ids[i:i + DELETE_BATCH]).execute()


def cleanup_stale(client, ilanlar: pd.DataFrame, run_start: str, today: str | None = None) -> dict:
    """Bu çalıştırmada görülmeyen ilanları ve ilansız kalan konserleri siler.

    run_start: pipeline'ın başladığı an (UTC, ISO). load() bundan sonra yazdığı için
    bu çalıştırmada gelen her ilanın son_guncelleme değeri run_start'tan yeni olur.
    """
    today = today or date.today().isoformat()
    report: dict = {"silinen_ilan": {}, "atlanan_kaynak": {}, "silinen_konser": 0}
    loaded = ilanlar["kaynak"].value_counts().to_dict()
    sources = sorted(set(loaded) | {"bubilet", "biletix", "passo"})

    for src in sources:
        n_new = int(loaded.get(src, 0))
        stale = (client.table("konser_ilanlari").select("id", count="exact")
                 .eq("kaynak", src).lt("son_guncelleme", run_start).execute())
        n_stale = stale.count or 0
        if not n_stale:
            continue
        # Oran kontrolü sadece gelecek tarihli bayat ilanlarla yapılır: tarihi geçmiş konserlerin
        # listeden düşmesi normaldir ve zamanla birikip kontrolü kalıcı olarak tıkamamalı.
        n_stale_future = (client.table("konser_ilanlari").select("id", count="exact")
                          .eq("kaynak", src).lt("son_guncelleme", run_start)
                          .gte("tarih", today).execute().count or 0)
        if n_new == 0:
            report["atlanan_kaynak"][src] = f"bu çalıştırmada veri gelmedi, {n_stale} eski ilan korundu"
        elif STALE_MIN_RATIO and n_new < STALE_MIN_RATIO * (n_new + n_stale_future):
            report["atlanan_kaynak"][src] = (f"sadece {n_new} ilan geldi, listeden düşen {n_stale_future} "
                                             f"gelecek tarihli ilan var; silme atlandı (eşik {STALE_MIN_RATIO:.0%})")
        else:
            (client.table("konser_ilanlari").delete()
             .eq("kaynak", src).lt("son_guncelleme", run_start).execute())
            report["silinen_ilan"][src] = n_stale

    for src, why in report["atlanan_kaynak"].items():
        log.warning("Bayat ilan temizliği %s için atlandı: %s", src, why)

    used = set(_fetch_column(client, "konser_ilanlari", "konser_id"))
    orphans = [kid for kid in _fetch_column(client, "konserler", "id") if kid not in used]
    _delete_ids(client, "konserler", orphans)
    report["silinen_konser"] = len(orphans)
    log.info("Temizlik: %s", report)
    return report
