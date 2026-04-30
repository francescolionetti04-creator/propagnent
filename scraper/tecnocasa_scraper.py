"""
HouseRadar — Tecnocasa.it scraper
==================================
URL provincia (no paginazione, ~45 annunci unica pagina):
    https://www.tecnocasa.it/annunci/immobili/toscana/{provincia}.html

Tutti i selettori sono best-effort: il parser prova MOLTE strategie
in cascata, stampa debug verboso, e segnala chiaramente quale strategia
ha trovato annunci. Questo serve per diagnosticare il bug "0 annunci"
quando l'HTML contiene 31+ occorrenze di "estate-card".
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


def _make_soup(html: str):
    """
    Prova lxml prima (più tollerante a HTML malformato), poi html.parser.
    Ritorna (soup, parser_usato).
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None, "no-bs4"

    try:
        import lxml  # noqa: F401
        return BeautifulSoup(html, "lxml"), "lxml"
    except Exception:
        return BeautifulSoup(html, "html.parser"), "html.parser"


def _print_debug(html: str, soup) -> None:
    """Diagnostica per capire perché il parser non trova card."""
    print(f"[DEBUG-TECNO] HTML len: {len(html)}")
    print(f"[DEBUG-TECNO] 'estate-card' nel raw HTML: {html.count('estate-card')}")
    print(f"[DEBUG-TECNO] 'estate-card-box-data' nel raw HTML: {html.count('estate-card-box-data')}")
    print(f"[DEBUG-TECNO] 'estate-card-current-price' nel raw HTML: {html.count('estate-card-current-price')}")
    if soup is None:
        print("[DEBUG-TECNO] BeautifulSoup non disponibile")
        return
    print(f"[DEBUG-TECNO] BS4 found .estate-card:                {len(soup.select('.estate-card'))}")
    print(f"[DEBUG-TECNO] BS4 found .estate-card-box-data:       {len(soup.select('.estate-card-box-data'))}")
    print(f"[DEBUG-TECNO] BS4 found [class*='estate-card']:       {len(soup.select('[class*=estate-card]'))}")
    print(f"[DEBUG-TECNO] BS4 find_all class~='estate-card':     "
          f"{len(soup.find_all(class_=lambda c: c and 'estate-card' in (c if isinstance(c, str) else ' '.join(c))))}")


