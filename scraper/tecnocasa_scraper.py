"""
HouseRadar — Tecnocasa.it scraper
==================================
Selettori verificati dal vivo (gennaio 2026):
- URL provincia (no paginazione, ~45 annunci unica pagina):
    https://www.tecnocasa.it/annunci/immobili/toscana/{provincia}.html
- Card:  .estate-card  (e parenti: anchor strategy via .estate-card-box-data)
- Box dati: .estate-card-box-data
    "€ 120.000 Trilocale in vendita Livorno, Via Dell' Oriolino 3 locali 60 Mq 1 bagno"
- Regex sul testo:
    €\s*([\d\.]+)                                        prezzo
    (Trilocale|Bilocale|Quadrilocale|Appartamento|...)   tipo
    (\d+)\s*locali                                       camere
    (\d+)\s*Mq                                            mq  (M maiuscolo!)
    (\d+)\s*bagn                                          bagni

NOTA: il parser è ROBUSTO contro variazioni di markup.
Strategia: trova tutti gli .estate-card-box-data (testo strutturato univoco
per ogni card) e risale al contenitore card via find_parent.
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
PORTALE = "tecnocasa.it"
PREFIX  = "Tecnocasa"

# Una pagina per provincia (Tecnocasa non ha ?page=)
URLS = [
    (f"https://www.tecnocasa.it/annunci/immobili/toscana/{prov}.html",
     prov.capitalize().replace("-", "-"))
    for prov in PROVINCE_TOSCANA
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
_RE_MQ      = re.compile(r"(\d+)\s*Mq")
_RE_BAGNI   = re.compile(r"(\d+)\s*bagn", re.IGNORECASE)
_RE_TIPO    = re.compile(
    r"\b(Monolocale|Bilocale|Trilocale|Quadrilocale|Quintilocale|Pentalocale|"
    r"Appartamento|Villa|Villetta|Bifamiliare|Attico|Loft|Rustico|Casale|"
    r"Casa\s+indipendente|Casa)\s+in\s+vendita\s+([^\n]{1,140})",
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
        log("BeautifulSoup mancante", prefix=PREFIX)
        return []

    # Forziamo html.parser (no lxml/html5lib) per evitare differenze di parsing
    soup = BeautifulSoup(html, "html.parser")

    # Debug: ci sono effettivamente .estate-card nel markup?
    n_card_raw = len(soup.select(".estate-card"))
    n_box_raw  = len(soup.select(".estate-card-box-data"))
    log(f"DEBUG html_len={len(html)} estate-card={n_card_raw} "
        f"box-data={n_box_raw}", prefix=PREFIX)

    annunci = []
    seen_urls = set()

    # Strategia 1: trova ogni .estate-card-box-data e risali al parent card.
    # Il testo del box è univoco per ogni annuncio.
    boxes = soup.select(".estate-card-box-data")
    for box in boxes:
        # Risali al primo parent che contiene "estate-card" tra le sue classi
        card = box.find_parent(
            lambda tag: tag.name in ("div", "article", "li", "section")
                        and tag.get("class")
                        and any("estate-card" in c for c in tag.get("class", []))
        )
        if card is None:
            card = box.parent  # fallback: usa il parent immediato

        rec = _parse_card(card, box, provincia_hint)
        if rec and rec["url"] not in seen_urls:
            seen_urls.add(rec["url"])
            annunci.append(rec)

    # Strategia 2 di fallback: se nessun box-data trovato (rare site change),
    # prova le card "classiche".
    if not annunci:
        for card in soup.select(".estate-card, [class*='estate-card']"):
            box = card.select_one(".estate-card-box-data") or card
            rec = _parse_card(card, box, provincia_hint)
            if rec and rec["url"] not in seen_urls:
                seen_urls.add(rec["url"])
                annunci.append(rec)

    log(f"  Card parsate: {len(annunci)}", prefix=PREFIX)
    return annunci


def _parse_card(card, box, provincia_hint: str):
    """Estrae i dati da una singola card. card e box possono essere lo stesso elemento."""
    if card is None:
        return None
    box_text = box.get_text(" ", strip=True) if box is not None else card.get_text(" ", strip=True)

    # ── URL: primo <a href> non vuoto ────────────────────────────
    href = None
    for a in card.find_all("a", href=True):
        h = a["href"].strip()
        if not h or h.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        href = h
        break
    if not href:
        # Genera URL deterministico se non c'è link diretto
        # (usa l'hash del box_text per stabile dedup)
        href = f"https://www.tecnocasa.it/__nolink__/{abs(hash(box_text))}"
    if href.startswith("/"):
        href = "https://www.tecnocasa.it" + href

    # ── Prezzo ───────────────────────────────────────────────────
    prezzo_el = (card.select_one(".estate-card-current-price")
                 or card.select_one(".estate-card-price"))
    prezzo = _parse_prezzo(prezzo_el.get_text() if prezzo_el else box_text)

    # ── Tipo + indirizzo ─────────────────────────────────────────
    tipo = None
    indirizzo_titolo = None
    m_t = _RE_TIPO.search(box_text)
    if m_t:
        tipo = m_t.group(1).strip().capitalize()
        # Pulisce: "Livorno, Via Dell' Oriolino 3 locali 60 Mq 1 bagno"
        # → "Livorno, Via Dell' Oriolino"  (stop alla prima occorrenza " N locali|Mq|bagn")
        rest = m_t.group(2).strip()
        cut = re.search(r"\s+\d+\s*(locali|Mq|bagn)", rest)
        if cut:
            rest = rest[:cut.start()].strip()
        indirizzo_titolo = rest

    # ── Locali / Mq / Bagni ──────────────────────────────────────
    m_loc = _RE_LOCALI.search(box_text)
    camere = int(m_loc.group(1)) if m_loc else None
    m_mq = _RE_MQ.search(box_text)
    mq = int(m_mq.group(1)) if m_mq else None

    # ── Titolo ───────────────────────────────────────────────────
    if tipo and indirizzo_titolo:
        titolo = f"{tipo} in vendita — {indirizzo_titolo}"
    else:
        titolo = box_text[:160]

    # ── Foto ─────────────────────────────────────────────────────
    img = card.select_one("img")
    foto = (img.get("src") or img.get("data-src")) if img else None

    return {
        "url": href,
        "titolo": titolo,
        "prezzo": prezzo,
        "mq": mq,
        "camere": camere,
        "tipo": tipo,
        "inserzionista": "Tecnocasa",
        "foto_url": foto,
        "provincia_hint": provincia_hint,
    }


def scrapa_tecnocasa() -> int:
    log(f"Avvio scraping {PORTALE} — {datetime.now().strftime('%d/%m/%Y %H:%M')}", prefix=PREFIX)
    log(f"Province: {len(URLS)} (tutta la Toscana)", prefix=PREFIX)
    tutti = []
    for i, (url, provincia) in enumerate(URLS):
        log(f"[{i+1}/{len(URLS)}] {url}", prefix=PREFIX)
        try:
            html = fetch_html(url)
            ann = parse_pagina(html, provincia)
            log(f"  Trovati: {len(ann)} annunci ({provincia})", prefix=PREFIX)
            tutti.extend(ann)
        except Exception as e:
            log(f"  Errore: {e} — continuo", prefix=PREFIX)
        if i < len(URLS) - 1:
            pause_inter_provincia()
    log(f"Totale raccolti: {len(tutti)}", prefix=PREFIX)
    nuovi = salva_annunci_db(tutti, DB_PATH, PORTALE)
    log(f"Nuovi inseriti: {nuovi}", prefix=PREFIX)
    return nuovi


if __name__ == "__main__":
    scrapa_tecnocasa()
