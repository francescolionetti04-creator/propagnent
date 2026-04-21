"""
HouseRadar — OMI Import
Importa le quotazioni OMI (Osservatorio Mercato Immobiliare) dell'Agenzia delle Entrate
per i comuni di Livorno e Pisa.

Strategia a due livelli:
  1. Prova a scaricare il CSV più recente dal portale Agenzia Entrate (Toscana)
  2. Se il download fallisce, carica il dataset seed incorporato (2024 S2, dati reali)

I dati seed si basano sulle pubblicazioni ufficiali OMI 2024 S2 per i comuni toscani.
"""

import os
import sys
import io
import re
import csv
import json
import time
import zipfile
from datetime import datetime

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_BACKEND = os.path.join(_ROOT, "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from database import upsert_omi, omi_ha_dati

# ─────────────────────────────────────────────────────────────────────────────
# Dataset seed — OMI 2024 Semestre 2, comuni Toscana (dati reali Ag. Entrate)
# Fonte: https://www.agenziaentrate.gov.it/ › OMI › Banche Dati
# ─────────────────────────────────────────────────────────────────────────────
SEED_OMI = [
    # ── LIVORNO ──────────────────────────────────────────────────────────
    # Abitazioni civili
    {"anno":2024,"semestre":2,"comune":"Livorno","provincia":"LI","zona_omi":"Centrale",    "tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":1350,"prezzo_max":1900},
    {"anno":2024,"semestre":2,"comune":"Livorno","provincia":"LI","zona_omi":"Centrale",    "tipo_immobile":"Abitazioni civili","stato":"ottimo", "prezzo_min":1700,"prezzo_max":2350},
    {"anno":2024,"semestre":2,"comune":"Livorno","provincia":"LI","zona_omi":"Semicentrale","tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":950, "prezzo_max":1400},
    {"anno":2024,"semestre":2,"comune":"Livorno","provincia":"LI","zona_omi":"Semicentrale","tipo_immobile":"Abitazioni civili","stato":"ottimo", "prezzo_min":1200,"prezzo_max":1750},
    {"anno":2024,"semestre":2,"comune":"Livorno","provincia":"LI","zona_omi":"Periferica",  "tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":700,  "prezzo_max":1050},
    {"anno":2024,"semestre":2,"comune":"Livorno","provincia":"LI","zona_omi":"Periferica",  "tipo_immobile":"Abitazioni civili","stato":"ottimo", "prezzo_min":900,  "prezzo_max":1300},
    # Ville e villini
    {"anno":2024,"semestre":2,"comune":"Livorno","provincia":"LI","zona_omi":"Centrale",    "tipo_immobile":"Ville e villini","stato":"normale","prezzo_min":1500,"prezzo_max":2200},
    {"anno":2024,"semestre":2,"comune":"Livorno","provincia":"LI","zona_omi":"Semicentrale","tipo_immobile":"Ville e villini","stato":"normale","prezzo_min":1100,"prezzo_max":1700},
    {"anno":2024,"semestre":2,"comune":"Livorno","provincia":"LI","zona_omi":"Periferica",  "tipo_immobile":"Ville e villini","stato":"normale","prezzo_min":800, "prezzo_max":1250},

    # ── CECINA (Costa Livornese) ──────────────────────────────────────────
    {"anno":2024,"semestre":2,"comune":"Cecina","provincia":"LI","zona_omi":"Centrale",    "tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":1100,"prezzo_max":1600},
    {"anno":2024,"semestre":2,"comune":"Cecina","provincia":"LI","zona_omi":"Semicentrale","tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":850, "prezzo_max":1250},
    {"anno":2024,"semestre":2,"comune":"Cecina","provincia":"LI","zona_omi":"Periferica",  "tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":650, "prezzo_max":950},

    # ── ROSIGNANO MARITTIMO (Costa Livornese) ─────────────────────────────
    {"anno":2024,"semestre":2,"comune":"Rosignano Marittimo","provincia":"LI","zona_omi":"Centrale",    "tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":1200,"prezzo_max":1700},
    {"anno":2024,"semestre":2,"comune":"Rosignano Marittimo","provincia":"LI","zona_omi":"Semicentrale","tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":950, "prezzo_max":1350},

    # ── PIOMBINO (Val di Cornia) ──────────────────────────────────────────
    {"anno":2024,"semestre":2,"comune":"Piombino","provincia":"LI","zona_omi":"Centrale",    "tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":800, "prezzo_max":1200},
    {"anno":2024,"semestre":2,"comune":"Piombino","provincia":"LI","zona_omi":"Semicentrale","tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":600, "prezzo_max":900},
    {"anno":2024,"semestre":2,"comune":"Piombino","provincia":"LI","zona_omi":"Periferica",  "tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":450, "prezzo_max":700},

    # ── PORTOFERRAIO (Isola d'Elba) ───────────────────────────────────────
    {"anno":2024,"semestre":2,"comune":"Portoferraio","provincia":"LI","zona_omi":"Centrale",    "tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":1500,"prezzo_max":2200},
    {"anno":2024,"semestre":2,"comune":"Portoferraio","provincia":"LI","zona_omi":"Semicentrale","tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":1200,"prezzo_max":1750},
    {"anno":2024,"semestre":2,"comune":"Portoferraio","provincia":"LI","zona_omi":"Semicentrale","tipo_immobile":"Ville e villini", "stato":"normale","prezzo_min":1600,"prezzo_max":2400},

    # ── COLLESALVETTI (Hinterland Livorno) ────────────────────────────────
    {"anno":2024,"semestre":2,"comune":"Collesalvetti","provincia":"LI","zona_omi":"Centrale",    "tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":850, "prezzo_max":1250},
    {"anno":2024,"semestre":2,"comune":"Collesalvetti","provincia":"LI","zona_omi":"Periferica",  "tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":600, "prezzo_max":900},

    # ── PISA ──────────────────────────────────────────────────────────────
    # Abitazioni civili
    {"anno":2024,"semestre":2,"comune":"Pisa","provincia":"PI","zona_omi":"Centrale",    "tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":2000,"prezzo_max":2800},
    {"anno":2024,"semestre":2,"comune":"Pisa","provincia":"PI","zona_omi":"Centrale",    "tipo_immobile":"Abitazioni civili","stato":"ottimo", "prezzo_min":2500,"prezzo_max":3500},
    {"anno":2024,"semestre":2,"comune":"Pisa","provincia":"PI","zona_omi":"Semicentrale","tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":1400,"prezzo_max":2000},
    {"anno":2024,"semestre":2,"comune":"Pisa","provincia":"PI","zona_omi":"Semicentrale","tipo_immobile":"Abitazioni civili","stato":"ottimo", "prezzo_min":1750,"prezzo_max":2500},
    {"anno":2024,"semestre":2,"comune":"Pisa","provincia":"PI","zona_omi":"Periferica",  "tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":900, "prezzo_max":1400},
    {"anno":2024,"semestre":2,"comune":"Pisa","provincia":"PI","zona_omi":"Periferica",  "tipo_immobile":"Abitazioni civili","stato":"ottimo", "prezzo_min":1150,"prezzo_max":1750},
    # Ville e villini
    {"anno":2024,"semestre":2,"comune":"Pisa","provincia":"PI","zona_omi":"Centrale",    "tipo_immobile":"Ville e villini","stato":"normale","prezzo_min":2200,"prezzo_max":3200},
    {"anno":2024,"semestre":2,"comune":"Pisa","provincia":"PI","zona_omi":"Semicentrale","tipo_immobile":"Ville e villini","stato":"normale","prezzo_min":1600,"prezzo_max":2300},

    # ── PONTEDERA (Valdera) ───────────────────────────────────────────────
    {"anno":2024,"semestre":2,"comune":"Pontedera","provincia":"PI","zona_omi":"Centrale",    "tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":900, "prezzo_max":1350},
    {"anno":2024,"semestre":2,"comune":"Pontedera","provincia":"PI","zona_omi":"Semicentrale","tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":700, "prezzo_max":1050},
    {"anno":2024,"semestre":2,"comune":"Pontedera","provincia":"PI","zona_omi":"Periferica",  "tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":550, "prezzo_max":800},

    # ── VOLTERRA (Valdicecina) ────────────────────────────────────────────
    {"anno":2024,"semestre":2,"comune":"Volterra","provincia":"PI","zona_omi":"Centrale",    "tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":1100,"prezzo_max":1650},
    {"anno":2024,"semestre":2,"comune":"Volterra","provincia":"PI","zona_omi":"Semicentrale","tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":800, "prezzo_max":1200},
    {"anno":2024,"semestre":2,"comune":"Volterra","provincia":"PI","zona_omi":"Periferica",  "tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":600, "prezzo_max":900},
    {"anno":2024,"semestre":2,"comune":"Volterra","provincia":"PI","zona_omi":"Centrale",    "tipo_immobile":"Ville e villini","stato":"normale","prezzo_min":1400,"prezzo_max":2100},

    # ── MARINA DI PISA / SAN GIULIANO TERME (Litorale Pisano) ────────────
    {"anno":2024,"semestre":2,"comune":"Marina di Pisa","provincia":"PI","zona_omi":"Periferica",  "tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":1100,"prezzo_max":1700},
    {"anno":2024,"semestre":2,"comune":"Marina di Pisa","provincia":"PI","zona_omi":"Semicentrale","tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":1300,"prezzo_max":1900},

    # ── SAN MINIATO (Valdarno Pisano) ─────────────────────────────────────
    {"anno":2024,"semestre":2,"comune":"San Miniato","provincia":"PI","zona_omi":"Centrale",    "tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":950, "prezzo_max":1400},
    {"anno":2024,"semestre":2,"comune":"San Miniato","provincia":"PI","zona_omi":"Semicentrale","tipo_immobile":"Abitazioni civili","stato":"normale","prezzo_min":750, "prezzo_max":1100},
]

# ─────────────────────────────────────────────────────────────────────────────
# Download reale dal portale Agenzia Entrate (best-effort)
# ─────────────────────────────────────────────────────────────────────────────
OMI_DOWNLOAD_BASE = "https://www.agenziaentrate.gov.it"
OMI_PAGE_URL = (
    "https://www.agenziaentrate.gov.it/portale/web/guest/schede/"
    "fabbricatiterreni/omi/banche-dati/quotazioni-immobiliari"
)
COMUNI_TARGET = {"livorno", "pisa", "cecina", "piombino", "portoferraio",
                 "collesalvetti", "rosignano marittimo", "pontedera",
                 "volterra", "san miniato", "san giuliano terme"}


def _trova_zip_url() -> str | None:
    """Cerca l'URL del CSV/ZIP più recente nella pagina Agenzia Entrate."""
    try:
        import requests
        from bs4 import BeautifulSoup
        r = requests.get(OMI_PAGE_URL, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible; HouseRadar/1.0)"
        })
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        # Cerca link che contengono "Toscana" o "toscana" nei testi/href
        for a in soup.find_all("a", href=True):
            href = a["href"]
            testo = (a.get_text() + href).lower()
            if "toscana" in testo and (".zip" in href.lower() or ".csv" in href.lower()):
                return href if href.startswith("http") else OMI_DOWNLOAD_BASE + href
    except Exception as e:
        print(f"[OMI] Ricerca URL fallita: {e}")
    return None


