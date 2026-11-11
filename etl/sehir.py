"""Şehir alanı boş gelen ilanlarda şehri mekan ve başlık metninden çıkarır.

Sıra (ilk bulunan kullanılır):
1. Kaynağın verdiği şehir (yalnızca yazımı düzeltilir: "ISTANBUL" -> "İstanbul").
2. Mekan metninde geçen il adı: "FiBa Salon IKSV - Istanbul", "Holly Stone Bursa".
3. Bilinen mekan sözlüğü: "Zorlu PSM" -> İstanbul.
4. Başlıkta geçen il adı, önce "|" / "-" sonrasındaki kısım: "Birsen Tezer | Mersin".

Eşleştirme Türkçe karakterleri katlanmış metin üzerinde ve tam kelime olarak yapılır,
böylece "Istanbul", "İSTANBUL" ve "istanbul" aynı sayılır.
"""
from __future__ import annotations

import re
import unicodedata


def fold(s: str) -> str:
    s = (s or "").replace("I", "ı").replace("İ", "i").lower().replace("ı", "i")
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


# 81 il. Başka anlamı da olan ve başlıkta/mekanda yanlış eşleşme üreten adlar
# (Van -> "Van Morrison", Batman, Ordu, Muş) bilerek dışarıda; gerekirse
# VENUE_CITY ya da CITY_ALIASES ile tek tek eklenebilir.
PROVINCES = [
    "Adana", "Adıyaman", "Afyonkarahisar", "Ağrı", "Aksaray", "Amasya", "Ankara", "Antalya",
    "Ardahan", "Artvin", "Aydın", "Balıkesir", "Bartın", "Bayburt", "Bilecik", "Bingöl",
    "Bitlis", "Bolu", "Burdur", "Bursa", "Çanakkale", "Çankırı", "Çorum", "Denizli",
    "Diyarbakır", "Düzce", "Edirne", "Elazığ", "Erzincan", "Erzurum", "Eskişehir", "Gaziantep",
    "Giresun", "Gümüşhane", "Hakkari", "Hatay", "Iğdır", "Isparta", "İstanbul", "İzmir",
    "Kahramanmaraş", "Karabük", "Karaman", "Kars", "Kastamonu", "Kayseri", "Kilis", "Kırıkkale",
    "Kırklareli", "Kırşehir", "Kocaeli", "Konya", "Kütahya", "Malatya", "Manisa", "Mardin",
    "Mersin", "Muğla", "Nevşehir", "Niğde", "Osmaniye", "Rize", "Sakarya", "Samsun",
    "Şanlıurfa", "Siirt", "Sinop", "Şırnak", "Sivas", "Tekirdağ", "Tokat", "Trabzon",
    "Tunceli", "Uşak", "Yalova", "Yozgat", "Zonguldak",
]

# İl adı geçmeyen ama ili belli olan yaygın yazımlar ve ilçeler.
CITY_ALIASES = {
    "izmit": "Kocaeli", "gebze": "Kocaeli", "adapazari": "Sakarya", "antakya": "Hatay",
    "urfa": "Şanlıurfa", "maras": "Kahramanmaraş", "afyon": "Afyonkarahisar", "icel": "Mersin",
    "bodrum": "Muğla", "fethiye": "Muğla", "marmaris": "Muğla", "cesme": "İzmir",
    "alanya": "Antalya", "kusadasi": "Aydın", "kadikoy": "İstanbul", "besiktas": "İstanbul",
    "harbiye": "İstanbul", "maslak": "İstanbul", "kartal": "İstanbul", "atasehir": "İstanbul",
}

# Bilinen mekanlar -> il. Anahtarlar katlanmış metinde alt dizi olarak aranır.
# Birden çok şehirde şubesi olan mekanlar (Holly Stone, IF Performance, Jolly Joker...)
# burada yok; onların şehri ancak metinde yazıyorsa bulunur.
VENUE_CITY = {
    "babylon": "İstanbul",
    "zorlu psm": "İstanbul",
    "zorlu performans": "İstanbul",
    "volkswagen arena": "İstanbul",
    "sanat performance": "İstanbul",
    "kucukciftlik": "İstanbul",
    "cemil topuzlu": "İstanbul",
    "bostanci gosteri": "İstanbul",
    "jolly joker kartal": "İstanbul",
    "ulker sports": "İstanbul",
    "sinan erdem": "İstanbul",
    "jj arena": "İstanbul",
    "cemal resit rey": "İstanbul",
    "crr konser": "İstanbul",
    "fiba salon": "İstanbul",
    "maximum uniq": "İstanbul",
    "uniq hall": "İstanbul",
    "lifepark": "İstanbul",
    "dorock xl": "İstanbul",
    "salon iksv": "İstanbul",
    "akm turk telekom": "İstanbul",
    "ataturk kultur merkezi": "İstanbul",
    "congresium": "Ankara",
    "ankara arena": "Ankara",
    "cso ada": "Ankara",
    "meb sura": "Ankara",
    "ahmed adnan saygun": "İzmir",
    "kulturpark": "İzmir",
    "izmir arena": "İzmir",
}

_CANON = {fold(p): p for p in PROVINCES}
_CANON.update(CITY_ALIASES)
_WORD_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _CANON), key=len, reverse=True)) + r")\b")
_TITLE_SPLIT_RE = re.compile(r"\s[|–—-]\s|\|")


def city_in_text(text: str) -> str:
    """Metinde geçen ilk il adını standart yazımıyla döndürür, yoksa ""."""
    m = _WORD_RE.search(fold(text))
    return _CANON[m.group(1)] if m else ""


def city_from_venue(venue: str) -> str:
    v = fold(venue)
    return next((city for key, city in VENUE_CITY.items() if key in v), "")


def city_from_title(title: str) -> str:
    # "Gece Yolcuları | Ankara": ayraçtan sonraki parçalar önce, sonra başlığın tamamı.
    parts = _TITLE_SPLIT_RE.split(title or "")
    for part in reversed(parts[1:]):
        city = city_in_text(part)
        if city:
            return city
    return city_in_text(title)


def infer_city(sehir: str, mekan: str, baslik: str) -> tuple[str, str]:
    """(şehir, nereden_bulundu) döndürür. nereden: kaynak | mekan | mekan_sozluk | baslik | ""."""
    if sehir and sehir.strip():
        return city_in_text(sehir) or sehir.strip(), "kaynak"
    for fn, label in ((city_in_text, "mekan"), (city_from_venue, "mekan_sozluk")):
        city = fn(mekan)
        if city:
            return city, label
    city = city_from_title(baslik)
    return (city, "baslik") if city else ("", "")
