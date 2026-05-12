import asyncio
import threading
from fastapi import FastAPI, Query, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import HTTPException
from typing import Optional
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from database import (
    init_db, get_annunci, get_stats, get_alert,
    get_omi_zone_map, upsert_sync_annunci, get_comparabili,
    get_conn, _cur, _sql,
)
from models import Annuncio

# ── Auth + Stripe + Privato ───────────────────────────────────────────────────
from auth.routes import router as auth_router
from auth.dependencies import (
    require_auth, require_paid, require_privato, require_compratore,
    current_user, AuthRedirect,
)
from auth.users_db import public_user
from services.stripe_svc import router as stripe_router, ensure_stripe_prices
from privato.routes import router_priv as privato_router, router_agent as agente_router
from compratore.routes import router as compratore_router
from agency.routes import router as agency_router, auth_router as agency_auth_router

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
SCRAPER_DIR  = os.path.join(os.path.dirname(__file__), "..", "scraper")

# ── Init DB (tabelle annunci/users/app_config) ───────────────────────────────
init_db()

# ── Seed founders (idempotente per-email, gira ad ogni boot) ─────────────────
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    from seed_founders import run as _seed_founders
    _seed_founders()
except Exception as _seed_err:
    print(f"[Seed] errore founders: {_seed_err}")