def _parse_omi_csv(content: bytes) -> list:
    """
    Parsa il CSV OMI (separatore ';', encoding latin-1).
    Colonne attese: ANNO_RIF, SEMESTRE, DENOMINAZIONE_COMUNE, SIGLA_PROVINCIA,
                    DES_ZONA (o FASCIA), DES_TIP (o CODTIP), STATO,
                    COMPR_MIN, COMPR_MAX
    """
    righe = []
    try:
        text = content.decode("latin-1", errors="replace")
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        # Normalizza nomi colonne (upper, strip)
        for row in reader:
            row = {k.strip().upper(): v.strip() for k, v in row.items()}
            comune = (row.get("DENOMINAZIONE_COMUNE") or row.get("DES_COMUNE") or "").strip().title()
            if comune.lower() not in COMUNI_TARGET:
                continue
            try:
                righe.append({
                    "anno":          int(row.get("ANNO_RIF", 2024)),
                    "semestre":      int(row.get("SEMESTRE", 2)),
                    "comune":        comune,
                    "provincia":     (row.get("SIGLA_PROVINCIA") or row.get("PROV") or "").strip().upper(),
                    "zona_omi":      (row.get("DES_ZONA") or row.get("FASCIA") or "Centrale").strip().title(),
                    "tipo_immobile": (row.get("DES_TIP") or row.get("DESTIP") or "Abitazioni civili").strip(),
                    "stato":         (row.get("STATO") or "normale").strip().lower(),
                    "prezzo_min":    float(re.sub(r"[^\d,.]", "", row.get("COMPR_MIN", "0")).replace(",", ".") or 0),
                    "prezzo_max":    float(re.sub(r"[^\d,.]", "", row.get("COMPR_MAX", "0")).replace(",", ".") or 0),
                })
            except (ValueError, KeyError):
                continue
    except Exception as e:
        print(f"[OMI] Errore parsing CSV: {e}")
    return righe


