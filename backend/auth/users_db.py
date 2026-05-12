"""
HouseRadar — User CRUD su DB raw (psycopg2/sqlite3).
Niente ORM: usiamo lo stesso pattern del resto del progetto.
"""

import os
import sys
import uuid
from datetime import datetime, timedelta
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_conn, _cur, _sql, _to_dict


VALID_ROLES = ("privato", "compratore", "agente", "consulente")


def _now() -> str:
    return datetime.utcnow().isoformat()


# ─── CREATE ──────────────────────────────────────────────────────────────────

def create_user(
    email: str,
    password_hash: str,
    role: str,
    nome: Optional[str] = None,
    cognome: Optional[str] = None,
    telefono: Optional[str] = None,
    city: Optional[str] = None,
    is_founder: bool = False,
    is_email_verified: bool = False,
) -> dict:
    """Crea un nuovo utente. Solleva ValueError se email esiste o role non valido."""
    if role not in VALID_ROLES:
        raise ValueError(f"Role non valido: {role}")
    email = email.strip().lower()

    if get_user_by_email(email):
        raise ValueError("Email già registrata")

    token = str(uuid.uuid4())
    now = _now()

    conn = get_conn()
    cur = _cur(conn)
    cur.execute(_sql("""
        INSERT INTO users (
            email, password_hash, nome, cognome, telefono, role, city,
            is_founder, is_email_verified, email_verification_token,
            subscription_status, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """), (
        email, password_hash, nome, cognome, telefono, role, city,
        1 if is_founder else 0,
        1 if is_email_verified else 0,
        None if is_email_verified else token,
        "none",
        now, now,
    ))
    conn.commit()
    conn.close()
    return get_user_by_email(email)


# ─── READ ────────────────────────────────────────────────────────────────────

def get_user_by_email(email: str) -> Optional[dict]:
    conn = get_conn()
    cur = _cur(conn)
    cur.execute(_sql("SELECT * FROM users WHERE email = ?"), (email.strip().lower(),))
    row = cur.fetchone()
    conn.close()
    return _to_dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[dict]:
    conn = get_conn()
    cur = _cur(conn)
    cur.execute(_sql("SELECT * FROM users WHERE id = ?"), (user_id,))
    row = cur.fetchone()
    conn.close()
    return _to_dict(row) if row else None


def get_user_by_verification_token(token: str) -> Optional[dict]:
    conn = get_conn()
    cur = _cur(conn)
    cur.execute(_sql("SELECT * FROM users WHERE email_verification_token = ?"), (token,))
    row = cur.fetchone()
    conn.close()
    return _to_dict(row) if row else None


def get_user_by_reset_token(token: str) -> Optional[dict]:
    """Ritorna l'utente solo se token valido E non scaduto."""
    conn = get_conn()
    cur = _cur(conn)
    cur.execute(_sql("""
        SELECT * FROM users
        WHERE password_reset_token = ?
          AND password_reset_expires > ?
    """), (token, _now()))
    row = cur.fetchone()
    conn.close()
    return _to_dict(row) if row else None


def count_users() -> int:
    conn = get_conn()
    cur = _cur(conn)
    cur.execute("SELECT COUNT(*) FROM users")
    n = cur.fetchone()[0]
    conn.close()
    return int(n)


# ─── UPDATE ──────────────────────────────────────────────────────────────────

def _update(user_id: int, **fields):
    if not fields:
        return
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields.keys())
    conn = get_conn()
    cur = _cur(conn)
    cur.execute(_sql(f"UPDATE users SET {cols} WHERE id = ?"), (*fields.values(), user_id))
    conn.commit()
    conn.close()


def verify_email(user_id: int):
    _update(user_id, is_email_verified=1, email_verification_token=None)


def set_password_reset(user_id: int, token: str, expires_iso: str):
    _update(user_id, password_reset_token=token, password_reset_expires=expires_iso)


def reset_password(user_id: int, new_password_hash: str):
    _update(user_id,
            password_hash=new_password_hash,
            password_reset_token=None,
            password_reset_expires=None)


def set_stripe_customer(user_id: int, customer_id: str):
    _update(user_id, stripe_customer_id=customer_id)


def set_subscription(
    user_id: int,
    subscription_id: Optional[str] = None,
    status: Optional[str] = None,
    trial_ends_at: Optional[str] = None,
    customer_id: Optional[str] = None,
):
    fields = {}
    if subscription_id is not None: fields["stripe_subscription_id"] = subscription_id
    if status is not None:          fields["subscription_status"]    = status
    if trial_ends_at is not None:   fields["trial_ends_at"]          = trial_ends_at
    if customer_id is not None:     fields["stripe_customer_id"]     = customer_id
    if fields:
        _update(user_id, **fields)


def set_bio_pubblica(user_id: int, bio: Optional[str]):
    """Aggiorna bio_pubblica (max 200 char). None = cancella."""
    if bio is not None:
        bio = str(bio).strip()[:200] or None
    _update(user_id, bio_pubblica=bio)


def find_user_by_stripe_customer(customer_id: str) -> Optional[dict]:
    conn = get_conn()
    cur = _cur(conn)
    cur.execute(_sql("SELECT * FROM users WHERE stripe_customer_id = ?"), (customer_id,))
    row = cur.fetchone()
    conn.close()
    return _to_dict(row) if row else None


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def public_user(u: Optional[dict]) -> Optional[dict]:
    """Versione safe per il frontend (no password_hash, no token)."""
    if not u:
        return None
    return {
        "id":                  u["id"],
        "email":               u["email"],
        "nome":                u.get("nome"),
        "cognome":             u.get("cognome"),
        "telefono":            u.get("telefono"),
        "role":                u["role"],
        "city":                u.get("city"),
        "is_founder":          bool(u.get("is_founder")),
        "is_email_verified":   bool(u.get("is_email_verified")),
        "subscription_status": u.get("subscription_status") or "none",
        "trial_ends_at":       u.get("trial_ends_at"),
        "tutorial_visto":      bool(u.get("tutorial_visto")),
        "bio_pubblica":        u.get("bio_pubblica"),
    }


def has_paid_access(u: dict) -> bool:
    """True se founder o subscription attiva/in trial."""
    if not u:
        return False
    if bool(u.get("is_founder")):
        return True
    return (u.get("subscription_status") or "none") in ("trialing", "active")
