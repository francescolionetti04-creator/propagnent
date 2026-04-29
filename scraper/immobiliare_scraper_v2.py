# TODO: serve playwright-stealth o user-data-dir persistente per Cloudflare bypass
"""
HouseRadar — Immobiliare.it scraper v2 (Playwright)
====================================================
Versione alternativa allo scraper curl_cffi: usa Chromium headless via
Playwright per superare Cloudflare quando l'IP del runner viene bloccato.

Richiede:
    pip install playwright
    playwright install chromium

URL: https://www.immobiliare.it/vendita-case/livorno/  e /pisa/
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
PORTALE = "immobiliare.it"
PREFIX  = "Imm-v2"

URLS = [
    ("https://www.immobiliare.it/vendita-case/livorno/?pag=1", "Livorno"),
    ("https://www.immobiliare.it/vendita-case/livorno/?pag=2", "Livorno"),
    ("https://www.immobiliare.it/vendita-case/livorno/?pag=3", "Livorno"),
    ("https://www.immobiliare.it/vendita-case/pisa/?pag=1", "Pisa"),
    ("https://www.immobiliare.it/vendita-case/pisa/?pag=2", "Pisa"),
    ("https://www.immobiliare.it/vendita-case/pisa/?pag=3", "Pisa"),
]


# ─── Fetch via Playwright ────────────────────────────────────────────────────

def fetch_html_playwright(url: str) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("playwright non installato — pip install playwright && playwright install chromium")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        ctx = browser.new_context(
            user_agent=HEADERS_CHROME["User-Agent"],
            locale="it-IT",
            timezone_id="Europe/Rome",
            viewport={"width": 1280, "height": 900},
            extra_http_headers={"Accept-Language": "it-IT,it;q=0.9"},
        )
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        # Aspetta il caricamento di __NEXT_DATA__ o cards
        try:
            page.wait_for_selector('script#__NEXT_DATA__, [data-cy="listing-item"]', timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(2000)
        html = page.content()
        browser.close()
        return html


# ─── Parser ──────────────────────────────────────────────────────────────────

def parse_pagina(html: str, provincia_hint: str) -> list:
    annunci = []

    # __NEXT_DATA__ è il json ufficiale di immobiliare.it
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.S,
    )
    if m:
        try:
            data = json.loads(m.group(1))
            for it in _walk_listings(data):
                rec = _from_immobiliare(it, provincia_hint)
                if rec:
                    annunci.append(rec)
        except Exception as e:
            log(f"NEXT_DATA parse error: {e}", prefix=PREFIX)

    return annunci


def _walk_listings(obj):
    """Cerca array di realEstate dentro la struttura props.pageProps."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("results", "items", "list") and isinstance(v, list):
                for it in v:
                    if isinstance(it, dict):
                        yield it
            else:
                yield from _walk_listings(v)
    elif isinstance(obj, list):
        for it in obj:
            yield from _walk_listings(it)


def _from_immobiliare(it: dict, hint: str) -> dict | None:
    re_obj = it.get("realEstate") if isinstance(it.get("realEstate"), dict) else it
    if not isinstance(re_obj, dict):
        return None
    titolo = re_obj.get("title") or re_obj.get("name") or ""
    if not titolo:
        return None
    properties = re_obj.get("properties") or []
    prop = properties[0] if properties else {}

    url = re_obj.get("seoUrl") or re_obj.get("url") or it.get("seoUrl") or ""
    if url and url.startswith("/"):
        url = "https://www.immobiliare.it" + url

    prezzo = None
    pr = re_obj.get("price") or {}
    if isinstance(pr, dict):
        prezzo = pr.get("value") or pr.get("price")
    if isinstance(prezzo, (int, float)):
        prezzo = int(prezzo)
    else:
        prezzo = estrai_prezzo(str(prezzo or ""))

    mq = prop.get("surface")
    try:
        mq = int(re.sub(r'\D', '', str(mq))) if mq else None
    except Exception:
        mq = None

    cam = prop.get("rooms") or prop.get("bedRoomsNumber")
    try:
        cam = int(cam) if cam else None
    except Exception:
        cam = None

    inserz = ""
    if isinstance(re_obj.get("advertiser"), dict):
        adv = re_obj["advertiser"]
        if isinstance(adv.get("agency"), dict):
            inserz = adv["agency"].get("displayName") or adv["agency"].get("label") or ""
        else:
            inserz = adv.get("displayName") or ""

    foto = None
    multimedia = prop.get("multimedia") or {}
    if isinstance(multimedia, dict):
        photos = multimedia.get("photos") or []
        if photos and isinstance(photos[0], dict):
            foto = photos[0].get("urls", {}).get("large") or photos[0].get("url")

    return {
        "url": url,
        "titolo": titolo,
        "prezzo": prezzo,
        "mq": mq,
        "camere": cam,
        "inserzionista": inserz,
        "foto_url": foto,
        "provincia_hint": hint,
    }


# ─── Entry point ──────────────────────────────────────────────────────────────

def scrapa_immobiliare_v2() -> int:
    log(f"Avvio scraping {PORTALE} (Playwright) — {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        prefix=PREFIX)
    tutti = []
    for url, provincia in URLS:
        log(f"Pagina: {url}", prefix=PREFIX)
        try:
            html = fetch_html_playwright(url)
            ann = parse_pagina(html, provincia)
            log(f"  Trovati: {len(ann)} annunci", prefix=PREFIX)
            tutti.extend(ann)
        except Exception as e:
            log(f"  Errore: {e}", prefix=PREFIX)
        random_pause(3, 6)
    log(f"Totale raccolti: {len(tutti)}", prefix=PREFIX)
    nuovi = salva_annunci_db(tutti, DB_PATH, PORTALE)
    log(f"Nuovi inseriti: {nuovi}", prefix=PREFIX)
    return nuovi


if __name__ == "__main__":
    scrapa_immobiliare_v2()
