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
from database import init_db, get_annunci, get_stats, get_alert, get_omi_zone_map
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

# Inizializza il database all'avvio (crea tabelle + migrazioni)
init_db()

# Carica dati OMI al boot (seed se DB vuoto, ~0.1s)
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scraper"))
    from omi_import import importa_omi
    importa_omi()
except Exception as _omi_err:
    print(f"[OMI] Errore import avvio: {_omi_err}")

scraper_running = False


@app.on_event("startup")
async def startup_event():
    """Se il DB è vuoto, avvia lo scraper in background al primo boot (es. Render)."""
    stats = get_stats()
    if stats["totale"] < 10:
        print("[Startup] DB vuoto — avvio scraping automatico in background...")
        threading.Thread(target=_popola_db_in_background, daemon=True).start()


def _popola_db_in_background():
    """Lancia scraper in un thread separato se il DB è vuoto.
    Ogni fonte è isolata: se una crasha le altre continuano comunque."""
    import time
    time.sleep(3)          # aspetta che uvicorn sia completamente su
    sys.path.insert(0, SCRAPER_DIR)
    print("[Startup] DB vuoto — avvio scraping automatico...")

    # ── Idealista ─────────────────────────────────────────────────────
    # Disabilitato su Render: gli IP cloud vengono bloccati con 403.
    # Riabilitare solo se si usa un proxy residenziale.
    print("[Startup] Idealista.it — temporaneamente disabilitato su Render (IP cloud bloccato)")

    # ── Subito.it ─────────────────────────────────────────────────────
    try:
        print("[Scraping] Avvio Subito.it...")
        from subito_api import scrapa_subito
        n = scrapa_subito()
        print(f"[Scraping] Subito.it completato — {n} nuovi annunci")
    except Exception as e:
        print(f"[Scraping] Subito.it ERRORE: {e}")

    # ── Immobiliare.it ────────────────────────────────────────────────
    try:
        print("[Scraping] Avvio Immobiliare.it...")
        from immobiliare_scraper import scrapa_immobiliare
        n = scrapa_immobiliare()
        print(f"[Scraping] Immobiliare.it completato — {n} nuovi annunci")
    except Exception as e:
        print(f"[Scraping] Immobiliare.it ERRORE: {e}")

    print("[Scraping] Ciclo completato.")


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
        sys.path.insert(0, SCRAPER_DIR)
        # Idealista disabilitato su Render (403 IP cloud)
        print("[Scraper] Idealista.it — disabilitato su Render (IP cloud bloccato)")
        try:
            from subito_api import scrapa_subito
            await asyncio.to_thread(scrapa_subito)
        except Exception as e:
            print(f"[Scraper] Subito.it errore: {e}")
        try:
            from immobiliare_scraper import scrapa_immobiliare
            await asyncio.to_thread(scrapa_immobiliare)
        except Exception as e:
            print(f"[Scraper] Immobiliare.it errore: {e}")
        finally:
            scraper_running = False

    asyncio.create_task(run())
    return JSONResponse(content={"status": "avviato", "messaggio": "Scraper in esecuzione in background..."})


@app.get("/scraper/status")
def scraper_status():
    return JSONResponse(content={"running": scraper_running})


# ─────────────────────────────────────────────────────────────────────────────
# MATCH AI COMPRATORI
# ─────────────────────────────────────────────────────────────────────────────

