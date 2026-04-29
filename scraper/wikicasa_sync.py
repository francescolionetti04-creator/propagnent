"""
HouseRadar — Wikicasa.it Sync
==============================
Scraping Wikicasa.it + push a Render via POST /api/sync.
"""

import os
import sys
import sqlite3
import requests
from datetime import datetime

_DIR      = os.path.dirname(os.path.abspath(__file__))
_LOCAL_DB = os.path.join(_DIR, "..", "backend", "propagnent.db")
_TMP_DB   = "/tmp/houseradar_wiki.db"

IS_GHA  = os.environ.get("GITHUB_ACTIONS") == "true"
DB_PATH = _TMP_DB if (IS_GHA or not os.path.exists(_LOCAL_DB)) else _LOCAL_DB

sys.path.insert(0, _DIR)
sys.path.insert(0, os.path.join(_DIR, "..", "backend"))

import database
database.DB_PATH = DB_PATH

import wikicasa_scraper
wikicasa_scraper.DB_PATH = DB_PATH

HOUSERADAR_URL = os.environ.get("HOUSERADAR_URL", "https://houseradar.onrender.com").rstrip("/")
SYNC_TOKEN     = os.environ.get("SYNC_TOKEN", "")

PORTALE = "wikicasa.it"
LABEL   = "Wikicasa.it"


def _init_tmp_db():
    database.init_db()
    print(f"[Sync] DB inizializzato: {DB_PATH}")


def leggi_annunci() -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM annunci WHERE portale = ?", (PORTALE,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def sincronizza(annunci: list) -> dict:
    resp = requests.post(
        f"{HOUSERADAR_URL}/api/sync",
        json=annunci,
        headers={"X-Sync-Token": SYNC_TOKEN, "Content-Type": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    print(f"\n{'='*58}")
    print(f"HouseRadar — {LABEL} Sync — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"Target : {HOUSERADAR_URL}")
    print(f"DB     : {DB_PATH}  |  GHA: {IS_GHA}")
    print(f"{'='*58}\n")

    if not SYNC_TOKEN:
        print("[Sync] ERRORE: SYNC_TOKEN non impostato — interrompo.")
        sys.exit(1)

    if IS_GHA or not os.path.exists(_LOCAL_DB):
        _init_tmp_db()

    print(f"[Sync] Fase 1 — Scraping {LABEL}...")
    try:
        n = wikicasa_scraper.scrapa_wikicasa()
        print(f"[Sync] Scraping completato — {n} nuovi annunci\n")
    except Exception as e:
        print(f"[Sync] Errore scraping {LABEL}: {e}")

    annunci = leggi_annunci()
    print(f"[Sync] Annunci {LABEL} nel DB: {len(annunci)}")
    if not annunci:
        print("[Sync] Nessun annuncio — fine.")
        return

    print(f"[Sync] Fase 3 — Invio a {HOUSERADAR_URL}/api/sync ...")
    try:
        result = sincronizza(annunci)
        print(f"[Sync] ✓ {len(annunci)} annunci {LABEL} → Render | "
              f"Inseriti: {result.get('inseriti')} | "
              f"Aggiornati: {result.get('aggiornati')} | "
              f"Totale: {result.get('totale')}\n")
    except requests.HTTPError as e:
        print(f"[Sync] ERRORE HTTP {e.response.status_code if e.response else '?'}: "
              f"{e.response.text[:300] if e.response else ''}")
        sys.exit(1)
    except Exception as e:
        print(f"[Sync] ERRORE: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
