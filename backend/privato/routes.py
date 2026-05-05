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
