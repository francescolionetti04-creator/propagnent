"""
HouseRadar — Scheduler locale
==============================
Esegue ogni 30 minuti la pipeline completa di scraping + sync verso Render.
Ogni sync è isolato: se uno fallisce, gli altri continuano (continue-on-error).

Pipeline (in ordine):
  1. Idealista.it       (idealista_sync.py)
  2. Immobiliare.it v2  (immobiliare_sync_v2.py — Playwright)
  3. Casa.it            (casa_sync.py)
  4. Wikicasa.it        (wikicasa_sync.py)
  5. Tecnocasa.it       (tecnocasa_sync.py)

Render gestisce autonomamente Subito.it e Immobiliare.it (curl_cffi)
direttamente al boot, quindi non sono qui.

Env vars richieste:
    SYNC_TOKEN      — token segreto (stesso di Render)
    HOUSERADAR_URL  — es. https://houseradar.onrender.com (opzionale)
"""

import os
import sys
import importlib
import schedule
import time
import traceback
from datetime import datetime


# Lista dei moduli sync da eseguire in sequenza
SYNC_MODULES = [
    ("Idealista.it",          "idealista_sync"),
    ("Immobiliare.it (v2)",   "immobiliare_sync_v2"),
    ("Casa.it",               "casa_sync"),
    ("Wikicasa.it",           "wikicasa_sync"),
    ("Tecnocasa.it",          "tecnocasa_sync"),
]


def _run_sync(label: str, module_name: str):
    """Esegue un singolo sync. Cattura ogni eccezione per continue-on-error."""
    print(f"\n{'─'*58}")
    print(f"[Scheduler] ▶ {label} — {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'─'*58}")
    try:
        # Re-import a ogni run per evitare stato stantio
        if module_name in sys.modules:
            mod = importlib.reload(sys.modules[module_name])
        else:
            mod = importlib.import_module(module_name)
        mod.main()
        print(f"[Scheduler] ✓ {label} completato")
    except SystemExit as e:
        # Alcuni sync chiamano sys.exit(1) — tratta come errore non fatale
        print(f"[Scheduler] ⚠ {label} ha chiamato sys.exit({e.code}) — continuo")
    except Exception as e:
        print(f"[Scheduler] ✗ {label} errore: {e}")
        traceback.print_exc()


def job():
    """Esegue tutti i sync in sequenza con continue-on-error."""
    start = datetime.now()
    print(f"\n{'='*58}")
    print(f"[Scheduler] AVVIO JOB — {start.strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"[Scheduler] Pipeline: {len(SYNC_MODULES)} sync in sequenza")
    print(f"{'='*58}")

    for label, module in SYNC_MODULES:
        _run_sync(label, module)

    elapsed = (datetime.now() - start).total_seconds()
    print(f"\n{'='*58}")
    print(f"[Scheduler] JOB COMPLETATO in {elapsed:.0f}s — "
          f"prossima esecuzione tra 30 min")
    print(f"{'='*58}\n")


if __name__ == "__main__":
    print("=" * 58)
    print("HouseRadar — Scheduler locale avviato")
    print(f"Pipeline: {', '.join(label for label, _ in SYNC_MODULES)}")
    print(f"Target: {os.environ.get('HOUSERADAR_URL', 'https://houseradar.onrender.com')}")
    print("=" * 58 + "\n")

    if not os.environ.get("SYNC_TOKEN"):
        print("[Scheduler] ATTENZIONE: SYNC_TOKEN non impostato.")
        print("  Imposta la variabile d'ambiente prima di avviare.\n")

    # Aggiungi scraper dir al path per gli import
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    # Esecuzione immediata all'avvio
    job()

    schedule.every(30).minutes.do(job)

    while True:
        schedule.run_pending()
        time.sleep(60)
