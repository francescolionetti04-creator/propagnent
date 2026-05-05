"""Auth API: signup, login, logout, verify, forgot/reset password, me."""

import os
import re
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, RedirectResponse
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, constr, validator

from .jwt_utils import issue_token, cookie_kwargs, SESSION_COOKIE
from .users_db import (
    create_user, get_user_by_email, get_user_by_id,
    get_user_by_verification_token, get_user_by_reset_token,
    verify_email, set_password_reset, reset_password as do_reset_password,
    public_user, VALID_ROLES,
)

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.email import send_verification_email, send_password_reset_email, send_welcome_email


router = APIRouter(prefix="/auth", tags=["auth"])
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://houseradar.it").rstrip("/")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ─── Pydantic schemas ───────────────────────────────────────────────────────

class SignupBody(BaseModel):
    email: str
    password: constr(min_length=8, max_length=128)
    nome:     str | None = None
    cognome:  str | None = None
    telefono: str | None = None
    role:     str
    city:     str | None = None

    @validator("email")
    def _v_email(cls, v):
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Email non valida")
        return v

    @validator("role")
    def _v_role(cls, v):
        if v not in VALID_ROLES:
            raise ValueError(f"Role deve essere uno di: {VALID_ROLES}")
        return v


class LoginBody(BaseModel):
    email: str
    password: str


class ForgotBody(BaseModel):
    email: str


class ResetBody(BaseModel):
    token: str
    new_password: constr(min_length=8, max_length=128)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _hash(pw: str) -> str:
    return pwd.hash(pw)


def _verify(pw: str, hashed: str) -> bool:
    try:
        return pwd.verify(pw, hashed)
    except Exception:
        return False


# ─── Routes ─────────────────────────────────────────────────────────────────

@router.post("/signup")
def signup(body: SignupBody):
    if get_user_by_email(body.email):
        raise HTTPException(status_code=409, detail="Email già registrata")
    try:
        user = create_user(
            email=body.email,
            password_hash=_hash(body.password),
            nome=body.nome,
            cognome=body.cognome,
            telefono=body.telefono,
            role=body.role,
            city=body.city,
            is_founder=False,
            is_email_verified=False,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Invia email verifica (best-effort)
    try:
        token = user["email_verification_token"]
        link  = f"{APP_BASE_URL}/auth/verify?token={token}"
        send_verification_email(user["email"], link, nome=user.get("nome"))
    except Exception as e:
        print(f"[Signup] Email verifica errore: {e}")

    return {
        "user_id": user["id"],
        "email":   user["email"],
        "message": "Registrazione riuscita. Controlla la tua email per verificare l'account.",
    }


@router.post("/login")
def login(body: LoginBody, response: JSONResponse = None):
    user = get_user_by_email(body.email)
    if not user or not _verify(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email o password non corretti")
    if not bool(user.get("is_email_verified")) and not bool(user.get("is_founder")):
        raise HTTPException(status_code=403, detail="Verifica prima la tua email")

    token = issue_token(user["id"])
    resp = JSONResponse({
        "user":    public_user(user),
        "message": "Login riuscito",
    })
    resp.set_cookie(value=token, **cookie_kwargs())
    return resp


@router.post("/logout")
def logout():
    resp = JSONResponse({"message": "Logout riuscito"})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@router.get("/verify")
def verify(token: str):
    user = get_user_by_verification_token(token)
    if not user:
        return RedirectResponse(url="/accedi?verified=0", status_code=303)
    verify_email(user["id"])
    # Welcome email best-effort
    try:
        send_welcome_email(user["email"], user["role"], nome=user.get("nome"))
    except Exception as e:
        print(f"[Verify] Welcome email errore: {e}")
    return RedirectResponse(url="/accedi?verified=1", status_code=303)


@router.post("/forgot-password")
def forgot_password(body: ForgotBody):
    user = get_user_by_email(body.email)
    if user:
        token = str(uuid.uuid4())
        expires = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        set_password_reset(user["id"], token, expires)
        try:
            link = f"{APP_BASE_URL}/reset-password?token={token}"
            send_password_reset_email(user["email"], link, nome=user.get("nome"))
        except Exception as e:
            print(f"[Forgot] Email errore: {e}")
    # Risposta sempre identica per evitare enumeration
    return {"message": "Se l'email esiste, ti abbiamo inviato un link"}


@router.post("/reset-password")
def reset_password(body: ResetBody):
    user = get_user_by_reset_token(body.token)
    if not user:
        raise HTTPException(status_code=400, detail="Token non valido o scaduto")
    do_reset_password(user["id"], _hash(body.new_password))
    return {"message": "Password aggiornata. Ora puoi accedere."}


@router.get("/me")
def me(request: Request):
    from .dependencies import current_user
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Non autenticato")
    return public_user(user)
