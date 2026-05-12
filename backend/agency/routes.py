"""API agenzia: inviti, member, accept signup invito.

Endpoints:
  POST   /api/agency/invite                 — owner invita via email
  GET    /api/agency/members                — owner: lista members + inviti pendenti + counters
  DELETE /api/agency/member/{user_id}       — owner: soft-delete membro (+ aggiorna Stripe seat)
  POST   /api/agency/invite/{token}/resend  — owner: reinvio email invito
  DELETE /api/agency/invite/{id}            — owner: annulla invito pendente
  GET    /api/agency/invite/{token}         — pubblico: verifica validità invito
  POST   /auth/signup-invite                — pubblico: signup tramite invito (auto-login)
"""

import os
import re
import sys
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, constr, validator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from auth.dependencies import require_paid, require_auth
from auth.users_db import (
    create_user, get_user_by_email, get_user_by_id, public_user,
)
from auth.passwords import hash_password
from auth.jwt_utils import issue_token, cookie_kwargs

from services.email import send_agency_invite_email, send_welcome_email
from services.stripe_svc import report_seat_usage

from .db import (
    get_agency_by_owner, get_member_agency,
    create_invite, get_invite_by_token, is_invite_valid,
    list_pending_invites, mark_invite_accepted, cancel_invite,
    list_active_members, count_active_members,
    upsert_member, soft_delete_member, is_owner,
    public_member, public_invite,
    DEFAULT_MAX_INCLUSI,
)


router = APIRouter(prefix="/api/agency", tags=["agency"])
auth_router = APIRouter(prefix="/auth", tags=["auth"])  # /auth/signup-invite

APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://houseradar.it").rstrip("/")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ─── Schemas ────────────────────────────────────────────────────────────────

class InviteIn(BaseModel):
    email: str
    nome:  Optional[str] = None

    @validator("email")
    def _v_email(cls, v):
        v = (v or "").strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Email non valida")
        return v


class SignupInviteIn(BaseModel):
    token:    str
    password: constr(min_length=8, max_length=128)
    nome:     Optional[str] = None
    cognome:  Optional[str] = None
    telefono: Optional[str] = None
    city:     Optional[str] = None


# ─── Helpers ────────────────────────────────────────────────────────────────

def _require_owner(user) -> dict:
    """Restituisce l'agency se l'utente è owner, altrimenti 403."""
    agency = get_agency_by_owner(user["id"])
    if not agency:
        raise HTTPException(status_code=403,
                            detail="Solo il titolare dell'agenzia può gestire i membri")
    return agency


def _sync_seat_usage(agency: dict) -> int:
    """Recalcola seat extra correnti e li riporta a Stripe. Ritorna extras."""
    n_attivi = count_active_members(agency["id"])
    inclusi  = int(agency.get("max_account_inclusi") or DEFAULT_MAX_INCLUSI)
    extras   = max(0, n_attivi - inclusi)
    seat_id  = agency.get("stripe_seat_item_id")
    if seat_id:
        report_seat_usage(seat_id, extras)
    return extras


def _send_invite_email(invite: dict, agency: dict, owner: dict) -> None:
    link = f"{APP_BASE_URL}/signup/invito/{invite['invite_token']}"
    owner_name = " ".join(filter(None, [
        owner.get("nome"), owner.get("cognome")
    ])).strip() or owner.get("email")
    try:
        send_agency_invite_email(
            to=invite["email_invitato"],
            link=link,
            agency_name=agency.get("nome_agenzia") or "HouseRadar Agenzia",
            owner_name=owner_name,
            invitee_name=invite.get("nome_invitato"),
        )
    except Exception as e:
        print(f"[Agency invite] email errore: {e}")


# ─── /api/agency/* (owner only, eccetto /invite/{token}) ────────────────────

@router.post("/invite")
def invite_member(body: InviteIn, user=Depends(require_paid)):
    agency = _require_owner(user)
    # Se l'email è già member attivo, errore
    existing_user = get_user_by_email(body.email)
    if existing_user:
        member = get_member_agency(existing_user["id"])
        if member and member["id"] == agency["id"]:
            raise HTTPException(status_code=409,
                                detail="Questo utente è già membro della tua agenzia")
        if existing_user["role"] in ("privato", "compratore"):
            raise HTTPException(status_code=400,
                                detail="Questo utente ha un account non-agente — chiedigli di registrarsi come agente")
    invite = create_invite(agency["id"], body.email, nome_invitato=body.nome)
    _send_invite_email(invite, agency, user)
    return {
        "invite_id":  invite["id"],
        "email":      invite["email_invitato"],
        "expires_at": invite["expires_at"],
    }