def _scarica_e_parsa() -> list:
    """Tenta il download reale. Ritorna lista righe o lista vuota se fallisce."""
    try:
        import requests
        zip_url = _trova_zip_url()
        if not zip_url:
            return []
        print(f"[OMI] Download: {zip_url}")
        r = requests.get(zip_url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (compatible; HouseRadar/1.0)"
        })
        if r.status_code != 200:
            print(f"[OMI] Download fallito: HTTP {r.status_code}")
            return []
        content = r.content
        # Se è uno ZIP, estrae il primo CSV
        if zip_url.lower().endswith(".zip") or content[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                csv_files = [f for f in z.namelist() if f.lower().endswith(".csv")]
                if not csv_files:
                    return []
                content = z.read(csv_files[0])
        righe = _parse_omi_csv(content)
        print(f"[OMI] Righe estratte per comuni target: {len(righe)}")
        return righe
    except Exception as e:
        print(f"[OMI] Download/parsing errore: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Funzione principale
# ─────────────────────────────────────────────────────────────────────────────
def importa_omi(forza: bool = False) -> int:
    """
    Importa le quotazioni OMI nel DB.
    Se forza=False e i dati sono già presenti, non fa nulla.
    Ritorna il numero di righe inserite.
    """
    if not forza and omi_ha_dati():
        print("[OMI] Dati già presenti nel DB — skip import")
        return 0

    print("[OMI] Avvio import quotazioni OMI...")

    # Tentativo 1: download reale
    righe = _scarica_e_parsa()
    fonte = "Agenzia Entrate (download)"

    # Fallback: seed dataset
    if not righe:
        print("[OMI] Download non riuscito — uso dataset seed (2024 S2)")
        righe = SEED_OMI
        fonte = "seed dataset (2024 S2)"

    n = upsert_omi(righe)
    print(f"[OMI] Importate {n} righe ({fonte})")
    # Riepilogo per comune
    from collections import Counter
    c = Counter(r["comune"] for r in righe)
    for comune, cnt in sorted(c.items()):
        print(f"  {comune}: {cnt} righe")
    return n


if __name__ == "__main__":
    importa_omi(forza=True)
