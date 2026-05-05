"""CRUD lead_venditori + lead_contatti — raw SQL via database._sql()."""

import os
import sys
from datetime import datetime
from typing import Optional, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_conn, _cur, _sql, _to_dict


VALID_TIPI    = ("appartamento", "villa", "attico", "loft", "monolocale", "altro")
VALID_URGENZE = ("alta", "media", "bassa")
VALID_STATUS  = ("attivo", "venduto", "ritirato")

PROVINCE = (
    "Livorno", "Pisa", "Firenze", "Siena", "Arezzo",
    "Lucca", "Grosseto", "Pistoia", "Prato", "Massa-Carrara",
)


def _now() -> str:
    return datetime.utcnow().isoformat()


# ─── lead_venditori ──────────────────────────────────────────────────────────

def create_lead(user_id: int, **fields) -> dict:
    """Inserisce un lead_venditore. Ritorna il record creato."""
    now = _now()
    cols = [
        "user_id", "indirizzo", "citta", "provincia", "tipo_immobile",
        "mq", "camere", "bagni", "prezzo_richiesto", "descrizione",
        "urgenza", "telefono_privato", "foto_url", "status",
        "created_at", "updated_at",
    ]
    vals = [
        user_id,
        fields.get("indirizzo"),
        fields.get("citta"),
        fields.get("provincia"),
        fields.get("tipo_immobile"),
        fields.get("mq"),
        fields.get("camere"),
        fields.get("bagni"),
        fields.get("prezzo_richiesto"),
        fields.get("descrizione"),
        fields.get("urgenza", "media"),
        fields.get("telefono_privato"),
        fields.get("foto_url"),
        fields.get("status", "attivo"),
        now, now,
    ]
    placeholders = ",".join(["?"] * len(cols))
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql(f"INSERT INTO lead_venditori ({', '.join(cols)}) VALUES ({placeholders})"), vals)
    conn.commit()
    # Recupera l'ultimo lead creato per quel user
    cur.execute(_sql("""
        SELECT * FROM lead_venditori
        WHERE user_id = ?
        ORDER BY id DESC LIMIT 1
    """), (user_id,))
    row = cur.fetchone()
    conn.close()
    return _to_dict(row) if row else {}


def get_active_lead_by_user(user_id: int) -> Optional[dict]:
    """Ritorna il lead più recente con status='attivo' del privato."""
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        SELECT * FROM lead_venditori
        WHERE user_id = ? AND status = 'attivo'
        ORDER BY id DESC LIMIT 1
    """), (user_id,))
    row = cur.fetchone()
    conn.close()
    return _to_dict(row) if row else None


def get_lead_by_id(lead_id: int) -> Optional[dict]:
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("SELECT * FROM lead_venditori WHERE id = ?"), (lead_id,))
    row = cur.fetchone()
    conn.close()
    return _to_dict(row) if row else None


def update_lead(lead_id: int, **fields):
    if not fields:
        return
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields.keys())
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql(f"UPDATE lead_venditori SET {cols} WHERE id = ?"),
                (*fields.values(), lead_id))
    conn.commit(); conn.close()


def list_active_leads(provincia: Optional[str] = None) -> List[dict]:
    """Lead attivi, opzionalmente filtrati per provincia (case-insensitive)."""
    conn = get_conn(); cur = _cur(conn)
    if provincia:
        cur.execute(_sql("""
            SELECT * FROM lead_venditori
            WHERE status = 'attivo' AND lower(provincia) = lower(?)
            ORDER BY created_at DESC
        """), (provincia,))
    else:
        cur.execute(_sql("""
            SELECT * FROM lead_venditori
            WHERE status = 'attivo'
            ORDER BY created_at DESC
        """))
    rows = [_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ─── lead_contatti ───────────────────────────────────────────────────────────

def log_contatto(lead_id: int, agente_user_id: int) -> dict:
    """Registra (idempotente sulla coppia) il click 'Contatta' di un agente."""
    conn = get_conn(); cur = _cur(conn)
    # check duplicate
    cur.execute(_sql("""
        SELECT id FROM lead_contatti
        WHERE lead_venditore_id = ? AND agente_user_id = ?
    """), (lead_id, agente_user_id))
    existing = cur.fetchone()
    if existing:
        conn.close()
        return {"already_contacted": True}
    cur.execute(_sql("""
        INSERT INTO lead_contatti (lead_venditore_id, agente_user_id, contattato_at)
        VALUES (?, ?, ?)
    """), (lead_id, agente_user_id, _now()))
    conn.commit(); conn.close()
    return {"already_contacted": False}


def list_contatti_for_lead(lead_id: int) -> List[dict]:
    """Agenti che hanno contattato un lead (join con users)."""
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        SELECT c.id, c.contattato_at,
               u.id AS agente_id, u.email AS agente_email,
               u.nome AS agente_nome, u.cognome AS agente_cognome,
               u.city AS agente_city, u.telefono AS agente_telefono
        FROM lead_contatti c
        JOIN users u ON u.id = c.agente_user_id
        WHERE c.lead_venditore_id = ?
        ORDER BY c.contattato_at DESC
    """), (lead_id,))
    rows = [_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def list_contatti_set_for_agente(agente_user_id: int) -> set:
    """Set degli ID lead che l'agente ha già contattato (per badge 'Già contattato')."""
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        SELECT lead_venditore_id FROM lead_contatti
        WHERE agente_user_id = ?
    """), (agente_user_id,))
    ids = {row[0] if not isinstance(row, dict) else row["lead_venditore_id"]
           for row in cur.fetchall()}
    conn.close()
    return ids


def public_lead(lead: dict, with_telefono: bool = False) -> dict:
    """Versione safe per il frontend (espone telefono solo dopo 'Contatta')."""
    if not lead:
        return {}
    out = {
        "id":               lead["id"],
        "indirizzo":        lead.get("indirizzo"),
        "citta":            lead.get("citta"),
        "provincia":        lead.get("provincia"),
        "tipo_immobile":    lead.get("tipo_immobile"),
        "mq":               lead.get("mq"),
        "camere":           lead.get("camere"),
        "bagni":            lead.get("bagni"),
        "prezzo_richiesto": lead.get("prezzo_richiesto"),
        "descrizione":      lead.get("descrizione"),
        "urgenza":          lead.get("urgenza"),
        "foto_url":         lead.get("foto_url"),
        "status":           lead.get("status"),
        "created_at":       lead.get("created_at"),
    }
    if with_telefono:
        out["telefono_privato"] = lead.get("telefono_privato")
    return out
