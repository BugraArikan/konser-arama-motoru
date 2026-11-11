"""Şehir alanı boş ya da anlamsız gelen ilanlarda şehri mekan ve başlık metninden çıkarır.

Sıra (ilk bulunan kullanılır):
1. Kaynağın verdiği şehir, ama yalnızca tanınan bir il ya da ilçeyse. "EMPTY", "null",
   "0", "Türkiye" gibi değerler şehir sayılmaz ve aramaya devam edilir.
2. Mekan metninde geçen il adı. Önce sondaki "- İstanbul" / "| Ankara" parçasına bakılır:
   "Zorlu PSM - touché by N Kolay - İstanbul", "Holly Stone Bursa".
3. Bilinen mekan sözlüğü (VENUE_CITY): "Zorlu PSM" -> İstanbul.
4. Mekan metninde geçen ilçe/semt (DISTRICT_TO_CITY): "Rossi Suadiye" -> İstanbul.
5. Başlıkta geçen il adı, önce ayraçtan sonraki parça: "Birsen Tezer | Mersin".
6. Kaynağın tanınmayan ama anlamlı görünen değeri (ör. "Lefkoşa"), olduğu gibi.

Eşleştirme, Türkçe karakterleri ve büyük/küçük harfi katlanmış, görünmez karakterleri
temizlenmiş metin üzerinde ve tam kelime olarak yapılır: "Istanbul", "İSTANBUL",
"An​kara" ve "Gece Yolcuları ｜ Ankara" da yakalanır.
"""
from __future__ import annotations

import re
import unicodedata

_INVISIBLE_RE = re.compile(r"[­​-‏⁠﻿]")


def fold(s: str) -> str:
    # NFKC: tam genişlikli "｜", NBSP vb. sade karşılıklarına döner.
    s = _INVISIBLE_RE.sub("", unicodedata.normalize("NFKC", s or ""))
    s = s.replace("I", "ı").replace("İ", "i").lower().replace("ı", "i")
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


# 81 il. Başka anlamı da olan ve yanlış eşleşme üreten adlar (Van -> "Van Morrison",
# Batman, Ordu, Muş) bilerek dışarıda; gerekirse VENUE_CITY ile tek tek eklenebilir.
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

# İl adının eski/kısa/İngilizce yazımları. Hem mekanda hem başlıkta il adı gibi aranır.
CITY_ALIASES = {
    "istanbul": "İstanbul", "izmit": "Kocaeli", "adapazari": "Sakarya", "antakya": "Hatay",
    "urfa": "Şanlıurfa", "maras": "Kahramanmaraş", "afyon": "Afyonkarahisar", "icel": "Mersin",
    "antep": "Gaziantep",
}

# Popüler ilçe ve semtler -> il. Sadece MEKAN metninde aranır (başlıkta "Moda", "Bebek"
# gibi kelimeler başka anlamda geçebilir). Birden çok ilde aynı adla bulunan semtler
# (Göztepe, Bahçelievler, Gaziosmanpaşa, Yenimahalle, Kemer, Fatih...) bilerek dışarıda.
DISTRICT_TO_CITY = {
    "İstanbul": [
        "Kumburgaz", "Suadiye", "Bahçeşehir", "Ataköy", "Nişantaşı", "Bebek", "Kadıköy",
        "Beşiktaş", "Bakırköy", "Maslak", "Harbiye", "Kartal", "Ataşehir", "Şişli", "Beyoğlu",
        "Taksim", "Karaköy", "Galata", "Cihangir", "Ortaköy", "Arnavutköy", "Kuruçeşme",
        "Sarıyer", "Etiler", "Levent", "Mecidiyeköy", "Üsküdar", "Moda", "Caddebostan",
        "Bostancı", "Maltepe", "Pendik", "Tuzla", "Beylikdüzü", "Esenyurt", "Büyükçekmece",
        "Küçükçekmece", "Silivri", "Florya", "Yeşilköy", "Zeytinburnu", "Eminönü", "Sultanahmet",
        "Kurtköy", "Çekmeköy", "Ümraniye", "Kozyatağı", "Erenköy", "Fenerbahçe", "Kalamış",
        "Avcılar", "Başakşehir", "Kağıthane", "Seyrantepe", "Zekeriyaköy", "Kilyos", "Şile",
        "Büyükada", "Kemerburgaz", "Göktürk", "Halkalı", "Eyüpsultan", "Haliç", "Balat",
        "Feriköy", "Bomonti", "Tarabya", "Yeniköy", "İstinye", "Emirgan", "Rumelihisarı",
        "Kandilli", "Çengelköy", "Beylerbeyi", "Kuzguncuk", "Dolmabahçe", "Vadistanbul",
    ],
    "Ankara": [
        "Çankaya", "Kızılay", "Tunalı", "Ümitköy", "Çayyolu", "Bilkent", "Keçiören",
        "Etimesgut", "Gölbaşı", "Kavaklıdere", "Sıhhiye", "Beysukent", "İncek", "Batıkent",
        "Eryaman",
    ],
    "İzmir": [
        "Alsancak", "Karşıyaka", "Bornova", "Buca", "Konak", "Çeşme", "Urla", "Alaçatı",
        "Seferihisar", "Gaziemir", "Balçova", "Narlıdere", "Güzelbahçe", "Bostanlı",
        "Mavişehir", "Kemeraltı", "Foça", "Dikili",
    ],
    "Bursa": ["Nilüfer", "Osmangazi", "Mudanya", "İnegöl", "Gemlik", "Uludağ", "Görükle"],
    "Antalya": ["Alanya", "Kalkan", "Manavgat", "Belek", "Konyaaltı", "Muratpaşa", "Kaleiçi", "Aspendos"],
    "Muğla": [
        "Bodrum", "Fethiye", "Marmaris", "Datça", "Göcek", "Ölüdeniz", "Dalaman", "Gümbet",
        "Yalıkavak", "Türkbükü", "Turgutreis", "Akyaka",
    ],
    "Aydın": ["Kuşadası", "Didim"],
    "Balıkesir": ["Ayvalık", "Cunda", "Edremit", "Akçay", "Bandırma"],
    "Kocaeli": ["Gebze", "Kartepe"],
    "Sakarya": ["Sapanca"],
    "Eskişehir": ["Odunpazarı", "Tepebaşı"],
    "Hatay": ["İskenderun"],
    "Mersin": ["Tarsus", "Silifke"],
    "Çanakkale": ["Bozcaada", "Gökçeada", "Assos"],
    "Nevşehir": ["Kapadokya", "Cappadocia", "Göreme", "Ürgüp", "Uçhisar"],
    "Trabzon": ["Uzungöl"],
    "Denizli": ["Pamukkale"],
}

