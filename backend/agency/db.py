"""CRUD agencies + agency_members + agency_invites — raw SQL."""

import os
import sys
import uuid
from datetime import datetime, timedelta
from typing import Optional, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_conn, _cur, _sql, _to_dict


INVITE_TTL_DAYS = 14
DEFAULT_MAX_INCLUSI = 3


def _now() -> str:
    return datetime.utcnow().isoformat()


def _expiry(days: int = INVITE_TTL_DAYS) -> str:
    return (datetime.utcnow() + timedelta(days=days)).isoformat()


# ─── agencies ────────────────────────────────────────────────────────────────

def create_agency(
    owner_user_id: int,
    nome_agenzia: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
    stripe_seat_item_id: Optional[str] = None,
    piano: str = "agenzia",
    max_account_inclusi: int = DEFAULT_MAX_INCLUSI,
) -> dict:
    now = _now()
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        INSERT INTO agencies (
            owner_user_id, nome_agenzia, piano, max_account_inclusi,
            stripe_subscription_id, stripe_seat_item_id, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?)
    """), (
        owner_user_id, nome_agenzia, piano, max_account_inclusi,
        stripe_subscription_id, stripe_seat_item_id, now, now,
    ))
    conn.commit()
    cur.execute(_sql("""
        SELECT * FROM agencies WHERE owner_user_id = ? ORDER BY id DESC LIMIT 1
    """), (owner_user_id,))
    row = cur.fetchone(); conn.close()
    agency = _to_dict(row) if row else {}
    # L'owner è automaticamente il primo member
    if agency:
        upsert_member(agency["id"], owner_user_id, ruolo="owner")
    return agency


def get_agency_by_id(agency_id: int) -> Optional[dict]:
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("SELECT * FROM agencies WHERE id = ?"), (agency_id,))
    row = cur.fetchone(); conn.close()
    return _to_dict(row) if row else None


def get_agency_by_owner(owner_user_id: int) -> Optional[dict]:
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        SELECT * FROM agencies
        WHERE owner_user_id = ?
        ORDER BY id DESC LIMIT 1
    """), (owner_user_id,))
    row = cur.fetchone(); conn.close()
    return _to_dict(row) if row else None


def get_agency_by_subscription(sub_id: str) -> Optional[dict]:
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("SELECT * FROM agencies WHERE stripe_subscription_id = ?"),
                (sub_id,))
    row = cur.fetchone(); conn.close()
    return _to_dict(row) if row else None


def update_agency(agency_id: int, **fields):
    if not fields:
        return
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields.keys())
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql(f"UPDATE agencies SET {cols} WHERE id = ?"),
                (*fields.values(), agency_id))
    conn.commit(); conn.close()


# ─── agency_members ──────────────────────────────────────────────────────────

def upsert_member(agency_id: int, user_id: int, ruolo: str = "agent") -> dict:
    """Inserisce o riattiva un member (idempotente)."""
    now = _now()
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        SELECT * FROM agency_members WHERE agency_id = ? AND user_id = ?
    """), (agency_id, user_id))
    row = cur.fetchone()
    if row:
        existing = _to_dict(row)
        # Se era stato rimosso, riattiva
        cur.execute(_sql("""
            UPDATE agency_members SET removed_at = NULL, accepted_at = ?
            WHERE id = ?
        """), (now, existing["id"]))
        conn.commit(); conn.close()
        return get_member(agency_id, user_id)
    cur.execute(_sql("""
        INSERT INTO agency_members
            (agency_id, user_id, ruolo_in_agenzia, invited_at, accepted_at)
        VALUES (?,?,?,?,?)
    """), (agency_id, user_id, ruolo, now, now))
    conn.commit(); conn.close()
    return get_member(agency_id, user_id)


def get_member(agency_id: int, user_id: int) -> Optional[dict]:
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        SELECT * FROM agency_members WHERE agency_id = ? AND user_id = ?
    """), (agency_id, user_id))
    row = cur.fetchone(); conn.close()
    return _to_dict(row) if row else None


