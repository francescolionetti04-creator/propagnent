"""
HouseRadar — Wikicasa.it scraper
=================================
Selettori verificati dal vivo (gennaio 2026):
- Card listing: .uikit-card.insertion
- Link annuncio: a[href*="/annuncio/"]   →  https://www.wikicasa.it/annuncio/{ID}
- Prezzo:  €\s*([\d\.]+)
- MQ:      (\d+)\s*m[²2]
- Locali:  (\d+)\s*locali
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
PORTALE = "wikicasa.it"
PREFIX  = "Wikicasa"

URLS = []
for citta in ("livorno", "pisa"):
    for page in (1, 2, 3):
        URLS.append((
            f"https://www.wikicasa.it/vendita-case/{citta}/?page={page}",
            citta.capitalize(),
        ))


def fetch_html(url: str) -> str:
    from curl_cffi import requests as cffi
    r = cffi.get(url, headers=HEADERS_CHROME, impersonate="chrome120", timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.text


# ─── Parser ──────────────────────────────────────────────────────────────────

_RE_PREZZO  = re.compile(r"€\s*([\d\.]+)")
_RE_MQ      = re.compile(r"(\d+)\s*m[²2]")
_RE_LOCALI  = re.compile(r"(\d+)\s*locali", re.IGNORECASE)
_RE_TITOLO  = re.compile(
    r"\b(Appartamento|Bilocale|Trilocale|Quadrilocale|Monolocale|Villa|Attico|Loft|Rustico|Casa)\b[^\n]{0,120}",
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


def _parse_mq(testo: str):
    m = _RE_MQ.search(testo or "")
    return int(m.group(1)) if m else None


def _parse_locali(testo: str):
    m = _RE_LOCALI.search(testo or "")
    return int(m.group(1)) if m else None


def parse_pagina(html: str, provincia_hint: str) -> list:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log("BeautifulSoup mancante", prefix=PREFIX)
        return []

    soup = BeautifulSoup(html, "html.parser")
    annunci = []

    for card in soup.select(".uikit-card.insertion"):
        link = card.select_one('a[href*="/annuncio/"]')
        if not link:
            continue
        href = link.get("href", "")
        if href.startswith("/"):
            href = "https://www.wikicasa.it" + href
        # Normalizza eliminando query string varia
        m_id = re.search(r"/annuncio/(\d+)", href)
        if m_id:
            href = f"https://www.wikicasa.it/annuncio/{m_id.group(1)}"

        text = card.get_text(" ", strip=True)

        # Titolo (h2/h3 se presente, altrimenti regex sul testo)
        titolo_el = card.select_one("h2, h3")
        if titolo_el and titolo_el.get_text(strip=True):
            titolo = titolo_el.get_text(strip=True)
        else:
            m_t = _RE_TITOLO.search(text)
            titolo = m_t.group(0).strip() if m_t else text[:120]

        prezzo = _parse_prezzo(text)
        mq     = _parse_mq(text)
        camere = _parse_locali(text)

        img = card.select_one("img")
        foto = img.get("src") or img.get("data-src") if img else None

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

    # Dedup per URL
    seen = set()
    deduped = []
    for a in annunci:
        if a["url"] in seen:
            continue
        seen.add(a["url"])
        deduped.append(a)
    return deduped


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
        random_pause(3, 7)
    log(f"Totale raccolti: {len(tutti)}", prefix=PREFIX)
    nuovi = salva_annunci_db(tutti, DB_PATH, PORTALE)
    log(f"Nuovi inseriti: {nuovi}", prefix=PREFIX)
    return nuovi


if __name__ == "__main__":
    scrapa_wikicasa()
