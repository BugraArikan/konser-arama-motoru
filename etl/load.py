"""Adım 3 (Load): temiz tabloları Supabase'e upsert eder.

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


def load(konserler: pd.DataFrame, ilanlar: pd.DataFrame, client=None) -> None:
    client = client or get_client()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    k = konserler.assign(son_guncelleme=now)
    i = ilanlar.assign(son_guncelleme=now)
    # İlanlar konserlere foreign key ile bağlı, önce konserler yazılmalı.
    upsert(client, "konserler", to_records(k))
    upsert(client, "konser_ilanlari", to_records(i))
