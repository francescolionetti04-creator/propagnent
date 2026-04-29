"""
HouseRadar — Tecnocasa.it scraper
==================================
Selettori verificati dal vivo (gennaio 2026):
- URL provincia (no paginazione, ~45 annunci unica pagina):
    https://www.tecnocasa.it/annunci/immobili/toscana/livorno.html
    https://www.tecnocasa.it/annunci/immobili/toscana/pisa.html
- Card:  .estate-card
- Prezzo: .estate-card-price | .estate-card-current-price  ("€ 120.000")
- Box dati: .estate-card-box-data
    "€ 120.000 Trilocale in vendita Livorno, Via Dell' Oriolino - Garibaldi 3 locali 60 Mq 1 bagno"
- Regex sul testo:
    €\s*([\d\.]+)                                        prezzo
    (Trilocale|Bilocale|Quadrilocale|Appartamento|...)   tipo
    (\d+)\s*locali                                       camere
    (\d+)\s*Mq                                            mq  (M maiuscolo!)
    (\d+)\s*bagn                                          bagni
"""

import os
import sys
import re
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _scraper_common import (
    HEADERS_CHROME, log, random_pause,
    salva_annunci_db,
)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "backend", "propagnent.db")
PORTALE = "tecnocasa.it"
PREFIX  = "Tecnocasa"

# Pagina provincia unica: tutti gli annunci della provincia in un solo HTML
URLS = [
    ("https://www.tecnocasa.it/annunci/immobili/toscana/livorno.html", "Livorno"),
    ("https://www.tecnocasa.it/annunci/immobili/toscana/pisa.html",    "Pisa"),
]


def fetch_html(url: str) -> str:
    from curl_cffi import requests as cffi
    r = cffi.get(url, headers=HEADERS_CHROME, impersonate="chrome120", timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.text


# ─── Parser ──────────────────────────────────────────────────────────────────

_RE_PREZZO  = re.compile(r"€\s*([\d\.]+)")
_RE_LOCALI  = re.compile(r"(\d+)\s*locali", re.IGNORECASE)
_RE_MQ      = re.compile(r"(\d+)\s*Mq")        # M maiuscolo (formato Tecnocasa)
_RE_BAGNI   = re.compile(r"(\d+)\s*bagn", re.IGNORECASE)
_RE_TIPO    = re.compile(
    r"\b(Monolocale|Bilocale|Trilocale|Quadrilocale|Quintilocale|"
    r"Appartamento|Villa|Villetta|Attico|Loft|Rustico|Casale|Casa)\s+in\s+vendita\s+([^,\n]+,[^\d\n]{1,80})",
    re.IGNORECASE,
)


def _parse_prezzo(testo: str):
    m = _RE_PREZZO.search(testo or "")
    if not m:
        return None
    try:
        return int(m.group(1).replace(".", ""))
    except Exception:
        return None


def parse_pagina(html: str, provincia_hint: str) -> list:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html, "html.parser")
    annunci = []

    for card in soup.select(".estate-card"):
        # Link annuncio: primo <a> con href
        link = card.find("a", href=True)
        if not link:
            continue
        href = link["href"].strip()
        if href.startswith("/"):
            href = "https://www.tecnocasa.it" + href
        elif not href.startswith("http"):
            continue

        # Box dati strutturato
        box = card.select_one(".estate-card-box-data")
        box_text = box.get_text(" ", strip=True) if box else card.get_text(" ", strip=True)

        # Prezzo: priorità ai selettori dedicati
        prezzo_el = (card.select_one(".estate-card-current-price")
                     or card.select_one(".estate-card-price"))
        prezzo = _parse_prezzo(prezzo_el.get_text() if prezzo_el else box_text)

        # Tipo + via dal pattern "Tipo in vendita Città, Via ..."
        tipo = None
        indirizzo_titolo = None
        m_t = _RE_TIPO.search(box_text)
        if m_t:
            tipo = m_t.group(1).strip().capitalize()
            indirizzo_titolo = m_t.group(2).strip()

        m_loc = _RE_LOCALI.search(box_text)
        camere = int(m_loc.group(1)) if m_loc else None
        m_mq = _RE_MQ.search(box_text)
        mq = int(m_mq.group(1)) if m_mq else None

        # Titolo: "<Tipo> in vendita - <indirizzo>" o fallback box_text
        if tipo and indirizzo_titolo:
            titolo = f"{tipo} in vendita — {indirizzo_titolo}"
        else:
            titolo = box_text[:160]

        img = card.select_one("img")
        foto = (img.get("src") or img.get("data-src")) if img else None

        annunci.append({
            "url": href,
            "titolo": titolo,
            "prezzo": prezzo,
            "mq": mq,
            "camere": camere,
            "tipo": tipo,
            "inserzionista": "Tecnocasa",   # franchising → sempre agenzia
            "foto_url": foto,
            "provincia_hint": provincia_hint,
        })

    # Dedup per URL
    seen = set()
    deduped = []
    for a in annunci:
        if a["url"] in seen:
            continue
        seen.add(a["url"])
        deduped.append(a)
    return deduped


def scrapa_tecnocasa() -> int:
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
    scrapa_tecnocasa()
