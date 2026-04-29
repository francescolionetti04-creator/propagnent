"""
HouseRadar — Casa.it scraper
=============================
Selettori verificati dal vivo (gennaio 2026):
- Card listing:   .csaSrpcard
- Link annuncio:  a[href*="/immobili/"]   →  /immobili/{ID}/
- Box dati:       .csaSrpcard__det__cont   ("€ 900.000 400 m² 6 locali 3 bagni")
- Prezzo:         .csaSrpcard__det__feats__text.first  (€\s*([\d\.]+))
- Regex sul testo:
    €\s*([\d\.]+)        prezzo
    (\d+)\s*m²            mq
    (\d+)\s*locali        camere
    (\d+)\s*bagni         bagni

Strategia: prima curl_cffi (Chrome120 TLS), fallback Playwright se 403.
Il JSON-LD @graph contiene name/url/locality ma NON i prezzi → DOM resta autoritativo.
"""

import os
import sys
import re
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _scraper_common import (
    HEADERS_CHROME, log, random_pause,
    salva_annunci_db,
)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "backend", "propagnent.db")
PORTALE = "casa.it"
PREFIX  = "Casa"

URLS = []
for prov in ("livorno-provincia", "pisa-provincia"):
    for page in (1, 2, 3):
        URLS.append((
            f"https://www.casa.it/vendita/residenziale/{prov}/?page={page}",
            "Livorno" if "livorno" in prov else "Pisa",
        ))


# ─── Fetch (curl_cffi → Playwright fallback) ────────────────────────────────

def _fetch_curl(url: str) -> str:
    from curl_cffi import requests as cffi
    r = cffi.get(url, headers=HEADERS_CHROME, impersonate="chrome120", timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.text


def _fetch_playwright(url: str) -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=HEADERS_CHROME["User-Agent"],
            locale="it-IT", viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        html = page.content()
        browser.close()
        return html


def fetch_html(url: str) -> str:
    try:
        return _fetch_curl(url)
    except Exception as e:
        log(f"curl_cffi fallito ({e}) — fallback Playwright", prefix=PREFIX)
        return _fetch_playwright(url)


# ─── Parser ──────────────────────────────────────────────────────────────────

_RE_PREZZO = re.compile(r"€\s*([\d\.]+)")
_RE_MQ     = re.compile(r"(\d+)\s*m²")
_RE_LOCALI = re.compile(r"(\d+)\s*locali", re.IGNORECASE)
_RE_BAGNI  = re.compile(r"(\d+)\s*bagn", re.IGNORECASE)


def _parse_prezzo(testo: str):
    m = _RE_PREZZO.search(testo or "")
    if not m:
        return None
    try:
        return int(m.group(1).replace(".", ""))
    except Exception:
        return None


def _build_jsonld_index(soup) -> dict:
    """
    Estrae da @graph i blocchi SingleFamilyResidence|Apartment|House e li
    indicizza per URL → {name, locality, numberOfRooms}.
    """
    idx = {}
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            blob = json.loads(tag.string or "{}")
        except Exception:
            continue
        graph = blob.get("@graph") if isinstance(blob, dict) else None
        items = graph or (blob if isinstance(blob, list) else [blob])
        for it in items:
            if not isinstance(it, dict):
                continue
            t = it.get("@type")
            if t in ("SingleFamilyResidence", "Apartment", "House", "Residence"):
                url = it.get("url") or ""
                if url:
                    idx[url.rstrip("/")] = {
                        "name":     it.get("name") or "",
                        "locality": (it.get("address") or {}).get("addressLocality") or "",
                        "rooms":    it.get("numberOfRooms"),
                    }
    return idx


def parse_pagina(html: str, provincia_hint: str) -> list:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html, "html.parser")
    jsonld = _build_jsonld_index(soup)
    annunci = []

    for card in soup.select(".csaSrpcard"):
        link = card.select_one('a[href*="/immobili/"]')
        if not link:
            continue
        href = link.get("href", "")
        if href.startswith("/"):
            href = "https://www.casa.it" + href
        # Normalizza per dedup
        m_id = re.search(r"/immobili/(\d+)", href)
        if m_id:
            href = f"https://www.casa.it/immobili/{m_id.group(1)}/"

        # Box dati raggruppato (preferito)
        det = card.select_one(".csaSrpcard__det__cont")
        det_text = det.get_text(" ", strip=True) if det else card.get_text(" ", strip=True)

        # Prezzo: preferisci il selettore dedicato
        prezzo_el = card.select_one(".csaSrpcard__det__feats__text.first")
        prezzo = _parse_prezzo(prezzo_el.get_text() if prezzo_el else det_text)

        m_mq = _RE_MQ.search(det_text)
        mq = int(m_mq.group(1)) if m_mq else None
        m_loc = _RE_LOCALI.search(det_text)
        camere = int(m_loc.group(1)) if m_loc else None

        # Titolo: preferisci JSON-LD (più pulito), altrimenti h2/h3 della card
        titolo = ""
        meta = jsonld.get(href.rstrip("/"))
        if meta and meta.get("name"):
            titolo = meta["name"]
            if meta.get("locality") and meta["locality"] not in titolo:
                titolo = f"{titolo} — {meta['locality']}"
        else:
            t_el = card.select_one("h2, h3, .csaSrpcard__det__title")
            titolo = (t_el.get_text(strip=True) if t_el else "")[:160]
        if not titolo:
            titolo = det_text[:120]

        img = card.select_one("img")
        foto = (img.get("src") or img.get("data-src")) if img else None

        annunci.append({
            "url": href,
            "titolo": titolo,
            "prezzo": prezzo,
            "mq": mq,
            "camere": camere,
            "inserzionista": "",
            "foto_url": foto,
            "provincia_hint": provincia_hint,
        })

    # Dedup
    seen = set()
    deduped = []
    for a in annunci:
        if a["url"] in seen:
            continue
        seen.add(a["url"])
        deduped.append(a)
    return deduped


def scrapa_casa() -> int:
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
        random_pause(3, 7)
    log(f"Totale raccolti: {len(tutti)}", prefix=PREFIX)
    nuovi = salva_annunci_db(tutti, DB_PATH, PORTALE)
    log(f"Nuovi inseriti: {nuovi}", prefix=PREFIX)
    return nuovi


if __name__ == "__main__":
    scrapa_casa()
