"""CRUD lead_compratori + lead_match — raw SQL via database._sql()."""

import os
import sys
from datetime import datetime
from typing import Optional, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_conn, _cur, _sql, _to_dict


PROVINCE = (
    "Livorno", "Pisa", "Firenze", "Siena", "Arezzo",
    "Lucca", "Grosseto", "Pistoia", "Prato", "Massa-Carrara",
)
VALID_TIPI    = ("appartamento", "villa", "attico", "loft", "monolocale", "altro")
VALID_URGENZE = ("alta", "media", "bassa")
VALID_STATUS  = ("attivo", "soddisfatto", "sospeso")


def _now() -> str:
    return datetime.utcnow().isoformat()


def _csv(values) -> Optional[str]:
    if not values:
        return None
    if isinstance(values, str):
        return values
    return ",".join(str(v).strip() for v in values if str(v).strip())


def _parse_csv(s: Optional[str]) -> List[str]:
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]


# ─── lead_compratori ─────────────────────────────────────────────────────────

def create_lead(user_id: int, **fields) -> dict:
    now = _now()
    cols = [
        "user_id", "province_interesse", "zona_libera", "tipo_immobile",
        "mq_min", "mq_max", "camere_min",
        "prezzo_min", "prezzo_max",
        "urgenza", "note_aggiuntive", "email_match_attivo",
        "status", "created_at", "updated_at",
    ]
    vals = [
        user_id,
        _csv(fields.get("province_interesse")),
        fields.get("zona_libera"),
        _csv(fields.get("tipo_immobile")),
        fields.get("mq_min"),
        fields.get("mq_max"),
        fields.get("camere_min"),
        fields.get("prezzo_min"),
        fields.get("prezzo_max"),
        fields.get("urgenza", "media"),
        fields.get("note_aggiuntive"),
        1 if fields.get("email_match_attivo", True) else 0,
        fields.get("status", "attivo"),
        now, now,
    ]
    placeholders = ",".join(["?"] * len(cols))
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql(f"INSERT INTO lead_compratori ({', '.join(cols)}) VALUES ({placeholders})"), vals)
    conn.commit()
    cur.execute(_sql("""
        SELECT * FROM lead_compratori
        WHERE user_id = ?
        ORDER BY id DESC LIMIT 1
    """), (user_id,))
    row = cur.fetchone()
    conn.close()
    return _to_dict(row) if row else {}


