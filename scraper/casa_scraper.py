"""
HouseRadar — Casa.it scraper
=============================
Strategia: prova prima curl_cffi (Chrome120 TLS impersonation),
fallback Playwright se 403/Cloudflare.
URL: https://www.casa.it/vendita/case/livorno-provincia e /pisa-provincia

Schema dati uguale a idealista_scraper:
  url, titolo, prezzo, mq, camere, inserzionista, foto_url, provincia_hint
"""

import os
import sys
import re
import json
import sqlite3
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _scraper_common import (
    HEADERS_CHROME, log, random_pause,
    estrai_prezzo, estrai_mq, estrai_camere,
    salva_annunci_db,
)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "backend", "propagnent.db")
PORTALE = "casa.it"
PREFIX  = "Casa"

URLS = [
    ("https://www.casa.it/vendita/case/livorno-provincia?pag=1", "Livorno"),
    ("https://www.casa.it/vendita/case/livorno-provincia?pag=2", "Livorno"),
    ("https://www.casa.it/vendita/case/livorno-provincia?pag=3", "Livorno"),
    ("https://www.casa.it/vendita/case/pisa-provincia?pag=1", "Pisa"),
    ("https://www.casa.it/vendita/case/pisa-provincia?pag=2", "Pisa"),
    ("https://www.casa.it/vendita/case/pisa-provincia?pag=3", "Pisa"),
]


# ─── Fetch (curl_cffi → Playwright fallback) ────────────────────────────────

def fetch_curl_cffi(url: str) -> str:
    from curl_cffi import requests as cffi
    r = cffi.get(url, headers=HEADERS_CHROME, impersonate="chrome120", timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.text


def fetch_playwright(url: str) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("playwright non installato")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=HEADERS_CHROME["User-Agent"],
            locale="it-IT",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        html = page.content()
        browser.close()
        return html


def fetch_html(url: str) -> str:
    try:
        return fetch_curl_cffi(url)
    except Exception as e:
        log(f"curl_cffi fallito ({e}) — fallback Playwright", prefix=PREFIX)
        return fetch_playwright(url)


# ─── Parser ──────────────────────────────────────────────────────────────────

def parse_pagina(html: str, provincia_hint: str) -> list:
    """
    Casa.it pubblica un grosso blob JSON dentro window.__INITIAL_STATE__
    o tag data-listings; in caso di assenza fallback su BS4 generico.
    """
    annunci = []

    # 1) JSON inline
    m = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', html, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            for it in _walk_listings(data):
                annunci.append(_normalize_jsonld(it, provincia_hint))
        except Exception as e:
            log(f"JSON parse: {e}", prefix=PREFIX)

    # 2) JSON-LD <script type="application/ld+json">
    if not annunci:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup.find_all("script", type="application/ld+json"):
                try:
                    blob = json.loads(tag.string or "{}")
                    items = blob if isinstance(blob, list) else [blob]
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        if it.get("@type") in ("Apartment", "House", "Residence", "Product", "Offer"):
                            annunci.append(_normalize_jsonld(it, provincia_hint))
                except Exception:
                    continue
        except Exception:
            pass

    # 3) Fallback HTML cards
    if not annunci:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for card in soup.select('[data-listing-id], article.listing, div.srp-card, li.entry'):
                a_tag = card.find("a", href=True)
                titolo_el = card.find(["h2", "h3", "h4"])
                prezzo_el = card.find(string=re.compile(r"€"))
                if not a_tag or not titolo_el:
                    continue
                href = a_tag["href"]
                if href.startswith("/"):
                    href = "https://www.casa.it" + href
                txt = card.get_text(" ", strip=True)
                annunci.append({
                    "url": href,
                    "titolo": titolo_el.get_text(strip=True),
                    "prezzo": estrai_prezzo(prezzo_el or ""),
                    "mq": estrai_mq(txt),
                    "camere": estrai_camere(txt),
                    "inserzionista": "",
                    "foto_url": (card.find("img") or {}).get("src") if card.find("img") else None,
                    "provincia_hint": provincia_hint,
                })
        except Exception as e:
            log(f"BS4 fallback errore: {e}", prefix=PREFIX)

    return annunci


def _walk_listings(obj):
    """Cerca array di annunci in un dict potenzialmente nidificato."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("listings", "results", "items", "ads", "properties") and isinstance(v, list):
                for it in v:
                    if isinstance(it, dict):
                        yield it
            else:
                yield from _walk_listings(v)
    elif isinstance(obj, list):
        for it in obj:
            yield from _walk_listings(it)


def _normalize_jsonld(it: dict, hint: str) -> dict:
    titolo = it.get("name") or it.get("title") or it.get("titolo") or ""
    url = (it.get("url") or it.get("permalink") or it.get("link")
           or (it.get("offers") or {}).get("url") or "")
    if url and url.startswith("/"):
        url = "https://www.casa.it" + url
    prezzo = (it.get("price")
              or (it.get("offers") or {}).get("price")
              or it.get("priceValue"))
    try:
        prezzo = int(float(prezzo)) if prezzo else None
    except Exception:
        prezzo = estrai_prezzo(str(prezzo))
    mq = (it.get("floorSize") or {}).get("value") if isinstance(it.get("floorSize"), dict) else it.get("mq")
    try:
        mq = int(mq) if mq else None
    except Exception:
        mq = None
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


# ─── Entry point ──────────────────────────────────────────────────────────────

def scrapa_casa() -> int:
    log(f"Avvio scraping {PORTALE} — {datetime.now().strftime('%d/%m/%Y %H:%M')}", prefix=PREFIX)
    tutti = []
    for url, provincia in URLS:
        log(f"Pagina: {url}", prefix=PREFIX)
        try:
            html = fetch_html(url)
            annunci = parse_pagina(html, provincia)
            log(f"  Trovati: {len(annunci)} annunci", prefix=PREFIX)
            tutti.extend(annunci)
        except Exception as e:
            log(f"  Errore: {e}", prefix=PREFIX)
        random_pause(2, 6)
    log(f"Totale raccolti: {len(tutti)}", prefix=PREFIX)
    nuovi = salva_annunci_db(tutti, DB_PATH, PORTALE)
    log(f"Nuovi inseriti nel DB: {nuovi}", prefix=PREFIX)
    return nuovi


if __name__ == "__main__":
    scrapa_casa()
