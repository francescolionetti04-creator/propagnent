"""
HouseRadar — Idealista Sync
===========================
Esegue lo scraping Idealista.it localmente (IP residenziale italiano)
e sincronizza gli annunci con il backend Render via POST /api/sync.

Uso:
    python idealista_sync.py

Variabili d'ambiente richieste:
    SYNC_TOKEN      — token segreto (stesso valore configurato su Render)
    HOUSERADAR_URL  — URL base del backend (default: https://houseradar.onrender.com)
"""

import os
import sys
import sqlite3
import requests
from datetime import datetime

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)
sys.path.insert(0, os.path.join(_DIR, "..", "backend"))

DB_PATH = os.path.join(_DIR, "..", "backend", "propagnent.db")

HOUSERADAR_URL = os.environ.get("HOUSERADAR_URL", "https://houseradar.onrender.com").rstrip("/")
SYNC_TOKEN = os.environ.get("SYNC_TOKEN", "")


def leggi_annunci_idealista() -> list:
    """Legge dal DB locale tutti gli annunci di idealista.it."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM annunci WHERE portale = 'idealista.it'")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def sincronizza(annunci: list) -> dict:
    """
    POSTa l'array di annunci al backend remoto.
    Ritorna il JSON di risposta {"inseriti": N, "aggiornati": N, "totale": N}.
    """
    url = f"{HOUSERADAR_URL}/api/sync"
    resp = requests.post(
        url,
        json=annunci,
        headers={
            "X-Sync-Token": SYNC_TOKEN,
            "Content-Type": "application/json",
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    print(f"\n{'='*55}")
    print(f"HouseRadar — Idealista Sync — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"Target: {HOUSERADAR_URL}")
    print(f"{'='*55}\n")

    if not SYNC_TOKEN:
        print("[Sync] ERRORE: variabile d'ambiente SYNC_TOKEN non impostata.")
        print("  Imposta SYNC_TOKEN con il token configurato su Render.")
        sys.exit(1)

    # 1. Scraping Idealista locale (IP residenziale)
    print("[Sync] Fase 1 — Scraping Idealista.it in locale...")
    from scraper import esegui_scraper
    try:
        n_scraped = esegui_scraper()
        print(f"[Sync] Scraping completato — {n_scraped} nuovi annunci salvati in DB locale\n")
    except Exception as e:
        print(f"[Sync] Errore scraping Idealista: {e}")
        # Continua comunque: sincronizza quelli già in DB
        n_scraped = 0

    # 2. Leggi tutti gli annunci Idealista dal DB locale
    annunci = leggi_annunci_idealista()
    print(f"[Sync] Fase 2 — Annunci Idealista nel DB locale: {len(annunci)}")

    if not annunci:
        print("[Sync] Nessun annuncio da sincronizzare. Fine.")
        return

    # 3. Invia al backend remoto
    print(f"[Sync] Fase 3 — Invio a {HOUSERADAR_URL}/api/sync ...")
    try:
        result = sincronizza(annunci)
        ins = result.get("inseriti", "?")
        agg = result.get("aggiornati", "?")
        tot = result.get("totale", "?")
        print(f"[Sync] ✓ Sincronizzati {len(annunci)} annunci Idealista → {HOUSERADAR_URL}")
        print(f"       Inseriti: {ins} | Aggiornati: {agg} | Totale: {tot}\n")
    except requests.HTTPError as e:
        status = e.response.status_code if e.response else "?"
        body = e.response.text[:200] if e.response else ""
        print(f"[Sync] ERRORE HTTP {status}: {body}")
    except requests.ConnectionError:
        print(f"[Sync] ERRORE: impossibile connettersi a {HOUSERADAR_URL}. Backend raggiungibile?")
    except Exception as e:
        print(f"[Sync] ERRORE: {e}")


if __name__ == "__main__":
    main()