def get_active_lead_by_user(user_id: int) -> Optional[dict]:
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        SELECT * FROM lead_compratori
        WHERE user_id = ?
        ORDER BY id DESC LIMIT 1
    """), (user_id,))
    row = cur.fetchone()
    conn.close()
    return _to_dict(row) if row else None


def get_lead_by_id(lead_id: int) -> Optional[dict]:
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("SELECT * FROM lead_compratori WHERE id = ?"), (lead_id,))
    row = cur.fetchone()
    conn.close()
    return _to_dict(row) if row else None


def update_lead(lead_id: int, **fields):
    if not fields:
        return
    # CSV-encode list-like fields
    if "province_interesse" in fields:
        fields["province_interesse"] = _csv(fields["province_interesse"])
    if "tipo_immobile" in fields:
        fields["tipo_immobile"] = _csv(fields["tipo_immobile"])
    if "email_match_attivo" in fields:
        fields["email_match_attivo"] = 1 if fields["email_match_attivo"] else 0
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields.keys())
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql(f"UPDATE lead_compratori SET {cols} WHERE id = ?"),
                (*fields.values(), lead_id))
    conn.commit(); conn.close()


def list_active_leads() -> List[dict]:
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        SELECT * FROM lead_compratori
        WHERE status = 'attivo'
        ORDER BY created_at DESC
    """))
    rows = [_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def public_lead(lead: Optional[dict]) -> Optional[dict]:
    if not lead:
        return None
    return {
        "id":                  lead["id"],
        "province_interesse":  _parse_csv(lead.get("province_interesse")),
        "zona_libera":         lead.get("zona_libera"),
        "tipo_immobile":       _parse_csv(lead.get("tipo_immobile")),
        "mq_min":              lead.get("mq_min"),
        "mq_max":              lead.get("mq_max"),
        "camere_min":          lead.get("camere_min"),
        "prezzo_min":          lead.get("prezzo_min"),
        "prezzo_max":          lead.get("prezzo_max"),
        "urgenza":             lead.get("urgenza"),
        "note_aggiuntive":     lead.get("note_aggiuntive"),
        "email_match_attivo":  bool(lead.get("email_match_attivo")),
        "status":              lead.get("status"),
        "created_at":          lead.get("created_at"),
    }


# ─── lead_match ──────────────────────────────────────────────────────────────

def insert_match(lead_compratore_id: int, annuncio_id: int, match_score: int) -> bool:
    """Inserisce un match. False se duplicato (UNIQUE constraint)."""
    conn = get_conn(); cur = _cur(conn)
    try:
        cur.execute(_sql("""
            INSERT OR IGNORE INTO lead_match
              (lead_compratore_id, annuncio_id, match_score, notificato_via_email, created_at)
            VALUES (?, ?, ?, 0, ?)
        """), (lead_compratore_id, annuncio_id, match_score, _now()))
        # rowcount == 1 se inserito, 0 se ignorato
        inserted = (cur.rowcount > 0) if cur.rowcount is not None else True
        conn.commit()
    except Exception as e:
        print(f"[match] insert error: {e}")
        inserted = False
    finally:
        conn.close()
    return inserted


def get_existing_annuncio_ids(lead_compratore_id: int) -> set:
    """Set degli annuncio_id già presenti per quel compratore (per dedup)."""
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        SELECT annuncio_id FROM lead_match WHERE lead_compratore_id = ?
    """), (lead_compratore_id,))
    out = {row[0] if not isinstance(row, dict) else row["annuncio_id"]
           for row in cur.fetchall()}
    conn.close()
    return out


def get_match_for_user(user_id: int, limit: int = 50) -> List[dict]:
    """
    Ritorna lead_match × annunci per il compratore corrente,
    ordinati per match_score DESC, created_at DESC.
    """
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        SELECT
            m.id              AS match_id,
            m.match_score     AS match_score,
            m.created_at      AS matched_at,
            m.notificato_via_email AS notified,
            a.id              AS annuncio_id,
            a.indirizzo       AS indirizzo,
            a.zona            AS zona,
            a.tipo            AS tipo,
            a.mq              AS mq,
            a.camere          AS camere,
            a.prezzo          AS prezzo,
            a.giorni_online   AS giorni_online,
            a.fonte           AS fonte,
            a.url_originale   AS url,
            a.foto_url        AS foto_url,
            a.portale         AS portale,
            a.data_inserimento AS data_inserimento
        FROM lead_match m
        JOIN annunci a ON a.id = m.annuncio_id
        JOIN lead_compratori lc ON lc.id = m.lead_compratore_id
        WHERE lc.user_id = ?
        ORDER BY m.match_score DESC, m.created_at DESC
        LIMIT ?
    """), (user_id, limit))
    rows = [_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_unnotified_matches(lead_compratore_id: int, since_iso: Optional[str] = None) -> List[dict]:
    """Match non ancora notificati via email per un compratore."""
    conn = get_conn(); cur = _cur(conn)
    if since_iso:
        cur.execute(_sql("""
            SELECT m.id, m.match_score, m.created_at,
                   a.id AS annuncio_id, a.indirizzo, a.zona, a.tipo,
                   a.mq, a.camere, a.prezzo, a.url_originale, a.foto_url
            FROM lead_match m JOIN annunci a ON a.id = m.annuncio_id
            WHERE m.lead_compratore_id = ?
              AND m.notificato_via_email = 0
              AND m.created_at >= ?
            ORDER BY m.match_score DESC
        """), (lead_compratore_id, since_iso))
    else:
        cur.execute(_sql("""
            SELECT m.id, m.match_score, m.created_at,
                   a.id AS annuncio_id, a.indirizzo, a.zona, a.tipo,
                   a.mq, a.camere, a.prezzo, a.url_originale, a.foto_url
            FROM lead_match m JOIN annunci a ON a.id = m.annuncio_id
            WHERE m.lead_compratore_id = ?
              AND m.notificato_via_email = 0
            ORDER BY m.match_score DESC
        """), (lead_compratore_id,))
    rows = [_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def mark_notified(match_ids: List[int]):
    if not match_ids:
        return
    conn = get_conn(); cur = _cur(conn)
    placeholders = ",".join(["?"] * len(match_ids))
    cur.execute(_sql(
        f"UPDATE lead_match SET notificato_via_email = 1 WHERE id IN ({placeholders})"
    ), match_ids)
    conn.commit(); conn.close()