@router.get("/members")
def list_members(user=Depends(require_paid)):
    agency = _require_owner(user)
    members = list_active_members(agency["id"])
    invites = list_pending_invites(agency["id"])
    inclusi = int(agency.get("max_account_inclusi") or DEFAULT_MAX_INCLUSI)
    n_attivi = len(members)
    extras = max(0, n_attivi - inclusi)
    return {
        "agency": {
            "id":                  agency["id"],
            "nome_agenzia":        agency.get("nome_agenzia"),
            "piano":               agency.get("piano"),
            "max_account_inclusi": inclusi,
        },
        "counters": {
            "attivi":          n_attivi,
            "inclusi":         inclusi,
            "extras":          extras,
            "extras_eur_mese": extras * 100,
            "inviti_pendenti": len(invites),
        },
        "members": [public_member(m) for m in members],
        "invites": [public_invite(i) for i in invites],
    }


@router.delete("/member/{user_id}")
def remove_member(user_id: int, user=Depends(require_paid)):
    agency = _require_owner(user)
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Non puoi rimuovere te stesso")
    ok = soft_delete_member(agency["id"], user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Membro non trovato")
    _sync_seat_usage(agency)
    return {"ok": True}


@router.delete("/invite/{invite_id}")
def cancel_pending_invite(invite_id: int, user=Depends(require_paid)):
    agency = _require_owner(user)
    ok = cancel_invite(invite_id, agency["id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Invito non trovato")
    return {"ok": True}


@router.post("/invite/{token}/resend")
def resend_invite(token: str, user=Depends(require_paid)):
    agency = _require_owner(user)
    inv = get_invite_by_token(token)
    if not inv or inv["agency_id"] != agency["id"]:
        raise HTTPException(status_code=404, detail="Invito non trovato")
    if inv.get("accepted_at") or inv.get("cancelled_at"):
        raise HTTPException(status_code=400, detail="Invito già completato o annullato")
    _send_invite_email(inv, agency, user)
    return {"ok": True}


@router.get("/invite/{token}")
def get_invite_public(token: str):
    """Endpoint pubblico — usato dalla pagina /signup/invito/{token}."""
    inv = get_invite_by_token(token)
    if not is_invite_valid(inv):
        raise HTTPException(status_code=404, detail="Invito non valido o scaduto")
    from .db import get_agency_by_id
    agency = get_agency_by_id(inv["agency_id"])
    owner = get_user_by_id(agency["owner_user_id"]) if agency else None
    owner_name = " ".join(filter(None, [
        (owner or {}).get("nome"), (owner or {}).get("cognome")
    ])).strip() or (owner or {}).get("email")
    return {
        "email":          inv["email_invitato"],
        "nome":           inv.get("nome_invitato"),
        "agency_name":    (agency or {}).get("nome_agenzia") or "HouseRadar Agenzia",
        "owner_name":     owner_name,
        "expires_at":     inv["expires_at"],
    }


# ─── /auth/signup-invite ────────────────────────────────────────────────────

@auth_router.post("/signup-invite")
def signup_invite(body: SignupInviteIn):
    inv = get_invite_by_token(body.token)
    if not is_invite_valid(inv):
        raise HTTPException(status_code=400, detail="Invito non valido o scaduto")

    from .db import get_agency_by_id
    agency = get_agency_by_id(inv["agency_id"])
    if not agency:
        raise HTTPException(status_code=400, detail="Agenzia non trovata")

    email = inv["email_invitato"]
    if get_user_by_email(email):
        raise HTTPException(status_code=409,
                            detail="Email già registrata — accedi e contatta il titolare")

    try:
        user = create_user(
            email=email,
            password_hash=hash_password(body.password),
            nome=body.nome or inv.get("nome_invitato"),
            cognome=body.cognome,
            telefono=body.telefono,
            role="agente",
            city=body.city,
            is_founder=False,
            is_email_verified=True,  # email già verificata dall'invito
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    upsert_member(agency["id"], user["id"], ruolo="agent")
    mark_invite_accepted(inv["id"], user["id"])
    _sync_seat_usage(agency)

    # Welcome email best-effort
    try:
        send_welcome_email(user["email"], "agente", nome=user.get("nome"))
    except Exception as e:
        print(f"[Signup invite] welcome email: {e}")

    # Auto-login
    jwt_token = issue_token(user["id"])
    resp = JSONResponse({
        "user":     public_user(user),
        "redirect": "/app",
        "message":  "Account creato e collegato all'agenzia",
    })
    resp.set_cookie(value=jwt_token, **cookie_kwargs())
    return resp
