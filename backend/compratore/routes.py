"""API compratore."""

import os
import sys
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, validator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from auth.dependencies import require_compratore

from .db import (
    create_lead, get_active_lead_by_user, get_lead_by_id, update_lead,
    get_match_for_user, public_lead,
    PROVINCE, VALID_TIPI, VALID_URGENZE,
)


router = APIRouter(prefix="/api/compratore", tags=["compratore"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class LeadIn(BaseModel):
    province_interesse: List[str]
    zona_libera:        Optional[str] = None
    tipo_immobile:      Optional[List[str]] = None
    mq_min:             Optional[int] = None
    mq_max:             Optional[int] = None
    camere_min:         Optional[int] = None
    prezzo_min:         Optional[int] = None
    prezzo_max:         Optional[int] = None
    urgenza:            str = "media"
    note_aggiuntive:    Optional[str] = None
    email_match_attivo: bool = True

    @validator("province_interesse")
    def _v_prov(cls, v):
        if not v:
            raise ValueError("Almeno una provincia richiesta")
        for p in v:
            if p not in PROVINCE:
                raise ValueError(f"Provincia non valida: {p}")
        return v

    @validator("tipo_immobile")
    def _v_tipi(cls, v):
        if v is None:
            return v
        out = []
        for t in v:
            t2 = (t or "").lower()
            if t2 not in VALID_TIPI:
                raise ValueError(f"tipo_immobile non valido: {t}")
            out.append(t2)
        return out

    @validator("urgenza")
    def _v_urg(cls, v):
        v = (v or "media").lower()
        if v not in VALID_URGENZE:
            raise ValueError(f"urgenza deve essere una di: {VALID_URGENZE}")
        return v


class LeadUpdate(BaseModel):
    province_interesse: Optional[List[str]] = None
    zona_libera:        Optional[str] = None
    tipo_immobile:      Optional[List[str]] = None
    mq_min:             Optional[int] = None
    mq_max:             Optional[int] = None
    camere_min:         Optional[int] = None
    prezzo_min:         Optional[int] = None
    prezzo_max:         Optional[int] = None
    urgenza:            Optional[str] = None
    note_aggiuntive:    Optional[str] = None
    email_match_attivo: Optional[bool] = None


class EmailToggleBody(BaseModel):
    email_match_attivo: bool


# ─── Routes ─────────────────────────────────────────────────────────────────

@router.post("/lead")
def create_lead_route(body: LeadIn, user=Depends(require_compratore)):
    lead = create_lead(user["id"], **body.dict())
    return {"lead_id": lead["id"], "message": "Preferenze salvate", "lead": public_lead(lead)}


@router.get("/me/lead")
def my_lead(user=Depends(require_compratore)):
    lead = get_active_lead_by_user(user["id"])
    return {"lead": public_lead(lead)}


@router.put("/lead/{lead_id}")
def update_lead_route(lead_id: int, body: LeadUpdate, user=Depends(require_compratore)):
    lead = get_lead_by_id(lead_id)
    if not lead or lead["user_id"] != user["id"]:
        raise HTTPException(404, "Preferenze non trovate")
    update_lead(lead_id, **{k: v for k, v in body.dict().items() if v is not None})
    return {"message": "Aggiornato", "lead": public_lead(get_lead_by_id(lead_id))}


@router.post("/lead/{lead_id}/sospendi")
def sospendi(lead_id: int, user=Depends(require_compratore)):
    return _change_status(lead_id, user, "sospeso")


@router.post("/lead/{lead_id}/riattiva")
def riattiva(lead_id: int, user=Depends(require_compratore)):
    return _change_status(lead_id, user, "attivo")


def _change_status(lead_id: int, user: dict, new_status: str):
    lead = get_lead_by_id(lead_id)
    if not lead or lead["user_id"] != user["id"]:
        raise HTTPException(404, "Preferenze non trovate")
    update_lead(lead_id, status=new_status)
    return {"message": f"Status aggiornato a '{new_status}'"}


@router.get("/me/match")
def my_matches(user=Depends(require_compratore)):
    matches = get_match_for_user(user["id"], limit=50)
    return {"matches": matches, "totale": len(matches)}


@router.put("/lead/{lead_id}/email-toggle")
def email_toggle(lead_id: int, body: EmailToggleBody, user=Depends(require_compratore)):
    lead = get_lead_by_id(lead_id)
    if not lead or lead["user_id"] != user["id"]:
        raise HTTPException(404, "Preferenze non trovate")
    update_lead(lead_id, email_match_attivo=body.email_match_attivo)
    return {"message": "Aggiornato", "email_match_attivo": body.email_match_attivo}
