"""
HouseRadar — Immobiliare.it Sync
=================================
Scraping Immobiliare.it + push a Render via POST /api/sync.
Funziona sia in locale (IP residenziale) che su GitHub Actions (IP GHA variabili).

Strategia DB:
  - Su GitHub Actions (GITHUB_ACTIONS=true): usa /tmp/houseradar_imm.db (effimero)
  - In locale: usa backend/propagnent.db se esiste, altrimenti /tmp

Env vars richieste:
    SYNC_TOKEN      — token segreto (stesso valore su Render)
    HOUSERADAR_URL  — URL del backend (default: https://houseradar.onrender.com)
"""

import os
import sys
import sqlite3
import requests
from datetime import datetime

# ── Path setup ────────────────────────────────────────────────────────────────
_DIR      = os.path.dirname(os.path.abspath(__file__))
_LOCAL_DB = os.path.join(_DIR, "..", "backend", "propagnent.db")
_TMP_DB   = "/tmp/houseradar_imm.db"

IS_GHA  = os.environ.get("GITHUB_ACTIONS") == "true"
DB_PATH = _TMP_DB if (IS_GHA or not os.path.exists(_LOCAL_DB)) else _LOCAL_DB

# ── sys.path: scraper dir + backend dir ──────────────────────────────────────
sys.path.insert(0, _DIR)
sys.path.insert(0, os.path.join(_DIR, "..", "backend"))

# ── Patch DB_PATH prima di importare i moduli che lo usano ───────────────────
import database
database.DB_PATH = DB_PATH          # init_db() userà questo path

import immobiliare_scraper
immobiliare_scraper.DB_PATH = DB_PATH  # salva_annunci() userà questo path

# ── Config ────────────────────────────────────────────────────────────────────
HOUSERADAR_URL = os.environ.get("HOUSERADAR_URL", "https://houseradar.onrender.com").rstrip("/")
SYNC_TOKEN     = os.environ.get("SYNC_TOKEN", "")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _init_tmp_db():
    """Crea le tabelle nel DB temporaneo (solo su GHA o primo avvio)."""
    database.init_db()
    print(f"[Sync] DB inizializzato: {DB_PATH}")


def leggi_annunci() -> list:
    """Legge tutti gli annunci immobiliare.it dal DB (tmp o locale)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM annunci WHERE portale = 'immobiliare.it'")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def sincronizza(annunci: list) -> dict:
    """POST gli annunci al backend Render. Ritorna {inseriti, aggiornati, totale}."""
    resp = requests.post(
        f"{HOUSERADAR_URL}/api/sync",
        json=annunci,
        headers={
            "X-Sync-Token": SYNC_TOKEN,
            "Content-Type": "application/json",
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*58}")
    print(f"HouseRadar — Immobiliare.it Sync — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"Target : {HOUSERADAR_URL}")
    print(f"DB     : {DB_PATH}  |  GHA: {IS_GHA}")
    print(f"{'='*58}\n")

    if not SYNC_TOKEN:
        print("[Sync] ERRORE: SYNC_TOKEN non impostato — interrompo.")
        sys.exit(1)

    # Fase 0: inizializza DB (sempre su GHA; in locale solo se non esiste)
    if IS_GHA or not os.path.exists(_LOCAL_DB):
        _init_tmp_db()

    # Fase 1: scraping
    print("[Sync] Fase 1 — Scraping Immobiliare.it...")
    from immobiliare_scraper import scrapa_immobiliare
    try:
        n = scrapa_immobiliare()
        print(f"[Sync] Scraping completato — {n} nuovi annunci nel DB\n")
    except Exception as e:
        print(f"[Sync] Errore scraping Immobiliare.it: {e}")
        n = 0

    # Fase 2: lettura dal DB
    annunci = leggi_annunci()
    print(f"[Sync] Annunci Immobiliare.it nel DB: {len(annunci)}")

    if not annunci:
        print("[Sync] Nessun annuncio — fine.")
        return

    # Fase 3: sync → Render
    print(f"[Sync] Fase 3 — Invio a {HOUSERADAR_URL}/api/sync ...")
    try:
        result = sincronizza(annunci)
        ins = result.get("inseriti", "?")
        agg = result.get("aggiornati", "?")
        tot = result.get("totale", "?")
        print(f"[Sync] ✓ Sincronizzati {len(annunci)} annunci Immobiliare.it → Render")
        print(f"       Inseriti: {ins} | Aggiornati: {agg} | Totale: {tot}\n")
    except requests.HTTPError as e:
        status = e.response.status_code if e.response else "?"
        body   = e.response.text[:300] if e.response else ""
        print(f"[Sync] ERRORE HTTP {status}: {body}")
        sys.exit(1)
    except requests.ConnectionError:
        print(f"[Sync] ERRORE: impossibile raggiungere {HOUSERADAR_URL}")
        sys.exit(1)
    except Exception as e:
        print(f"[Sync] ERRORE: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
