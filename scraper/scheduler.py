"""
HouseRadar — Scheduler locale
==============================
Esegue ogni 30 minuti:
  - Scraping Idealista.it (IP locale residenziale)
  - Sync annunci → backend Render via /api/sync

Render gestisce autonomamente Subito.it e Immobiliare.it
(non bloccati sugli IP cloud).

Env vars richieste:
    SYNC_TOKEN      — token segreto (stesso di Render)
    HOUSERADAR_URL  — es. https://houseradar.onrender.com (opzionale)
"""

import schedule
import time
from datetime import datetime


def job():
    """Scraping Idealista locale + sync → Render."""
    print(f"\n[Scheduler] Avvio job — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    try:
        from idealista_sync import main as sync_main
        sync_main()
    except Exception as e:
        print(f"[Scheduler] Errore: {e}")
    print(f"[Scheduler] Job completato — prossima esecuzione tra 30 min\n")


if __name__ == "__main__":
    import os
    print("=" * 55)
    print("HouseRadar — Scheduler locale avviato")
    print("Job: Idealista scraping + sync → Render ogni 30 min")
    print(f"Target: {os.environ.get('HOUSERADAR_URL', 'https://houseradar.onrender.com')}")
    print("=" * 55 + "\n")

    if not os.environ.get("SYNC_TOKEN"):
        print("[Scheduler] ATTENZIONE: SYNC_TOKEN non impostato.")
        print("  Imposta la variabile d'ambiente prima di avviare.\n")

    # Esecuzione immediata all'avvio
    job()

    schedule.every(30).minutes.do(job)

    while True:
        schedule.run_pending()
        time.sleep(60)
