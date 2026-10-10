"""Adım 2 (Transform): ham CSV'yi temizler, tekilleştirir, siteler arası gruplar.

Çıktı iki tablo:
- konserler: her gerçek konser için bir satır (aynı sanatçı + aynı gün + aynı şehir).
- ilanlar: her sitedeki ilan için bir satır, konser_id ile konsere bağlı. Fiyat
  kıyaslaması bu tablo üzerinden yapılır.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

TZ = ZoneInfo("Europe/Istanbul")

MONTHS = {
    "ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5,
    "haziran": 6, "temmuz": 7, "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9,
    "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12,
}
TR_DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]+)(?:\s+(\d{4}))?")
NUM_DATE_RE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})")
TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")

# Başlık eşleştirirken atılan gürültü kelimeleri.
NOISE_WORDS = {
    "konseri", "konser", "konserleri", "canli", "live", "in", "concert", "tour",
    "turnesi", "turne", "ozel", "gosteri", "performansi", "ile", "ve", "the",
}
# Başlığın sonundaki "- Mekan" / "| Şehir" kısmı.
TITLE_SUFFIX_RE = re.compile(r"\s+[-–|@]\s+.*$")


# ---------- yardımcılar ----------

def tr_lower(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


def fold(s: str) -> str:
    """Türkçe karakterleri ASCII'ye indirger: 'Bağcan' -> 'bagcan'."""
    s = tr_lower(s).replace("ı", "i")
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def normalize_title(title: str) -> str:
    t = TITLE_SUFFIX_RE.sub("", str(title or ""))
    t = fold(t)
    t = re.sub(r"\b20\d\d\b", " ", t)          # yıl
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    words = [w for w in t.split() if w not in NOISE_WORDS]
    return " ".join(words)


def parse_price(raw) -> float | None:
    """'2895₺'den itibaren' -> 2895.0, '1.450,50 TL' -> 1450.5, '750' -> 750.0"""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if raw > 0 else None
    s = str(raw)
    m = re.search(r"\d[\d.,]*", s)
    if not m:
        return None
    num = m.group(0).rstrip(".,")
    if "," in num and "." in num:            # 1.450,50
        num = num.replace(".", "").replace(",", ".")
    elif "," in num:                         # 1450,50 veya 1,450
        parts = num.split(",")
        num = num.replace(",", ".") if len(parts[-1]) <= 2 else num.replace(",", "")
    elif num.count(".") >= 1 and len(num.split(".")[-1]) == 3:   # 1.450
        num = num.replace(".", "")
    try:
        v = float(num)
    except ValueError:
        return None
    return v if v > 0 else None