# Bilinen mekanlar -> il. Anahtarlar katlanmış mekan metninde alt dizi olarak aranır.
# Birden çok şehirde şubesi olan mekanlar (Holly Stone, IF Performance, Jolly Joker,
# Hayal Kahvesi...) burada yok; onların şehri metindeki il/ilçe adından bulunur.
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
    "pera 77": "İstanbul",
    "pera palace": "İstanbul",
    "four seasons hotel bosphorus": "İstanbul",
    "four seasons bosphorus": "İstanbul",
    "hunger torun": "İstanbul",
    "torun center": "İstanbul",
    "milena pub": "Ankara",
    "congresium": "Ankara",
    "ankara arena": "Ankara",
    "cso ada": "Ankara",
    "meb sura": "Ankara",
    "ahmed adnan saygun": "İzmir",
    "kulturpark": "İzmir",
    "izmir arena": "İzmir",
}

# Şehir sayılmayacak kaynak değerleri.
JUNK_VALUES = {"", "empty", "null", "none", "nan", "na", "n/a", "-", "--", "0", "turkiye", "turkey",
               "diger", "other", "tum sehirler", "tumu", "undefined"}

_CITY = {fold(p): p for p in PROVINCES}
_CITY.update(CITY_ALIASES)
_DISTRICT = {fold(d): city for city, ds in DISTRICT_TO_CITY.items() for d in ds}
_VENUE = {fold(k): v for k, v in VENUE_CITY.items()}


def _word_re(keys) -> re.Pattern:
    return re.compile(r"\b(" + "|".join(sorted(map(re.escape, keys), key=len, reverse=True)) + r")\b")


_CITY_RE = _word_re(_CITY)
_DISTRICT_RE = _word_re(_DISTRICT)
# Ayraçlar: | ¦ │ / , : ve boşluklu tire türleri ("Zorlu PSM - ... - İstanbul").
_SPLIT_RE = re.compile(r"\s*[|¦│/,:]\s*|\s+[-–—]\s+|\s*[–—]\s*")


def _segments_last_first(text: str) -> list[str]:
    """Metni ayraçlardan böler; en sondaki parça ilk sırada, en sonda metnin tamamı."""
    folded = fold(text)
    parts = [p for p in _SPLIT_RE.split(folded) if p.strip()]
    return list(reversed(parts)) + [folded]


def _find(text: str, pattern: re.Pattern, table: dict) -> str:
    for seg in _segments_last_first(text):
        m = pattern.search(seg)
        if m:
            return table[m.group(1)]
    return ""


def city_in_text(text: str) -> str:
    """Metinde geçen il adını (sondaki parça öncelikli) standart yazımıyla döndürür."""
    return _find(text, _CITY_RE, _CITY)


def city_from_district(text: str) -> str:
    return _find(text, _DISTRICT_RE, _DISTRICT)


def city_from_venue(venue: str) -> str:
    v = fold(venue)
    return next((city for key, city in _VENUE.items() if key in v), "")


def city_from_title(title: str) -> str:
    return city_in_text(title)


def is_junk(value: str) -> bool:
    return fold(value).strip() in JUNK_VALUES


def infer_city(sehir: str, mekan: str, baslik: str) -> tuple[str, str]:
    """(şehir, nereden_bulundu) döndürür.

    nereden: kaynak | mekan | mekan_sozluk | ilce | baslik | kaynak_ham | "".
    """
    sehir = (sehir or "").strip()
    known = city_in_text(sehir) or city_from_district(sehir) if sehir else ""
    if known:
        return known, "kaynak"
    for fn, text, label in (
        (city_in_text, mekan, "mekan"),
        (city_from_venue, mekan, "mekan_sozluk"),
        (city_from_district, mekan, "ilce"),
        (city_from_title, baslik, "baslik"),
    ):
        city = fn(text)
        if city:
            return city, label
    if sehir and not is_junk(sehir):
        return sehir, "kaynak_ham"
    return "", ""