app = FastAPI(title="HouseRadar", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# ── Auth + Stripe + Privato routers ──────────────────────────────────────────
app.include_router(auth_router)
app.include_router(stripe_router)
app.include_router(privato_router)
app.include_router(agente_router)
app.include_router(compratore_router)
app.include_router(agency_router)
app.include_router(agency_auth_router)


@app.exception_handler(AuthRedirect)
async def _auth_redirect_handler(request: Request, exc: AuthRedirect):
    """Pagine → 303 redirect; API/JSON → 401 con destinazione."""
    accept = request.headers.get("accept", "")
    if request.url.path.startswith("/api") or "application/json" in accept:
        return JSONResponse({"error": "auth_required", "location": exc.location},
                            status_code=401)
    return RedirectResponse(url=exc.location, status_code=303)


# ── Bootstrap Stripe price_id al boot (best-effort) ──────────────────────────
try:
    if os.environ.get("STRIPE_SECRET_KEY"):
        ensure_stripe_prices()
except Exception as _se:
    print(f"[Stripe] bootstrap errore: {_se}")


# ── APScheduler: match + email cron ──────────────────────────────────────────
_scheduler = None


@app.on_event("startup")
async def _start_match_scheduler():
    global _scheduler
    if os.environ.get("DISABLE_MATCH_CRON") == "1":
        print("[match] cron disabilitato via DISABLE_MATCH_CRON=1")
        return
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from services.match_service import run_full_pipeline

        sched = BackgroundScheduler(timezone="Europe/Rome", daemon=True)
        # Ogni notte alle 03:00 Europe/Rome
        sched.add_job(run_full_pipeline,
                      CronTrigger(hour=3, minute=0),
                      id="match_pipeline",
                      replace_existing=True,
                      max_instances=1,
                      coalesce=True)
        sched.start()
        _scheduler = sched
        print("[match] scheduler avviato — match pipeline 03:00 Europe/Rome")
    except Exception as e:
        print(f"[match] scheduler errore: {e}")


@app.on_event("shutdown")
async def _stop_match_scheduler():
    global _scheduler
    if _scheduler:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass

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
    return JSONResponse(content=results)


@app.post("/api/sync")
async def sync_annunci(request: Request):
    """
    Endpoint protetto per sincronizzare annunci da scraper locali (es. Idealista).
    Richiede header: X-Sync-Token: <SYNC_TOKEN>
    Body: JSON array di annunci nel formato del DB.
    """
    token = request.headers.get("X-Sync-Token", "")
    expected = os.environ.get("SYNC_TOKEN", "")
    if not expected:
        return JSONResponse(status_code=503, content={"error": "SYNC_TOKEN non configurato sul server."})
    if token != expected:
        return JSONResponse(status_code=401, content={"error": "Token non valido."})

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Body JSON non valido."})

    if not isinstance(body, list):
        return JSONResponse(status_code=400, content={"error": "Atteso un array JSON di annunci."})

    result = upsert_sync_annunci(body)
    print(f"[Sync] Ricevuti {len(body)} annunci — "
          f"inseriti={result['inseriti']} aggiornati={result['aggiornati']}")
    return JSONResponse(content=result)


@app.get("/api/report-pdf")
def report_pdf(
    indirizzo: Optional[str] = Query(""),
    tipo:      Optional[str] = Query("Appartamento"),
    mq:        Optional[int] = Query(None),
    zona:      Optional[str] = Query(""),
):
    """
    Genera un PDF professionale di valutazione immobiliare con:
    - Stima valore basata su dati OMI (mq × €/m² min/max)
    - Tabella comparabili (ultimi 5 annunci simili nel DB)
    """
    from pdf_report import genera_report

    omi_map     = get_omi_zone_map()
    omi         = omi_map.get(zona or "") if zona else None
    comparabili = get_comparabili(zona=zona or "", tipo=tipo or "Appartamento", mq=mq)

    pdf_bytes = genera_report(
        indirizzo   = indirizzo or "",
        tipo        = tipo or "Appartamento",
        mq          = mq,
        zona        = zona or "",
        omi         = omi,
        comparabili = comparabili,
    )

    safe_name = (indirizzo or "valutazione")[:40].replace(" ", "_").replace("/", "-")
    filename  = f"HouseRadar_{safe_name}.pdf"

    return Response(
        content     = pdf_bytes,
        media_type  = "application/pdf",
        headers     = {
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control":       "no-store",
        },
    )


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
    conn = get_conn()
    cur = _cur(conn)

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

    cur.execute(_sql("SELECT COUNT(*) FROM annunci WHERE is_nuovo=1"))
    nuovi = cur.fetchone()[0]

    cur.execute("SELECT MAX(data_inserimento) FROM annunci")
    ultimo_inserimento = cur.fetchone()[0]

    conn.close()
    return JSONResponse(content={
        "totale": totale,
        "nuovi_oggi": nuovi,
        "ultimo_inserimento": str(ultimo_inserimento) if ultimo_inserimento else None,
        "per_portale": per_portale,
        "per_tipo": per_tipo,
    })


# ── Serve frontend ──────────────────────────────────────────────────────────
# IMPORTANTE: le route API vanno definite PRIMA del mount statico

_NO_CACHE = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _serve(html_file: str) -> FileResponse:
    return FileResponse(os.path.join(FRONTEND_DIR, html_file), headers=_NO_CACHE)


@app.get("/")
def root():
    """Homepage pubblica — landing page marketing."""
    return _serve("index.html")


@app.get("/pricing")
def pricing():
    """Pagina pubblica pricing."""
    return _serve("pricing.html")


@app.get("/app")
def app_dashboard(user=Depends(require_paid)):
    """Dashboard agenti — richiede auth + (founder OR subscription attiva)."""
    return _serve("app.html")


@app.get("/app/team")
def app_team(user=Depends(require_paid)):
    """Gestione team agenzia (visibile solo agli owner — il frontend mostra 403 altrimenti)."""
    return _serve("app_team.html")


@app.get("/signup/invito/{token}")
def signup_invito(token: str):
    """Pagina pubblica accettazione invito agenzia."""
    return _serve("signup_invito.html")


@app.get("/privato/onboarding")
def privato_onboarding(user=Depends(require_privato)):
    return _serve("privato_onboarding.html")


@app.get("/privato/nuovo-annuncio")
def privato_nuovo_annuncio(user=Depends(require_privato)):
    return _serve("privato_nuovo_annuncio.html")


@app.get("/privato/dashboard")
def privato_dashboard(user=Depends(require_privato)):
    return _serve("privato_dashboard.html")


@app.get("/compratore/onboarding")
def compratore_onboarding(user=Depends(require_compratore)):
    return _serve("compratore_onboarding.html")


@app.get("/compratore/nuove-preferenze")
def compratore_nuove_preferenze(user=Depends(require_compratore)):
    return _serve("compratore_nuove_preferenze.html")


@app.get("/compratore/dashboard")
def compratore_dashboard(user=Depends(require_compratore)):
    return _serve("compratore_dashboard.html")


@app.get("/forgot-password")
def forgot_page():
    return _serve("forgot-password.html")


@app.get("/reset-password")
def reset_page():
    return _serve("reset-password.html")


@app.get("/api/me")
def api_me(request: Request):
    """Ritorna l'utente corrente (None se non autenticato).
    Include flag `is_agency_owner` per mostrare la sezione AGENZIA in sidebar."""
    user = current_user(request)
    payload = public_user(user)
    if payload:
        try:
            from agency.db import get_agency_by_owner
            ag = get_agency_by_owner(user["id"])
            payload["is_agency_owner"] = bool(ag)
            payload["agency_id"] = ag["id"] if ag else None
        except Exception:
            payload["is_agency_owner"] = False
            payload["agency_id"] = None
    return JSONResponse({"user": payload})


@app.post("/api/agente/tutorial-visto")
def api_tutorial_visto(user=Depends(require_auth)):
    """Marca il video tutorial onboarding come visto per l'utente corrente."""
    from auth.users_db import _update
    _update(user["id"], tutorial_visto=1)
    return {"success": True}


@app.get("/api/profilo/{user_id}")
def api_profilo(user_id: int):
    """Dati pubblici di un agente (no auth). Solo per role agente/consulente."""
    from auth.users_db import get_user_by_id
    u = get_user_by_id(user_id)
    if not u or u.get("role") not in ("agente", "consulente"):
        raise HTTPException(404, "Profilo non trovato")
    return {
        "id":         u["id"],
        "nome":       u.get("nome"),
        "cognome":    u.get("cognome"),
        "role":       u.get("role"),
        "city":       u.get("city"),
        "is_founder": bool(u.get("is_founder")),
        "telefono":   u.get("telefono"),  # serve per WhatsApp CTA
    }


@app.get("/signup")
def signup():
    """Placeholder registrazione (Sprint 2)."""
    return _serve("signup.html")


@app.get("/accedi")
def accedi():
    """Placeholder login (Sprint 2)."""
    return _serve("accedi.html")


@app.get("/profilo/{user_id}")
def profilo_pubblico(user_id: int):
    """Pagina pubblica profilo agente — accessibile senza login."""
    return _serve("profilo_pubblico.html")


@app.get("/lead/{lead_id}")
def lead_dettaglio_page(lead_id: int, user=Depends(require_paid)):
    """Pagina dettaglio lead venditore — visibile solo agli agenti della stessa provincia."""
    from privato.db import get_lead_by_id, PROVINCE
    lead = get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(404, "Lead non trovato")
    user_city = (user.get("city") or "").strip()
    if any(p.lower() == user_city.lower() for p in PROVINCE):
        if (lead.get("provincia") or "").lower() != user_city.lower():
            raise HTTPException(403, "Lead non nella tua provincia")
    return _serve("lead_dettaglio.html")


@app.get("/profilo")
def profilo():
    """Pagina pubblica del profilo agente."""
    return _serve("profilo.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    # Se DB vuoto, popola in background
    stats = get_stats()
    if stats["totale"] < 10:
        threading.Thread(target=_popola_db_in_background, daemon=True).start()
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