def parse_pagina(html: str, provincia_hint: str) -> list:
    soup, parser_used = _make_soup(html)
    if soup is None:
        log("BeautifulSoup mancante", prefix=PREFIX)
        return []

    _print_debug(html, soup)
    print(f"[DEBUG-TECNO] Parser BS4 in uso: {parser_used}")

    annunci = []
    seen_urls = set()

    # ── Strategia 1: anchor inversa via .estate-card-box-data ────────────
    boxes = soup.select(".estate-card-box-data")
    if boxes:
        print(f"[DEBUG-TECNO] Strategia 1 (.estate-card-box-data): {len(boxes)} boxes")
        for box in boxes:
            card = box.find_parent(
                lambda tag: tag.name in ("div", "article", "li", "section")
                            and tag.get("class")
                            and any("estate-card" in c for c in tag.get("class", []))
            ) or box.parent
            rec = _parse_card(card, box, provincia_hint)
            if rec and rec["url"] not in seen_urls:
                seen_urls.add(rec["url"])
                annunci.append(rec)
        if annunci:
            print(f"[DEBUG-TECNO] ✓ Strategia 1 OK — {len(annunci)} card")
            return annunci

    # ── Strategia 2: .estate-card diretto ────────────────────────────────
    cards = soup.select(".estate-card")
    if cards:
        print(f"[DEBUG-TECNO] Strategia 2 (.estate-card): {len(cards)} card")
        for card in cards:
            box = card.select_one(".estate-card-box-data") or card
            rec = _parse_card(card, box, provincia_hint)
            if rec and rec["url"] not in seen_urls:
                seen_urls.add(rec["url"])
                annunci.append(rec)
        if annunci:
            print(f"[DEBUG-TECNO] ✓ Strategia 2 OK — {len(annunci)} card")
            return annunci

    # ── Strategia 3: attribute substring [class*="estate-card"] ──────────
    cards = soup.select('[class*="estate-card"]')
    if cards:
        print(f"[DEBUG-TECNO] Strategia 3 ([class*=estate-card]): {len(cards)} match")
        for card in cards:
            box = card.select_one(".estate-card-box-data") or card
            rec = _parse_card(card, box, provincia_hint)
            if rec and rec["url"] not in seen_urls and rec.get("titolo"):
                seen_urls.add(rec["url"])
                annunci.append(rec)
        if annunci:
            print(f"[DEBUG-TECNO] ✓ Strategia 3 OK — {len(annunci)} card")
            return annunci

    # ── Strategia 4: regex bruta sull'HTML grezzo ────────────────────────
    # Cerca blocchi che contengono "in vendita" e un prezzo, accomunati.
    print("[DEBUG-TECNO] Strategie BS4 fallite — fallback regex bruta")
    for m in re.finditer(
        r"€\s*[\d\.]+[^€]{10,400}?(?:locali|Mq|bagn)",
        html, re.IGNORECASE | re.DOTALL,
    ):
        text = re.sub(r"<[^>]+>", " ", m.group(0))
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 30:
            continue
        prezzo = _parse_prezzo(text)
        m_t = _RE_TIPO.search(text)
        tipo = m_t.group(1).strip().capitalize() if m_t else "Appartamento"
        indirizzo = m_t.group(2).strip()[:120] if m_t else text[:120]
        url_fake = f"https://www.tecnocasa.it/__nolink__/{abs(hash(text))}"
        if url_fake in seen_urls:
            continue
        seen_urls.add(url_fake)
        annunci.append({
            "url": url_fake,
            "titolo": f"{tipo} in vendita — {indirizzo}",
            "prezzo": prezzo,
            "mq": (int(_RE_MQ.search(text).group(1)) if _RE_MQ.search(text) else None),
            "camere": (int(_RE_LOCALI.search(text).group(1)) if _RE_LOCALI.search(text) else None),
            "tipo": tipo,
            "inserzionista": "Tecnocasa",
            "foto_url": None,
            "provincia_hint": provincia_hint,
        })
    print(f"[DEBUG-TECNO] Strategia 4 (regex bruta): {len(annunci)} match")
    return annunci


def _parse_card(card, box, provincia_hint: str):
    if card is None:
        return None
    box_text = box.get_text(" ", strip=True) if box is not None else card.get_text(" ", strip=True)

    # URL
    href = None
    for a in card.find_all("a", href=True):
        h = a["href"].strip()
        if not h or h.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        href = h
        break
    if not href:
        href = f"https://www.tecnocasa.it/__nolink__/{abs(hash(box_text))}"
    if href.startswith("/"):
        href = "https://www.tecnocasa.it" + href

    # Prezzo
    prezzo_el = (card.select_one(".estate-card-current-price")
                 or card.select_one(".estate-card-price"))
    prezzo = _parse_prezzo(prezzo_el.get_text() if prezzo_el else box_text)

    # Tipo + indirizzo
    tipo = None
    indirizzo_titolo = None
    m_t = _RE_TIPO.search(box_text)
    if m_t:
        tipo = m_t.group(1).strip().capitalize()
        rest = m_t.group(2).strip()
        cut = re.search(r"\s+\d+\s*(locali|Mq|bagn)", rest)
        if cut:
            rest = rest[:cut.start()].strip()
        indirizzo_titolo = rest

    m_loc = _RE_LOCALI.search(box_text)
    camere = int(m_loc.group(1)) if m_loc else None
    m_mq = _RE_MQ.search(box_text)
    mq = int(m_mq.group(1)) if m_mq else None

    if tipo and indirizzo_titolo:
        titolo = f"{tipo} in vendita — {indirizzo_titolo}"
    else:
        titolo = box_text[:160]

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
            log(f"  → {len(ann)} annunci ({provincia})", prefix=PREFIX)
            tutti.extend(ann)
        except Exception as e:
            log(f"  Errore: {e} — continuo", prefix=PREFIX)
        if i < len(URLS) - 1:
            pause_inter_provincia(15, 25)
    log(f"Totale raccolti: {len(tutti)}", prefix=PREFIX)
    nuovi = salva_annunci_db(tutti, DB_PATH, PORTALE)
    log(f"Nuovi inseriti: {nuovi}", prefix=PREFIX)
    return nuovi


if __name__ == "__main__":
    scrapa_tecnocasa()
