from . import biletix, bubilet, passo

SCRAPERS = {
    "bubilet": bubilet.scrape,
    "biletix": biletix.scrape,
    "passo": passo.scrape,
}
