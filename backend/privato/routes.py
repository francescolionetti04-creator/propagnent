"""API privato + agente per il modulo Lead Venditori."""

import os
import sys
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, validator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from auth.dependencies import require_privato, require_paid
from auth.users_db import get_user_by_id

from .db import (
    create_lead, get_active_lead_by_user, get_lead_by_id, update_lead,
    list_active_leads, log_contatto, list_contatti_for_lead,
    list_contatti_set_for_agente, public_lead,
    VALID_TIPI, VALID_URGENZE, VALID_STATUS, PROVINCE,
)

# Email notification
from services.email import _send, _wrap, _btn  # type: ignore


router_priv  = APIRouter(prefix="/api/privato", tags=["privato"])
router_agent = APIRouter(prefix="/api/agente",  tags=["agente"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class LeadIn(BaseModel):
    indirizzo:        str
    citta:            str
    provincia:        str
    tipo_immobile:    str
    mq:               Optional[int] = None
    camere:           Optional[int] = None
    bagni:            Optional[int] = None
    prezzo_richiesto: Optional[int] = None
    descrizione:      Optional[str] = None
    urgenza:          str = "media"

    @validator("provincia")
    def _v_prov(cls, v):
        if v not in PROVINCE:
            raise ValueError(f"Provincia deve essere una di: {PROVINCE}")
        return v

    @validator("tipo_immobile")
    def _v_tipo(cls, v):
        v = (v or "").lower()
        if v not in VALID_TIPI:
            raise ValueError(f"tipo_immobile deve essere uno di: {VALID_TIPI}")
        return v

    @validator("urgenza")
    def _v_urg(cls, v):
        v = (v or "media").lower()
        if v not in VALID_URGENZE:
            raise ValueError(f"urgenza deve essere una di: {VALID_URGENZE}")
        return v


class LeadUpdate(BaseModel):
    indirizzo:        Optional[str] = None
    citta:            Optional[str] = None
    provincia:        Optional[str] = None
    tipo_immobile:    Optional[str] = None
    mq:               Optional[int] = None
    camere:           Optional[int] = None
    bagni:            Optional[int] = None
    prezzo_richiesto: Optional[int] = None
    descrizione:      Optional[str] = None
    urgenza:          Optional[str] = None


# ─── /api/privato/* ─────────────────────────────────────────────────────────

@router_priv.post("/lead")
def create_lead_route(body: LeadIn, user=Depends(require_privato)):
    fields = body.dict()
    fields["telefono_privato"] = user.get("telefono")
    lead = create_lead(user["id"], **fields)
    return {"lead_id": lead["id"], "message": "Annuncio creato", "lead": public_lead(lead, with_telefono=True)}


@router_priv.get("/me/lead")
def my_lead(user=Depends(require_privato)):
    lead = get_active_lead_by_user(user["id"])
    return {"lead": public_lead(lead, with_telefono=True) if lead else None}


@router_priv.put("/lead/{lead_id}")
def update_lead_route(lead_id: int, body: LeadUpdate, user=Depends(require_privato)):
    lead = get_lead_by_id(lead_id)
    if not lead or lead["user_id"] != user["id"]:
        raise HTTPException(404, "Lead non trovato")
    update_lead(lead_id, **{k: v for k, v in body.dict().items() if v is not None})
    return {"message": "Aggiornato", "lead": public_lead(get_lead_by_id(lead_id), with_telefono=True)}


@router_priv.post("/lead/{lead_id}/marca-venduto")
def marca_venduto(lead_id: int, user=Depends(require_privato)):
    return _change_status(lead_id, user, "venduto")


@router_priv.post("/lead/{lead_id}/ritira")
def ritira(lead_id: int, user=Depends(require_privato)):
    return _change_status(lead_id, user, "ritirato")


def _change_status(lead_id: int, user: dict, new_status: str):
    lead = get_lead_by_id(lead_id)
    if not lead or lead["user_id"] != user["id"]:
        raise HTTPException(404, "Lead non trovato")
    update_lead(lead_id, status=new_status)
    return {"message": f"Status aggiornato a '{new_status}'"}


@router_priv.get("/me/contatti")
def my_contatti(user=Depends(require_privato)):
    lead = get_active_lead_by_user(user["id"])
    if not lead:
        return {"contatti": [], "lead_id": None}
    contatti = list_contatti_for_lead(lead["id"])
    return {"contatti": contatti, "lead_id": lead["id"]}


# ─── /api/agente/* ──────────────────────────────────────────────────────────

@router_agent.get("/lead-privati")
def lead_privati(provincia: Optional[str] = Query(None), user=Depends(require_paid)):
    """Lista lead attivi. Filtro provincia: query param > city dell'utente > tutte."""
    if not provincia:
        # Prova a derivare da user.city se è una provincia conosciuta
        city = (user.get("city") or "").strip()
        if any(p.lower() == city.lower() for p in PROVINCE):
            provincia = next(p for p in PROVINCE if p.lower() == city.lower())

    leads_raw = list_active_leads(provincia)
    contattati = list_contatti_set_for_agente(user["id"])

    out = []
    for l in leads_raw:
        # Non auto-mostrare il proprio annuncio se l'agente è anche privato
        if l["user_id"] == user["id"]:
            continue
        item = public_lead(l, with_telefono=False)
        item["already_contacted"] = l["id"] in contattati
        out.append(item)

    return {"leads": out, "filtro_provincia": provincia, "totale": len(out)}


@router_agent.post("/contatta-lead/{lead_id}")
def contatta_lead(lead_id: int, user=Depends(require_paid)):
    lead = get_lead_by_id(lead_id)
    if not lead or lead.get("status") != "attivo":
        raise HTTPException(404, "Lead non trovato o non attivo")
    if lead["user_id"] == user["id"]:
        raise HTTPException(400, "Non puoi contattare il tuo stesso annuncio")

    result = log_contatto(lead_id, user["id"])

    # Se primo contatto → notifica email al privato (best-effort)
    if not result.get("already_contacted"):
        try:
            privato = get_user_by_id(lead["user_id"])
            if privato:
                _send_privato_contattato_email(
                    privato_email=privato["email"],
                    privato_nome=privato.get("nome"),
                    indirizzo=lead.get("indirizzo", ""),
                    agente_nome=(user.get("nome") or user.get("email") or "Un agente"),
                    agente_citta=user.get("city") or "",
                )
        except Exception as e:
            print(f"[Contatta] notifica email errore: {e}")

    return {
        "telefono_privato":  lead.get("telefono_privato"),
        "already_contacted": result["already_contacted"],
        "message":           "Telefono ottenuto. Buon contatto!",
    }


# ─── Sprint 3: mini-stats + stima vendita probabile ─────────────────────────

@router_agent.get("/mini-stats")
def mini_stats(user=Depends(require_paid)):
    """4 contatori della top-bar dashboard."""
    from datetime import datetime, timedelta
    from database import get_conn as _gc, _cur as _gcur, _sql as _gsql
    from privato.db import list_active_leads as _list_lp

    today_iso = datetime.utcnow().date().isoformat()
    week_iso  = (datetime.utcnow() - timedelta(days=7)).isoformat()

    # Derivazione provincia agente
    city = (user.get("city") or "").strip()
    provincia_agente = city if any(p.lower() == city.lower() for p in PROVINCE) else None

    conn = _gc(); cur = _gcur(conn)

    # 1) Privati oggi (annunci scrapati con fonte='privato' inseriti oggi)
    cur.execute(_gsql("""
        SELECT COUNT(*) FROM annunci
        WHERE fonte = 'privato' AND data_inserimento >= ?
    """), (today_iso,))
    privati_oggi = cur.fetchone()[0] or 0

    # 2) Non in esclusiva totali (fonte='noescl')
    cur.execute(_gsql("SELECT COUNT(*) FROM annunci WHERE fonte = 'noescl'"))
    non_esclusiva = cur.fetchone()[0] or 0

    conn.close()

    # 3) Lead proprietari ultimi 7gg (filtra per provincia agente se nota)
    if provincia_agente:
        leads = [l for l in _list_lp(provincia_agente)
                 if l.get("created_at", "") >= week_iso]
    else:
        leads = [l for l in _list_lp() if l.get("created_at", "") >= week_iso]
    lead_proprietari_week = len(leads)

    return {
        "privati_oggi":          int(privati_oggi),
        "non_esclusiva":         int(non_esclusiva),
        "lead_proprietari_week": int(lead_proprietari_week),
        "messaggi_nuovi":        0,  # placeholder Sprint 4
        "provincia_agente":      provincia_agente,
    }


@router_agent.get("/stima/{annuncio_id}")
def stima_endpoint(annuncio_id: int, user=Depends(require_paid)):
    """Calcola stima vendita probabile per un annuncio."""
    from services.stima_service import calcola_stima, get_annuncio_by_id
    ann = get_annuncio_by_id(annuncio_id)
    if not ann:
        raise HTTPException(404, "Annuncio non trovato")
    return calcola_stima(ann)


@router_agent.get("/lead/{lead_id}")
def lead_detail(lead_id: int, user=Depends(require_paid)):
    """Dettaglio lead venditore + timeline contatti + stima vendita probabile."""
    from services.stima_service import calcola_stima

    lead = get_lead_by_id(lead_id)
    if not lead:
        raise HTTPException(404, "Lead non trovato")

    # Provincia gate (allineato con la route della pagina /lead/{id})
    user_city = (user.get("city") or "").strip()
    if any(p.lower() == user_city.lower() for p in PROVINCE):
        if (lead.get("provincia") or "").lower() != user_city.lower():
            raise HTTPException(403, "Lead non nella tua provincia")

    contattati = list_contatti_set_for_agente(user["id"])
    already_contacted = lead["id"] in contattati

    contatti_desc = list_contatti_for_lead(lead_id)
    # ASC = primo contatto in cima
    contatti_asc = list(reversed(contatti_desc))
    primo_agente_id = contatti_asc[0]["agente_id"] if contatti_asc else None

    stima = calcola_stima({
        "id":     None,
        "prezzo": lead.get("prezzo_richiesto"),
        "mq":     lead.get("mq"),
        "zona":   lead.get("citta"),
        "tipo":   lead.get("tipo_immobile"),
    })

    out = public_lead(lead, with_telefono=already_contacted)
    out["already_contacted"] = already_contacted
    out["contatti"]          = contatti_asc
    out["primo_agente_id"]   = primo_agente_id
    out["current_user_id"]   = user["id"]
    out["stima"]             = stima
    return out


# ─── Sprint 4 Task A: Script Chiamata AI ────────────────────────────────────

# Rate limit in-memory: { user_id: [unix_ts, ...] } — finestra 1h, max 10
_SCRIPT_RL_WINDOW = 3600
_SCRIPT_RL_MAX    = 10
_script_rl: dict  = {}
_script_rl_lock   = None


def _rate_limit_script(user_id: int) -> Optional[int]:
    """Ritorna None se ok, oppure i secondi di retry-after."""
    import time
    import threading
    global _script_rl_lock
    if _script_rl_lock is None:
        _script_rl_lock = threading.Lock()
    now = time.time()
    with _script_rl_lock:
        hist = [t for t in _script_rl.get(user_id, []) if now - t < _SCRIPT_RL_WINDOW]
        if len(hist) >= _SCRIPT_RL_MAX:
            retry = int(_SCRIPT_RL_WINDOW - (now - hist[0])) + 1
            _script_rl[user_id] = hist
            return max(1, retry)
        hist.append(now)
        _script_rl[user_id] = hist
        return None


def _log_script(agente_user_id: int, annuncio_id: int,
                tokens_input: int, tokens_output: int, costo_eur: float) -> None:
    from database import get_conn as _gc, _cur as _gcur, _sql as _gsql
    try:
        conn = _gc(); cur = _gcur(conn)
        cur.execute(_gsql("""
            INSERT INTO script_logs
                (agente_user_id, annuncio_id, tokens_input, tokens_output, costo_eur)
            VALUES (?, ?, ?, ?, ?)
        """), (agente_user_id, annuncio_id, tokens_input, tokens_output, costo_eur))
        conn.commit(); conn.close()
    except Exception as e:
        print(f"[script_logs] log errore: {e}")


@router_agent.post("/script/{annuncio_id}")
def script_chiamata_ai(annuncio_id: int, user=Depends(require_paid)):
    """
    Genera uno script chiamata di 30-45 secondi con Claude Sonnet 4.5.
    Rate limit: 10 generazioni/ora per agente.
    """
    retry_after = _rate_limit_script(user["id"])
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail=f"Hai raggiunto il limite di {_SCRIPT_RL_MAX} script/ora. "
                   f"Riprova tra {retry_after // 60} min.",
        )

    from services.ai_script import genera_script_chiamata, AIScriptError
    try:
        out = genera_script_chiamata(annuncio_id, user)
    except AIScriptError as e:
        msg = str(e)
        if "non trovato" in msg.lower():
            raise HTTPException(404, "Annuncio non trovato")
        # Errori Anthropic / configurazione → 503 con messaggio user-friendly
        print(f"[script-ai] errore: {msg}")
        raise HTTPException(
            status_code=503,
            detail="Servizio AI temporaneamente non disponibile. Riprova tra qualche minuto.",
        )

    _log_script(
        agente_user_id = user["id"],
        annuncio_id    = annuncio_id,
        tokens_input   = out["tokens_input"],
        tokens_output  = out["tokens_output"],
        costo_eur      = out["costo_eur"],
    )

    return {"script": out["script"]}


# ─── Email helper inline (sfrutta wrapper di services.email) ────────────────

def _send_privato_contattato_email(privato_email: str, privato_nome: Optional[str],
                                   indirizzo: str, agente_nome: str, agente_citta: str) -> bool:
    saluto = f"Ciao {privato_nome}," if privato_nome else "Ciao,"
    body = f"""
<h2 style="margin:0 0 18px;font-size:22px;font-weight:700">Un agente ti ha cercato 🏠</h2>
<p>{saluto}</p>
<p><strong>{agente_nome}</strong>{(' da <strong>' + agente_citta + '</strong>') if agente_citta else ''}
ha mostrato interesse per la tua casa in <strong>{indirizzo or '(indirizzo non specificato)'}</strong>.</p>
<p>Probabilmente ti contatterà a breve via WhatsApp o telefono.</p>
{_btn("https://houseradar.it/privato/dashboard", "Apri la tua dashboard")}
<p style="font-size:13px;color:#666">
  Per qualsiasi domanda, accedi al tuo account HouseRadar.
</p>"""
    return _send(privato_email, "Un agente ti ha cercato per la tua casa 🏠", _wrap(body, "Un agente ti ha cercato"))
