"""
HouseRadar — Helper comune per nuovi scraper portali
=====================================================
Funzioni condivise da casa_scraper, wikicasa_scraper, tecnocasa_scraper,
immobiliare_scraper_v2.

Espone:
  - HEADERS_CHROME       → User-Agent realistico Chrome120
  - random_pause(a, b)   → sleep randomico
  - log(msg, prefix)     → print con timestamp
  - estrai_prezzo(t)     → int €
  - estrai_mq(t)         → int m²
  - estrai_camere(t)     → int
  - is_agenzia(nome)     → bool
  - determina_zona(testo, hint)  → "Livorno Città" / "Pisa Città" / ...
  - determina_tipo(testo)        → "Appartamento"|"Villa"|"Bilocale"|...
  - genera_intel(...)            → dict {intel_privato, intel_warning, ai_insight}
  - salva_annunci_db(annunci, db_path, portale) → int (nuovi inseriti)
"""

import os
import re
import json
import time
import random
import sqlite3
from datetime import datetime


HEADERS_CHROME = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/121.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

PAROLE_AGENZIA = [
    "agenzia", "immobiliare", "srl", "s.r.l", "snc", "sas", "spa",
    "studio", "group", "real estate", "property", "invest",
    "gestioni", "consulenza", "tecnocasa", "gabetti", "remax", "re/max",
    "coldwell", "century", "engel", "volkers", "mediocasa",
    "frimm", "professionisti", "associati", "costruzioni", "sviluppo",
    "casa.it", "tempocasa",
]

ZONE_KEYWORDS = {
    "Livorno Città":      ["livorno"],
    "Costa Livornese":    ["cecina", "rosignano", "castiglioncello", "vada", "san vincenzo", "bibbona"],
    "Val di Cornia":      ["piombino", "campiglia", "suvereto", "sassetta"],
    "Isola d'Elba":       ["elba", "portoferraio", "capoliveri", "rio marina", "marciana", "porto azzurro"],
    "Hinterland Livorno": ["collesalvetti", "fauglia"],
    "Pisa Città":         ["pisa", "san giuliano"],
    "Valdera":            ["pontedera", "calcinaia", "ponsacco", "lari", "casciana", "peccioli", "lajatico"],
    "Valdicecina":        ["volterra", "montecatini val di cecina", "pomarance"],
    "Litorale Pisano":    ["marina di pisa", "tirrenia", "calambrone"],
    "Valdarno Pisano":    ["san miniato", "santa croce", "castelfranco di sotto", "montopoli", "fucecchio"],
}


def log(msg: str, prefix: str = "Scraper"):
    print(f"[{datetime.now().strftime('%H:%M:%S')}][{prefix}] {msg}")


def random_pause(min_s: float = 2.0, max_s: float = 6.0):
    delay = random.uniform(min_s, max_s)
    time.sleep(delay)


def estrai_prezzo(testo: str):
    if not testo:
        return None
    t = re.sub(r'[€\.\s]', '', testo)
    m = re.search(r'(\d{4,9})', t)
    return int(m.group(1)) if m else None


def estrai_mq(testo: str):
    if not testo:
        return None
    m = re.search(r'(\d{2,4})\s*m[q²2]\b', testo, re.IGNORECASE)
    return int(m.group(1)) if m else None


def estrai_camere(testo: str):
    if not testo:
        return None
    m = re.search(r'(\d+)\s*(local[ei]|camere?|vani?|stanz[ae])', testo, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r'\b(\d+)\s*\+\s*\d+', testo)  # es: "3+1"
    return int(m.group(1)) if m else None


def is_agenzia(nome: str) -> bool:
    if not nome:
        return False
    nome_l = nome.lower()
    return any(p in nome_l for p in PAROLE_AGENZIA)


def determina_zona(testo: str, hint: str = "") -> str:
    t = ((testo or "") + " " + (hint or "")).lower()
    for zona, keywords in ZONE_KEYWORDS.items():
        if any(k in t for k in keywords):
            return zona
    return hint or "Toscana"


def determina_tipo(testo: str) -> str:
    if not testo:
        return "Appartamento"
    t = testo.lower()
    if "villa" in t:
        return "Villa"
    if "rustic" in t or "casale" in t or "colonica" in t:
        return "Rustico"
    if "attico" in t:
        return "Attico"
    if "bilocale" in t or "bilocali" in t:
        return "Bilocale"
    if "trilocale" in t or "trilocali" in t:
        return "Trilocale"
    if "monolocale" in t:
        return "Monolocale"
    if "loft" in t:
        return "Loft"
    return "Appartamento"


