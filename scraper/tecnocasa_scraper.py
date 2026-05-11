"""
HouseRadar — Tecnocasa.it scraper
==================================
Tecnocasa è una SPA Vue.js: ogni annuncio è un componente
``<estate-card :estate="...JSON...">`` con tutti i dati strutturati
(detail_url, title, subtitle, price, surface, rooms_short, images, agency)
già presenti nell'HTML server-rendered.

Strategia:
  1. Regex sull'attributo Vue ``:estate="..."`` per estrarre il JSON
     di ogni card (HTML-decode + json.loads)
  2. Paginazione: ``.../pag-2``, ``.../pag-3``, ... fino a pagina vuota
  3. Fallback graceful: se l'HTML non contiene <estate-card>, logga e
     ritorna lista vuota senza crashare (es. Cloudflare, manutenzione)

URL pagina 1 (provincia):
    https://www.tecnocasa.it/annunci/immobili/toscana/{provincia}.html
URL pagina N:
    https://www.tecnocasa.it/annunci/immobili/toscana/{provincia}.html/pag-N
"""

import os
import sys
import re
import json
import html as html_lib
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
BASE_URL = "https://www.tecnocasa.it"
MAX_PAGES = 30  # safety cap, esce comunque a pagina vuota


def _province_url(provincia: str, page: int = 1) -> str:
    base = f"{BASE_URL}/annunci/immobili/toscana/{provincia}.html"
    return base if page <= 1 else f"{base}/pag-{page}"