def parse_date(raw, today: date | None = None) -> tuple[date | None, str | None]:
    """Ham tarih metninden (tarih, 'SS:DD') çıkarır.

    '28 Kasım Cts 15:00, 20:00' -> (2026-11-28, '15:00'); yıl yoksa en yakın
    gelecek yıl seçilir. ISO zaman damgaları İstanbul saatine çevrilir.
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)) or str(raw).strip() == "":
        return None, None
    s = str(raw).strip()
    today = today or datetime.now(TZ).date()

    # ISO: 2026-07-24T12:00:00Z
    if re.match(r"\d{4}-\d{2}-\d{2}", s):
        try:
            ts = pd.Timestamp(s)
            if ts.tzinfo is not None:
                ts = ts.tz_convert(TZ)
            hm = ts.strftime("%H:%M") if "T" in s or " " in s else None
            return ts.date(), hm
        except ValueError:
            pass

    tm = TIME_RE.search(s)
    hm = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else None

    m = NUM_DATE_RE.search(s)
    if m:
        d, mo, y = map(int, m.groups())
        try:
            return date(y, mo, d), hm
        except ValueError:
            return None, hm

    m = TR_DATE_RE.search(s)
    if m and tr_lower(m.group(2)) in MONTHS:
        d, mo = int(m.group(1)), MONTHS[tr_lower(m.group(2))]
        y = int(m.group(3)) if m.group(3) else today.year
        try:
            dt = date(y, mo, d)
        except ValueError:
            return None, hm
        # Yıl verilmemiş ve tarih 60 günden eskiyse bir sonraki yıldır (ör. Aralık'ta 'Şubat').
        if not m.group(3) and (today - dt).days > 60:
            dt = date(y + 1, mo, d)
        return dt, hm
    return None, hm


def _hash(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


# ---------- ana dönüşüm ----------

def clean(raw: pd.DataFrame, today: date | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = raw.copy()
    for col in ["kaynak", "baslik", "tarih_ham", "mekan", "sehir", "fiyat_ham", "link", "kaynak_id"]:
        if col not in df:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()
    df["baslik"] = df["baslik"].str.replace(r"\s+", " ", regex=True)
    df["mekan"] = df["mekan"].str.replace(r"\s+", " ", regex=True)

    df["fiyat"] = df["fiyat_ham"].map(parse_price)
    parsed = df["tarih_ham"].map(lambda s: parse_date(s, today))
    df["tarih"] = parsed.map(lambda x: x[0])
    df["saat"] = parsed.map(lambda x: x[1])
    df["sehir"] = df["sehir"].map(lambda s: s.title() if s else s)
    df["sanatci_norm"] = df["baslik"].map(normalize_title)
    df["sehir_norm"] = df["sehir"].map(fold)

    # Başlığı veya tarihi olmayan satırlar konser olarak eşleştirilemez.
    df = df[(df["sanatci_norm"] != "") & df["tarih"].notna()].copy()

    # 1) Site içi tekilleştirme: aynı link (yoksa başlık+tarih) bir kez kalsın, en ucuz fiyatla.
    df["dedupe_key"] = df["link"].where(df["link"] != "", df["sanatci_norm"] + df["tarih"].astype(str))
    df = (df.sort_values("fiyat", na_position="last")
            .drop_duplicates(["kaynak", "dedupe_key"], keep="first"))

    # 2) Siteler arası gruplama: aynı normalize başlık + gün (+ şehir biliniyorsa).
    #    Biletix/Passo şehri her zaman vermeyebilir; şehri boş olan ilan, aynı başlık+gündeki
    #    tek şehirli gruba katılır.
    df["grup_sehir"] = df["sehir_norm"]
    known = (df[df["grup_sehir"] != ""]
             .groupby(["sanatci_norm", "tarih"])["grup_sehir"]
             .agg(lambda s: s.iloc[0] if s.nunique() == 1 else ""))
    missing = df["grup_sehir"] == ""
    df.loc[missing, "grup_sehir"] = [
        known.get((a, t), "") for a, t in zip(df.loc[missing, "sanatci_norm"], df.loc[missing, "tarih"])
    ]
    df["konser_id"] = [_hash(a, t, c) for a, t, c in zip(df["sanatci_norm"], df["tarih"], df["grup_sehir"])]
    df["id"] = [_hash(k, l or i) for k, l, i in zip(df["kaynak"], df["link"], df["dedupe_key"])]

    ilanlar = df[[
        "id", "konser_id", "kaynak", "baslik", "mekan", "sehir", "tarih", "saat",
        "fiyat", "link", "kaynak_id", "cekilme_zamani",
    ]].reset_index(drop=True)

    g = df.sort_values(["kaynak"]).groupby("konser_id")
    konserler = pd.DataFrame({
        # En kısa başlık genelde en temizi; TAMAMI BÜYÜK HARF olanlar son tercih.
        "sanatci": g["baslik"].agg(lambda s: min(s, key=lambda x: (x.isupper(), len(x)))),
        "sanatci_norm": g["sanatci_norm"].first(),
        "tarih": g["tarih"].first(),
        "saat": g["saat"].agg(lambda s: s.dropna().iloc[0] if s.notna().any() else None),
        "sehir": g["sehir"].agg(lambda s: next((x for x in s if x), "")),
        "mekan": g["mekan"].agg(lambda s: next((x for x in s if x), "")),
        "min_fiyat": g["fiyat"].min(),
        "max_fiyat": g["fiyat"].max(),
        "kaynak_sayisi": g["kaynak"].nunique(),
        "kaynaklar": g["kaynak"].agg(lambda s: sorted(set(s))),
    }).reset_index().rename(columns={"konser_id": "id"})

    return konserler, ilanlar


def main() -> None:
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser()
    ap.add_argument("--inp", type=Path, default=Path("data/ham_konserler.csv"))
    ap.add_argument("--outdir", type=Path, default=Path("data"))
    a = ap.parse_args()
    konserler, ilanlar = clean(pd.read_csv(a.inp, dtype=str))
    konserler.to_csv(a.outdir / "konserler.csv", index=False)
    ilanlar.to_csv(a.outdir / "ilanlar.csv", index=False)
    print(f"{len(ilanlar)} ilan, {len(konserler)} konser "
          f"({(konserler['kaynak_sayisi'] > 1).sum()} tanesi birden fazla sitede)")


if __name__ == "__main__":
    main()
