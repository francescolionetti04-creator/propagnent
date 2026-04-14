import asyncio
import schedule
import time
from datetime import datetime
from scraper import esegui_tutto

def job():
    print(f"\nScheduler: avvio scraping — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    result = asyncio.run(esegui_tutto())
    print(f"Completato: Idealista={result['idealista']} | Subito={result['subito']} | Totale={result['totale']}\n")

if __name__ == "__main__":
    print("PropAgent AI — Scheduler avviato")
    print("Zone: Livorno e Pisa | Fonti: Idealista.it + Subito.it")
    print("Frequenza: ogni 2 ore\n")

    job()
    schedule.every(2).hours.do(job)

    while True:
        schedule.run_pending()
        time.sleep(60)