def fetch_html(url: str) -> str:
    """Fetch con curl_cffi impersonate (anti anti-bot leggero)."""
    from curl_cffi import requests as cffi
    r = cffi.get(url, headers=HEADERS_CHROME, impersonate="chrome120", timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.text


# ─── Parser ──────────────────────────────────────────────────────────────────

# Cattura tutto il contenuto JSON dentro :estate="..." (gestisce escape \")
_RE_ESTATE_PROP = re.compile(r':estate="((?:[^"\\]|\\.)*)"', re.DOTALL)
_RE_INT_PRICE = re.compile(r"[\d\.]+")
_RE_INT_FIRST = re.compile(r"(\d+)")


def _parse_int_field(val):
    """Estrae il primo numero intero da una stringa tipo '€ 85.000', '50 Mq', '2 locali'."""
    if val is None:
        return None
    s = str(val).replace(".", "")
    m = _RE_INT_FIRST.search(s)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _tipo_da_titolo(titolo: str):
    """Es: 'Bilocale in vendita' → 'Bilocale'. 'X locali in vendita' → None (uso default)."""
    if not titolo:
        return None
    m = re.match(
        r"\s*(Monolocale|Bilocale|Trilocale|Quadrilocale|Quintilocale|Pentalocale|"
        r"Appartamento|Villa|Villetta|Bifamiliare|Attico|Loft|Rustico|Casale|"
        r"Casa\s+indipendente|Casa)\b",
        titolo, re.IGNORECASE,
    )
    return m.group(1).strip().capitalize() if m else None


def _foto_da_images(images):
    if not images or not isinstance(images, list):
        return None
    url_dict = (images[0] or {}).get("url") or {}
    return (url_dict.get("card")
            or url_dict.get("gallery_preview")
            or url_dict.get("detail")
            or None)


def parse_pagina(html_str: str, provincia_hint: str) -> list:
    """Estrae annunci dal markup Vue ``<estate-card :estate="...">``."""
    if not html_str or "<estate-card" not in html_str:
        return []

    annunci = []
    seen_ids = set()
    for raw in _RE_ESTATE_PROP.findall(html_str):
        try:
            obj = json.loads(html_lib.unescape(raw))
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue

        # Dedup per id (alcuni annunci appaiono 2x come "top featured")
        ann_id = obj.get("id")
        if ann_id is not None:
            if ann_id in seen_ids:
                continue
            seen_ids.add(ann_id)

        detail_url = (obj.get("detail_url") or "").strip()
        if not detail_url:
            continue
        if detail_url.startswith("/"):
            detail_url = BASE_URL + detail_url

        titolo_base = (obj.get("title") or "").strip()
        subtitle = (obj.get("subtitle") or "").strip()
        if titolo_base and subtitle:
            titolo = f"{titolo_base} — {subtitle}"
        else:
            titolo = titolo_base or subtitle or f"Annuncio Tecnocasa {ann_id}"

        annunci.append({
            "url":            detail_url,
            "titolo":         titolo[:240],
            "prezzo":         _parse_int_field(obj.get("price")),
            "mq":             _parse_int_field(obj.get("surface")),
            "camere":         _parse_int_field(obj.get("rooms_short") or obj.get("rooms")),
            "tipo":           _tipo_da_titolo(titolo_base),
            "inserzionista":  "Tecnocasa",
            "foto_url":       _foto_da_images(obj.get("images")),
            "provincia_hint": provincia_hint,
        })

    return annunci


def _ha_next_page(html_str: str, page_corrente: int) -> bool:
    """True se nell'HTML c'è un link a pag-(N+1) — usato per fermare la paginazione."""
    if not html_str:
        return False
    return f"/pag-{page_corrente + 1}" in html_str


def scrapa_provincia(provincia: str) -> list:
    """Scrape multipagina per una provincia. Ritorna list di dict annunci."""
    prov_label = provincia.capitalize().replace("-", "-")
    annunci_prov = []

    for page in range(1, MAX_PAGES + 1):
        url = _province_url(provincia, page)
        log(f"  Pagina {page}: {url}", prefix=PREFIX)
        try:
            html_str = fetch_html(url)
        except Exception as e:
            log(f"    Errore HTTP: {e} — stop paginazione provincia", prefix=PREFIX)
            break

        ann = parse_pagina(html_str, prov_label)
        log(f"    → {len(ann)} annunci", prefix=PREFIX)

        if not ann:
            # Pagina vuota o anti-bot: ferma paginazione, ma non crashare
            if "<estate-card" not in html_str:
                log("    HTML privo di <estate-card> (possibile anti-bot/manutenzione) — stop", prefix=PREFIX)
            else:
                log("    Pagina vuota — stop paginazione", prefix=PREFIX)
            break

        annunci_prov.extend(ann)

        if not _ha_next_page(html_str, page):
            log(f"    Ultima pagina raggiunta (no link a pag-{page+1})", prefix=PREFIX)
            break

        random_pause(3, 7)

    return annunci_prov


def scrapa_tecnocasa() -> int:
    log(f"Avvio scraping {PORTALE} — {datetime.now().strftime('%d/%m/%Y %H:%M')}", prefix=PREFIX)
    log(f"Province: {len(PROVINCE_TOSCANA)} (tutta la Toscana)", prefix=PREFIX)

    tutti = []
    for i, prov in enumerate(PROVINCE_TOSCANA):
        prov_label = prov.capitalize().replace("-", "-")
        log(f"\n[{i+1}/{len(PROVINCE_TOSCANA)}] Provincia: {prov_label}", prefix=PREFIX)
        try:
            ann_prov = scrapa_provincia(prov)
        except Exception as e:
            log(f"  Errore inatteso provincia {prov_label}: {e} — continuo", prefix=PREFIX)
            ann_prov = []
        log(f"  Totale {prov_label}: {len(ann_prov)} annunci", prefix=PREFIX)
        tutti.extend(ann_prov)

        if i < len(PROVINCE_TOSCANA) - 1:
            pause_inter_provincia(15, 25)

    log(f"\nTotale raccolti: {len(tutti)}", prefix=PREFIX)
    if not tutti:
        log("Nessun annuncio raccolto — possibile blocco anti-bot lato Tecnocasa", prefix=PREFIX)
        return 0
    nuovi = salva_annunci_db(tutti, DB_PATH, PORTALE)
    log(f"Nuovi inseriti: {nuovi}", prefix=PREFIX)
    return nuovi


if __name__ == "__main__":
    scrapa_tecnocasa()