def _calcola_score(ann: dict, zona=None, mq=None, budget=None, camere=None, bagni=None,
                   terrazzo=0, garage=0, ascensore=0, giardino=0) -> dict:
    """Calcola un punteggio 10-99 di compatibilità fra un annuncio e un profilo cliente."""

    # ── Prezzo 30% ────────────────────────────────────────────────────
    if budget and ann.get("prezzo"):
        p, b = ann["prezzo"], budget
        s_p = (80 + 20 * (1 - p / b)) if p <= b else max(0.0, 80 - ((p - b) / b) * 200)
    else:
        s_p = 60.0
    s_prezzo = round(min(100, max(0, s_p)), 1)

    # ── Superficie 25% ────────────────────────────────────────────────
    if mq and ann.get("mq"):
        s_mq = max(0.0, 100 - abs(ann["mq"] - mq) / mq * 250)
    else:
        s_mq = 60.0
    s_superficie = round(min(100, max(0, s_mq)), 1)

    # ── Zona 20% ─────────────────────────────────────────────────────
    if zona and ann.get("zona"):
        s_z = 100.0 if ann["zona"] == zona else 0.0
    else:
        s_z = 70.0
    s_zona = s_z

    # ── Camere 15% ───────────────────────────────────────────────────
    if camere and ann.get("camere"):
        diff = abs(ann["camere"] - camere)
        s_c = 100.0 if diff == 0 else 60.0 if diff == 1 else 20.0 if diff == 2 else 0.0
    else:
        s_c = 60.0
    s_camere = s_c

    # ── Extra 10% ────────────────────────────────────────────────────
    testo = " ".join(filter(None, [
        ann.get("indirizzo", ""),
        ann.get("intel_privato") or "",
        ann.get("intel_warning") or "",
        ann.get("ai_insight") or "",
    ])).lower()

    kw_map = {
        "terrazzo":  ["terrazzo", "terrazza", "balcone"],
        "garage":    ["garage", "box auto", "posto auto", "box"],
        "ascensore": ["ascensore"],
        "giardino":  ["giardino"],
        "bagni":     ["doppi servizi", "2 bagni", "3 bagni", "bagno + wc"],
    }
    extra_richiesti = {
        "terrazzo":  bool(terrazzo),
        "garage":    bool(garage),
        "ascensore": bool(ascensore),
        "giardino":  bool(giardino),
        "bagni":     bool(bagni and bagni > 1),
    }
    extra_detail: dict = {}
    n_req = n_found = 0
    for k, richiesto in extra_richiesti.items():
        if richiesto:
            trovato = any(w in testo for w in kw_map[k])
            extra_detail[k] = trovato
            n_req += 1
            if trovato:
                n_found += 1
        else:
            extra_detail[k] = None  # non richiesto → non mostrato
    s_extra = round((n_found / n_req * 100) if n_req > 0 else 70.0, 1)

    # ── Score finale pesato ───────────────────────────────────────────
    dettaglio = {
        "prezzo":     s_prezzo,
        "superficie": s_superficie,
        "zona":       s_zona,
        "camere":     s_camere,
        "extra":      s_extra,
    }
    pesi = {"prezzo": 0.30, "superficie": 0.25, "zona": 0.20, "camere": 0.15, "extra": 0.10}
    finale = max(10, min(99, round(sum(dettaglio[k] * pesi[k] for k in pesi))))

    return {"score": finale, "dettaglio": dettaglio, "extra_detail": extra_detail}


@app.get("/match")
def match_compratore(
    zona:      Optional[str] = Query(None),
    tipo:      Optional[str] = Query(None),
    mq:        Optional[int] = Query(None),
    budget:    Optional[int] = Query(None),
    camere:    Optional[int] = Query(None),
    bagni:     Optional[int] = Query(None),
    terrazzo:  int = Query(0),
    garage:    int = Query(0),
    ascensore: int = Query(0),
    giardino:  int = Query(0),
):
    rows = get_annunci(tipo=tipo)
    results = []
    for row in rows:
        ann = Annuncio.from_row(row).to_dict()
        s = _calcola_score(ann, zona=zona, mq=mq, budget=budget, camere=camere, bagni=bagni,
                           terrazzo=terrazzo, garage=garage, ascensore=ascensore, giardino=giardino)
        ann["score"] = s["score"]
        ann["score_dettaglio"] = s["dettaglio"]
        ann["extra_detail"] = s["extra_detail"]
        results.append(ann)

    results.sort(key=lambda x: x["score"], reverse=True)
    return JSONResponse(content=results[:50])


@app.get("/api/omi")
def api_omi():
    """
    Restituisce la mappa zone HouseRadar → range OMI €/m² (2024 S2).
    Usata dal frontend per mostrare il badge prezzo vs mercato nelle card.
    """
    return JSONResponse(content=get_omi_zone_map())


@app.get("/debug/stats")
def debug_stats():
    """Statistiche dettagliate per portale e tipo — utile per verificare lo stato del DB."""
    conn = __import__("sqlite3").connect(
        __import__("os").path.join(__import__("os").path.dirname(__file__), "propagnent.db")
    )
    conn.row_factory = __import__("sqlite3").Row
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM annunci")
    totale = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(portale, 'sconosciuto') as p, COUNT(*) as n
        FROM annunci GROUP BY p ORDER BY n DESC
    """)
    per_portale = {r["p"]: r["n"] for r in cur.fetchall()}

    cur.execute("""
        SELECT COALESCE(fonte, 'sconosciuto') as f, COUNT(*) as n
        FROM annunci GROUP BY f ORDER BY n DESC
    """)
    per_tipo = {r["f"]: r["n"] for r in cur.fetchall()}

    cur.execute("SELECT COUNT(*) FROM annunci WHERE is_nuovo=1")
    nuovi = cur.fetchone()[0]

    cur.execute("SELECT MAX(data_inserimento) FROM annunci")
    ultimo_inserimento = cur.fetchone()[0]

    conn.close()
    return JSONResponse(content={
        "totale": totale,
        "nuovi_oggi": nuovi,
        "ultimo_inserimento": ultimo_inserimento,
        "per_portale": per_portale,
        "per_tipo": per_tipo,
    })


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
