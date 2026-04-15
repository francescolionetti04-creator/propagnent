import asyncio
import threading
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from typing import Optional
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from database import init_db, get_annunci, get_stats, get_alert
from models import Annuncio

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
SCRAPER_DIR  = os.path.join(os.path.dirname(__file__), "..", "scraper")

app = FastAPI(title="PropAgent AI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inizializza il database all'avvio
init_db()

scraper_running = False


@app.on_event("startup")
async def startup_event():
    """Se il DB è vuoto, avvia lo scraper in background al primo boot (es. Render)."""
    stats = get_stats()
    if stats["totale"] < 10:
        print("[Startup] DB vuoto — avvio scraping automatico in background...")
        threading.Thread(target=_popola_db_in_background, daemon=True).start()


def _popola_db_in_background():
    """Lancia scraper in un thread separato se il DB è vuoto."""
    import time
    time.sleep(3)          # aspetta che uvicorn sia completamente su
    sys.path.insert(0, SCRAPER_DIR)
    try:
        from scraper import esegui_scraper
        from subito_api import scrapa_subito
        print("[Startup] DB vuoto — avvio scraping automatico...")
        esegui_scraper()
        scrapa_subito()
        print("[Startup] Scraping completato.")
    except Exception as e:
        print(f"[Startup] Errore scraping: {e}")


@app.get("/annunci")
def annunci(
    zona: Optional[str] = Query(None),
    tipo: Optional[str] = Query(None),
    fonte: Optional[str] = Query(None),
    sort: Optional[str] = Query("new"),
    prezzo_max: Optional[int] = Query(None),
):
    rows = get_annunci(zona=zona, tipo=tipo, fonte=fonte, sort=sort, prezzo_max=prezzo_max)
    result = [Annuncio.from_row(r).to_dict() for r in rows]
    return JSONResponse(content=result)


@app.get("/stats")
def stats():
    return JSONResponse(content=get_stats())


@app.get("/alert")
def alert():
    return JSONResponse(content=get_alert())


@app.post("/scraper/avvia")
async def avvia_scraper():
    global scraper_running
    if scraper_running:
        return JSONResponse(content={"status": "già in esecuzione", "messaggio": "Lo scraper è già in esecuzione."})

    async def run():
        global scraper_running
        scraper_running = True
        try:
            sys.path.insert(0, SCRAPER_DIR)
            from scraper import esegui_scraper
            from subito_api import scrapa_subito
            await asyncio.to_thread(esegui_scraper)
            await asyncio.to_thread(scrapa_subito)
        except Exception as e:
            print(f"[Scraper] Errore: {e}")
        finally:
            scraper_running = False

    asyncio.create_task(run())
    return JSONResponse(content={"status": "avviato", "messaggio": "Scraper in esecuzione in background..."})


@app.get("/scraper/status")
def scraper_status():
    return JSONResponse(content={"running": scraper_running})


# ── Serve frontend ──────────────────────────────────────────────────────────
# IMPORTANTE: le route API vanno definite PRIMA del mount statico
@app.get("/")
def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    # Se DB vuoto, popola in background
    stats = get_stats()
    if stats["totale"] < 10:
        threading.Thread(target=_popola_db_in_background, daemon=True).start()
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
