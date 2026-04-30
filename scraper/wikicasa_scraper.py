"""
HouseRadar — Wikicasa.it scraper
=================================
URL pattern: https://www.wikicasa.it/vendita-case/{provincia}/?page=N

ANTI-403 STRATEGY:
- Sessione curl_cffi persistente (riusa cookie)
- Warm-up: GET https://www.wikicasa.it/ prima della prima provincia
- Header Referer: https://www.wikicasa.it/ su ogni richiesta successiva
- Pause inter-provincia 10-15s

Selettori (gennaio 2026):
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
    HEADERS_CHROME, log, random_pause, pause_inter_provincia,
    PROVINCE_TOSCANA,
    salva_annunci_db,
)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "backend", "propagnent.db")
PORTALE = "wikicasa.it"
PREFIX  = "Wikicasa"
MAX_PAGES = 50  # esce prima se trova pagina vuota

BASE_URL = "https://www.wikicasa.it"


# ─── Session con warm-up ─────────────────────────────────────────────────────

_session = None


def _get_session():
    """Sessione curl_cffi con warm-up homepage (cookie + token CF)."""
    global _session
    if _session is not None:
        return _session
    from curl_cffi import requests as cffi
    s = cffi.Session(impersonate="chrome120")
    s.headers.update(HEADERS_CHROME)
    log("Warm-up homepage…", prefix=PREFIX)
    try:
        r = s.get(BASE_URL + "/", timeout=30)
        log(f"  Homepage HTTP {r.status_code}, cookie: {len(s.cookies)}", prefix=PREFIX)
    except Exception as e:
        log(f"  Warm-up error: {e}", prefix=PREFIX)
    _session = s
    return _session


def fetch_html(url: str, referer: str = BASE_URL + "/") -> str:
    s = _get_session()
    headers = {"Referer": referer}
    r = s.get(url, headers=headers, timeout=30)
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


def parse_pagina(html: str, provincia_hint: str) -> list:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html, "html.parser")
    annunci = []

    cards = soup.select(".uikit-card.insertion")
    log(f"  DEBUG html_len={len(html)} cards_uikit={len(cards)}", prefix=PREFIX)

    for card in cards:
        link = card.select_one('a[href*="/annuncio/"]')
        if not link:
            continue
        href = link.get("href", "")
        if href.startswith("/"):
            href = BASE_URL + href
        m_id = re.search(r"/annuncio/(\d+)", href)
        if m_id:
            href = f"{BASE_URL}/annuncio/{m_id.group(1)}"

        text = card.get_text(" ", strip=True)

        titolo_el = card.select_one("h2, h3")
        if titolo_el and titolo_el.get_text(strip=True):
            titolo = titolo_el.get_text(strip=True)
        else:
            m_t = _RE_TITOLO.search(text)
            titolo = m_t.group(0).strip() if m_t else text[:120]

        prezzo = _parse_prezzo(text)
        mq     = (int(_RE_MQ.search(text).group(1)) if _RE_MQ.search(text) else None)
        camere = (int(_RE_LOCALI.search(text).group(1)) if _RE_LOCALI.search(text) else None)

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


def scrapa_wikicasa() -> int:
    log(f"Avvio scraping {PORTALE} — {datetime.now().strftime('%d/%m/%Y %H:%M')}", prefix=PREFIX)
    log(f"Province: {len(PROVINCE_TOSCANA)}", prefix=PREFIX)

    _get_session()  # forza warm-up subito

    tutti = []
    for i, prov in enumerate(PROVINCE_TOSCANA):
        prov_label = prov.capitalize().replace("-", "-")
        log(f"\n[{i+1}/{len(PROVINCE_TOSCANA)}] Provincia: {prov_label}", prefix=PREFIX)
        prov_referer = f"{BASE_URL}/vendita-case/{prov}/"
        for page in range(1, MAX_PAGES + 1):
            url = f"{BASE_URL}/vendita-case/{prov}/?page={page}"
            log(f"  Pagina {page}: {url}", prefix=PREFIX)
            try:
                html = fetch_html(url, referer=prov_referer)
                ann = parse_pagina(html, prov_label)
                log(f"    → {len(ann)} annunci", prefix=PREFIX)
                if not ann:
                    log("    Pagina vuota — stop paginazione", prefix=PREFIX)
                    break
                tutti.extend(ann)
            except Exception as e:
                log(f"    Errore: {e} — passo alla prossima", prefix=PREFIX)
                break
            random_pause(3, 7)
        if i < len(PROVINCE_TOSCANA) - 1:
            pause_inter_provincia()

    log(f"\nTotale raccolti: {len(tutti)}", prefix=PREFIX)
    nuovi = salva_annunci_db(tutti, DB_PATH, PORTALE)
    log(f"Nuovi inseriti: {nuovi}", prefix=PREFIX)
    return nuovi


if __name__ == "__main__":
    scrapa_wikicasa()
