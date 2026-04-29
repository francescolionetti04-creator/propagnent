"""
HouseRadar — Wikicasa.it scraper
=================================
Strategia: curl_cffi (Chrome120 TLS impersonation). Wikicasa raramente
applica protezioni avanzate.
URL: https://www.wikicasa.it/case-in-vendita/livorno-provincia (e pisa-provincia)
"""

import os
import sys
import re
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _scraper_common import (
    HEADERS_CHROME, log, random_pause,
    estrai_prezzo, estrai_mq, estrai_camere,
    salva_annunci_db,
)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "backend", "propagnent.db")
PORTALE = "wikicasa.it"
PREFIX  = "Wikicasa"

URLS = [
    ("https://www.wikicasa.it/case-in-vendita/livorno-provincia?page=1", "Livorno"),
    ("https://www.wikicasa.it/case-in-vendita/livorno-provincia?page=2", "Livorno"),
    ("https://www.wikicasa.it/case-in-vendita/livorno-provincia?page=3", "Livorno"),
    ("https://www.wikicasa.it/case-in-vendita/pisa-provincia?page=1", "Pisa"),
    ("https://www.wikicasa.it/case-in-vendita/pisa-provincia?page=2", "Pisa"),
    ("https://www.wikicasa.it/case-in-vendita/pisa-provincia?page=3", "Pisa"),
]


def fetch_html(url: str) -> str:
    from curl_cffi import requests as cffi
    r = cffi.get(url, headers=HEADERS_CHROME, impersonate="chrome120", timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.text


def parse_pagina(html: str, provincia_hint: str) -> list:
    annunci = []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log("BeautifulSoup mancante", prefix=PREFIX)
        return []

    soup = BeautifulSoup(html, "html.parser")

    # 1) JSON-LD ItemList di annunci
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            blob = json.loads(tag.string or "{}")
        except Exception:
            continue
        items = blob if isinstance(blob, list) else [blob]
        for it in items:
            if not isinstance(it, dict):
                continue
            if it.get("@type") == "ItemList":
                for el in it.get("itemListElement", []) or []:
                    obj = el.get("item") if isinstance(el, dict) else None
                    if isinstance(obj, dict):
                        annunci.append(_from_jsonld(obj, provincia_hint))
            elif it.get("@type") in ("Apartment", "House", "Product", "Residence"):
                annunci.append(_from_jsonld(it, provincia_hint))

    # 2) Fallback DOM
    if not annunci:
        for card in soup.select('article.listing-item, div.search-results-list-item, li.result-item'):
            a = card.find("a", href=True)
            if not a:
                continue
            href = a["href"]
            if href.startswith("/"):
                href = "https://www.wikicasa.it" + href
            titolo_el = card.find(["h2", "h3"])
            txt = card.get_text(" ", strip=True)
            img = card.find("img")
            annunci.append({
                "url": href,
                "titolo": titolo_el.get_text(strip=True) if titolo_el else (a.get("title") or "")[:120],
                "prezzo": estrai_prezzo(txt),
                "mq": estrai_mq(txt),
                "camere": estrai_camere(txt),
                "inserzionista": "",
                "foto_url": img.get("src") if img else None,
                "provincia_hint": provincia_hint,
            })

    return [a for a in annunci if a.get("url") and a.get("titolo")]


def _from_jsonld(it: dict, hint: str) -> dict:
    titolo = it.get("name") or it.get("title") or ""
    url = it.get("url") or ""
    if url.startswith("/"):
        url = "https://www.wikicasa.it" + url
    prezzo = (it.get("price")
              or (it.get("offers") or {}).get("price"))
    try:
        prezzo = int(float(prezzo)) if prezzo else None
    except Exception:
        prezzo = estrai_prezzo(str(prezzo or ""))
    mq = None
    if isinstance(it.get("floorSize"), dict):
        try:
            mq = int(it["floorSize"].get("value", 0)) or None
        except Exception:
            pass
    foto = it.get("image")
    if isinstance(foto, list):
        foto = foto[0] if foto else None
    if isinstance(foto, dict):
        foto = foto.get("url")
    inserz = ""
    if isinstance(it.get("seller"), dict):
        inserz = it["seller"].get("name", "")
    return {
        "url": url,
        "titolo": titolo,
        "prezzo": prezzo,
        "mq": mq,
        "camere": estrai_camere(titolo),
        "inserzionista": inserz,
        "foto_url": foto,
        "provincia_hint": hint,
    }


def scrapa_wikicasa() -> int:
    log(f"Avvio scraping {PORTALE} — {datetime.now().strftime('%d/%m/%Y %H:%M')}", prefix=PREFIX)
    tutti = []
    for url, provincia in URLS:
        log(f"Pagina: {url}", prefix=PREFIX)
        try:
            html = fetch_html(url)
            ann = parse_pagina(html, provincia)
            log(f"  Trovati: {len(ann)} annunci", prefix=PREFIX)
            tutti.extend(ann)
        except Exception as e:
            log(f"  Errore: {e}", prefix=PREFIX)
        random_pause(2, 6)
    log(f"Totale raccolti: {len(tutti)}", prefix=PREFIX)
    nuovi = salva_annunci_db(tutti, DB_PATH, PORTALE)
    log(f"Nuovi inseriti: {nuovi}", prefix=PREFIX)
    return nuovi


if __name__ == "__main__":
    scrapa_wikicasa()