def estrai_indirizzo(titolo: str):
    """Estrae un indirizzo plausibile dal titolo. Ritorna (indirizzo, preciso)."""
    if not titolo:
        return ("Indirizzo non disponibile", False)
    # Cerca pattern "via/viale/piazza/corso ..."
    m = re.search(
        r'\b(via|viale|piazza|corso|largo|strada|loc(?:alit[àa])?\.?)\s+[A-Z][^,;\n]{2,60}',
        titolo, re.IGNORECASE,
    )
    if m:
        return (m.group(0).strip(), True)
    return (titolo[:80].strip(), False)


def genera_intel(fonte: str, giorni: int, inserzionista: str = "", n_agenzie: int = 0) -> dict:
    """Genera testi descrittivi standardizzati per la card."""
    if fonte == "privato":
        return {
            "intel_privato": f"Annuncio di privato — {inserzionista or 'contatto diretto'}.",
            "intel_warning": "Privati su portali standard ricevono molte chiamate — agire rapidamente.",
            "ai_insight":    "Privato su portale principale. Contatto immediato consigliato.",
        }
    if fonte == "noescl":
        return {
            "intel_privato": None,
            "intel_warning": f"Presente con {n_agenzie} agenzie diverse. Probabile mandato non esclusivo.",
            "ai_insight":    "Senza esclusiva: spazio per subentrare con un mandato esclusivo.",
        }
    return {
        "intel_privato": None,
        "intel_warning": None,
        "ai_insight":    None,
    }


def salva_annunci_db(annunci: list, db_path: str, portale: str) -> int:
    """
    Salva annunci nel DB con dedup per (titolo) → rilevamento non-esclusiva.
    Ritorna numero di nuovi inseriti. Cancella inoltre gli annunci scaduti
    (presenti nel DB ma non più nella sessione corrente di scraping).
    """
    if not annunci:
        return 0
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    nuovi = 0
    ora = datetime.now().isoformat()

    # Raggruppa per titolo per individuare non-esclusiva
    per_titolo: dict = {}
    seen_urls: set = set()
    for a in annunci:
        url = a.get("url") or a.get("url_originale") or ""
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        ins = a.get("inserzionista", "") or ""
        if is_agenzia(ins):
            key = (a.get("titolo", "") or "")[:60].lower().strip()
            per_titolo.setdefault(key, []).append(a)

    for a in annunci:
        url = a.get("url") or a.get("url_originale")
        titolo = a.get("titolo")
        if not url or not titolo:
            continue

        cur.execute("SELECT id FROM annunci WHERE url_originale = ?", (url,))
        if cur.fetchone():
            continue

        ins = a.get("inserzionista", "") or ""
        fonte_raw = "agenzia" if is_agenzia(ins) else "privato"
        key = titolo[:60].lower().strip()
        agenzie_list = []
        if fonte_raw == "agenzia" and key in per_titolo and len(per_titolo[key]) > 1:
            fonte = "noescl"
            agenzie_list = list({x.get("inserzionista", "") for x in per_titolo[key] if x.get("inserzionista")})
        else:
            fonte = fonte_raw

        indirizzo, preciso = estrai_indirizzo(titolo)
        zona = determina_zona(titolo, a.get("provincia_hint", ""))
        tipo = a.get("tipo") or determina_tipo(titolo)
        intel = genera_intel(fonte, 0, ins, len(agenzie_list))

        cur.execute("""
            INSERT INTO annunci (
                indirizzo, indirizzo_preciso, zona, tipo, mq, camere,
                prezzo, giorni_online, fonte, agenzie, proprietario, telefono,
                intel_privato, intel_warning, ai_insight,
                is_nuovo, data_inserimento, url_originale, foto_url, portale
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            indirizzo, 1 if preciso else 0, zona, tipo,
            a.get("mq"), a.get("camere"), a.get("prezzo"),
            0, fonte,
            json.dumps(agenzie_list, ensure_ascii=False),
            ins if fonte == "privato" else None,
            None,
            intel["intel_privato"], intel["intel_warning"], intel["ai_insight"],
            1, ora, url, a.get("foto_url"), portale,
        ))
        nuovi += 1

    conn.commit()

    # Rimozione annunci scaduti (URL non più visti)
    if len(seen_urls) > 5:
        cur.execute("SELECT url_originale FROM annunci WHERE portale = ?", (portale,))
        urls_db = {row[0] for row in cur.fetchall()}
        scaduti = urls_db - seen_urls
        if scaduti:
            cur.executemany(
                "DELETE FROM annunci WHERE url_originale = ?",
                [(u,) for u in scaduti],
            )
            conn.commit()
            log(f"Rimossi {len(scaduti)} annunci scaduti da {portale}", prefix=portale)

    conn.close()
    return nuovi