def soft_delete_member(agency_id: int, user_id: int) -> bool:
    """Marca un member come rimosso. Ritorna False se non trovato."""
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        UPDATE agency_members SET removed_at = ?
        WHERE agency_id = ? AND user_id = ? AND removed_at IS NULL
    """), (_now(), agency_id, user_id))
    affected = cur.rowcount
    conn.commit(); conn.close()
    return affected > 0


def list_active_members(agency_id: int) -> List[dict]:
    """Members attivi (removed_at IS NULL) con info user."""
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        SELECT m.id, m.agency_id, m.user_id, m.ruolo_in_agenzia,
               m.invited_at, m.accepted_at, m.removed_at,
               u.email AS user_email, u.nome AS user_nome,
               u.cognome AS user_cognome, u.role AS user_role,
               u.city AS user_city, u.is_founder AS user_is_founder
        FROM agency_members m
        JOIN users u ON u.id = m.user_id
        WHERE m.agency_id = ? AND m.removed_at IS NULL
        ORDER BY m.ruolo_in_agenzia = 'owner' DESC, m.accepted_at ASC
    """), (agency_id,))
    rows = [_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def count_active_members(agency_id: int) -> int:
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        SELECT COUNT(*) FROM agency_members
        WHERE agency_id = ? AND removed_at IS NULL
    """), (agency_id,))
    n = cur.fetchone()[0]
    conn.close()
    return int(n)


def get_member_agency(user_id: int) -> Optional[dict]:
    """Ritorna l'agency a cui l'utente appartiene (member attivo)."""
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        SELECT a.* FROM agencies a
        JOIN agency_members m ON m.agency_id = a.id
        WHERE m.user_id = ? AND m.removed_at IS NULL
        ORDER BY m.id DESC LIMIT 1
    """), (user_id,))
    row = cur.fetchone(); conn.close()
    return _to_dict(row) if row else None


# ─── agency_invites ──────────────────────────────────────────────────────────

def create_invite(
    agency_id: int,
    email_invitato: str,
    nome_invitato: Optional[str] = None,
) -> dict:
    token = uuid.uuid4().hex
    now = _now()
    expires = _expiry()
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        INSERT INTO agency_invites
            (agency_id, invite_token, email_invitato, nome_invitato,
             invited_at, expires_at)
        VALUES (?,?,?,?,?,?)
    """), (agency_id, token, email_invitato.strip().lower(), nome_invitato,
           now, expires))
    conn.commit()
    cur.execute(_sql("SELECT * FROM agency_invites WHERE invite_token = ?"),
                (token,))
    row = cur.fetchone(); conn.close()
    return _to_dict(row) if row else {}


def get_invite_by_token(token: str) -> Optional[dict]:
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("SELECT * FROM agency_invites WHERE invite_token = ?"),
                (token,))
    row = cur.fetchone(); conn.close()
    return _to_dict(row) if row else None


def is_invite_valid(invite: dict) -> bool:
    if not invite:
        return False
    if invite.get("accepted_at"):
        return False
    if invite.get("cancelled_at"):
        return False
    try:
        expires = datetime.fromisoformat(invite["expires_at"])
        return datetime.utcnow() < expires
    except Exception:
        return False


def list_pending_invites(agency_id: int) -> List[dict]:
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        SELECT * FROM agency_invites
        WHERE agency_id = ?
          AND accepted_at IS NULL
          AND cancelled_at IS NULL
          AND expires_at > ?
        ORDER BY invited_at DESC
    """), (agency_id, _now()))
    rows = [_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def mark_invite_accepted(invite_id: int, user_id: int):
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        UPDATE agency_invites
        SET accepted_at = ?, accepted_by_user_id = ?
        WHERE id = ?
    """), (_now(), user_id, invite_id))
    conn.commit(); conn.close()


def cancel_invite(invite_id: int, agency_id: int) -> bool:
    """Solo se l'invito appartiene all'agency richiedente."""
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        UPDATE agency_invites SET cancelled_at = ?
        WHERE id = ? AND agency_id = ? AND accepted_at IS NULL
    """), (_now(), invite_id, agency_id))
    affected = cur.rowcount
    conn.commit(); conn.close()
    return affected > 0


# ─── Helpers ─────────────────────────────────────────────────────────────────

def is_owner(user_id: int, agency: Optional[dict] = None) -> bool:
    if not agency:
        agency = get_agency_by_owner(user_id)
    return bool(agency) and agency.get("owner_user_id") == user_id


def public_member(m: dict) -> dict:
    """Versione safe per il frontend."""
    return {
        "user_id":          m.get("user_id"),
        "email":            m.get("user_email"),
        "nome":             m.get("user_nome"),
        "cognome":          m.get("user_cognome"),
        "role":             m.get("user_role"),
        "city":             m.get("user_city"),
        "ruolo_in_agenzia": m.get("ruolo_in_agenzia"),
        "accepted_at":      m.get("accepted_at"),
        "is_founder":       bool(m.get("user_is_founder")),
    }


def public_invite(i: dict) -> dict:
    return {
        "id":             i.get("id"),
        "email":          i.get("email_invitato"),
        "nome":           i.get("nome_invitato"),
        "invited_at":     i.get("invited_at"),
        "expires_at":     i.get("expires_at"),
    }
