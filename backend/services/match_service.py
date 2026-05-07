"""
HouseRadar — Match service (cron jobs giornalieri).

run_match_cron():
  Per ogni lead_compratore attivo, query annunci che matchano le preferenze
  e inserisce nuovi record in lead_match con match_score 0-100.

run_match_email():
  Invia email Resend ai compratori con email_match_attivo=True per i match
  non ancora notificati.

Entrambi sono progettati per essere idempotenti: la UNIQUE constraint
su (lead_compratore_id, annuncio_id) impedisce duplicati.
"""

import os
import sys
import re
from datetime import datetime, timedelta
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_conn, _cur, _sql, _to_dict
from auth.users_db import get_user_by_id
from compratore.db import (
    list_active_leads, insert_match, get_existing_annuncio_ids,
    get_unnotified_matches, mark_notified, _parse_csv,
)
from services.email import send_compratore_match_email


# ─── Match scoring ───────────────────────────────────────────────────────────

def _midpoint_score(value, mn, mx, weight: int) -> int:
    """Punteggio max 'weight' se 'value' è al centro del range [mn, mx].
    0 se fuori range. Lineare al centro."""
    if value is None or mn is None or mx is None:
        return 0
    if value < mn or value > mx:
        return 0
    if mx == mn:
        return weight
    mid = (mn + mx) / 2.0
    half = (mx - mn) / 2.0 or 1
    dist = abs(value - mid)
    return int(weight * max(0.0, 1.0 - dist / half))


def _zona_libera_score(zona_libera: Optional[str], annuncio: dict, weight: int = 20) -> int:
    if not zona_libera:
        return 0
    keywords = [w.strip().lower() for w in re.split(r"[,;]+", zona_libera) if w.strip()]
    if not keywords:
        return 0
    haystack = " ".join([
        (annuncio.get("zona") or ""),
        (annuncio.get("indirizzo") or ""),
    ]).lower()
    hits = sum(1 for kw in keywords if kw in haystack)
    if not hits:
        return 0
    return int(weight * min(1.0, hits / max(1, len(keywords))))


def _recent_score(data_inserimento: Optional[str], weight: int = 20) -> int:
    if not data_inserimento:
        return 0
    try:
        di = datetime.fromisoformat(str(data_inserimento).replace("Z", "+00:00"))
        delta = (datetime.utcnow() - di.replace(tzinfo=None)).days
        if delta <= 7:
            return weight
        if delta <= 14:
            return weight // 2
    except Exception:
        pass
    return 0


def compute_match_score(annuncio: dict, lead: dict) -> int:
    score = 0
    score += _midpoint_score(annuncio.get("prezzo"),
                              lead.get("prezzo_min"), lead.get("prezzo_max"), 30)
    score += _midpoint_score(annuncio.get("mq"),
                              lead.get("mq_min"), lead.get("mq_max"), 20)
    score += _zona_libera_score(lead.get("zona_libera"), annuncio, 20)
    score += _recent_score(annuncio.get("data_inserimento"), 20)
    if (lead.get("camere_min") and annuncio.get("camere")
        and annuncio["camere"] == lead["camere_min"]):
        score += 10
    return min(100, max(0, score))


# ─── Cron: match generation ──────────────────────────────────────────────────

def _zona_to_provincia(zona: Optional[str]) -> Optional[str]:
    """Mappa zona HouseRadar → provincia. Usa parole chiave."""
    if not zona:
        return None
    z = zona.lower()
    if any(k in z for k in ("livorno", "elba", "cornia", "cecina", "rosignano",
                             "piombino", "collesalvetti")):
        return "Livorno"
    if any(k in z for k in ("pisa", "valdera", "valdicecina", "marina di pisa",
                             "tirrenia", "valdarno pisano", "san miniato")):
        return "Pisa"
    if "firenz" in z: return "Firenze"
    if "siena"  in z: return "Siena"
    if "arezzo" in z: return "Arezzo"
    if "lucca"  in z: return "Lucca"
    if "grosseto" in z: return "Grosseto"
    if "pistoia" in z: return "Pistoia"
    if "prato" in z: return "Prato"
    if "massa" in z or "carrara" in z: return "Massa-Carrara"
    return None


def _query_annunci_for_lead(lead: dict) -> list:
    """Esegue una query SQL ottimizzata su annunci per le preferenze del lead."""
    province = _parse_csv(lead.get("province_interesse"))
    tipi     = _parse_csv(lead.get("tipo_immobile"))

    where = ["1=1"]
    params: list = []

    # Tipo: confronto case-insensitive
    if tipi:
        ph = ",".join(["?"] * len(tipi))
        where.append(f"lower(tipo) IN ({ph})")
        params.extend([t.lower() for t in tipi])

    if lead.get("mq_min") is not None:
        where.append("mq IS NOT NULL AND mq >= ?")
        params.append(int(lead["mq_min"]))
    if lead.get("mq_max") is not None:
        where.append("(mq IS NULL OR mq <= ?)")
        params.append(int(lead["mq_max"]))
    if lead.get("camere_min") is not None:
        where.append("(camere IS NULL OR camere >= ?)")
        params.append(int(lead["camere_min"]))
    if lead.get("prezzo_min") is not None:
        where.append("prezzo IS NOT NULL AND prezzo >= ?")
        params.append(int(lead["prezzo_min"]))
    if lead.get("prezzo_max") is not None:
        where.append("prezzo IS NOT NULL AND prezzo <= ?")
        params.append(int(lead["prezzo_max"]))

    sql = f"""
        SELECT id, indirizzo, zona, tipo, mq, camere, prezzo,
               giorni_online, fonte, url_originale, data_inserimento
        FROM annunci
        WHERE {' AND '.join(where)}
        ORDER BY data_inserimento DESC
        LIMIT 500
    """

    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql(sql), params)
    rows = [_to_dict(r) for r in cur.fetchall()]
    conn.close()

    # Filtro provincia in Python (più semplice e robusto della mappatura SQL)
    if province:
        prov_set = {p.lower() for p in province}
        rows = [r for r in rows
                if (_zona_to_provincia(r.get("zona")) or "").lower() in prov_set]

    return rows


def run_match_cron() -> dict:
    """Genera nuovi match per tutti i compratori attivi. Idempotente."""
    leads = list_active_leads()
    total_matches = 0
    print(f"[match-cron] Avvio: {len(leads)} compratori attivi")

    for lead in leads:
        try:
            existing = get_existing_annuncio_ids(lead["id"])
            annunci = _query_annunci_for_lead(lead)
            nuovi = 0
            for ann in annunci:
                if ann["id"] in existing:
                    continue
                score = compute_match_score(ann, lead)
                if score < 30:  # threshold minima per evitare rumore
                    continue
                if insert_match(lead["id"], ann["id"], score):
                    nuovi += 1
            total_matches += nuovi
            print(f"[match-cron]   lead_compratore={lead['id']} (user={lead['user_id']}) → {nuovi} nuovi match")
        except Exception as e:
            print(f"[match-cron] errore lead {lead.get('id')}: {e}")

    print(f"[match-cron] Completato — {total_matches} match totali creati")
    return {"compratori_processati": len(leads), "match_creati": total_matches}


# ─── Cron: email notifications ───────────────────────────────────────────────

def run_match_email() -> dict:
    """Invia email ai compratori con match non ancora notificati nelle ultime 24h."""
    leads = list_active_leads()
    inviate = 0
    since = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    print(f"[match-email] Avvio: {len(leads)} compratori attivi")

    for lead in leads:
        if not lead.get("email_match_attivo"):
            continue
        try:
            matches = get_unnotified_matches(lead["id"], since_iso=since)
            if not matches:
                continue
            user = get_user_by_id(lead["user_id"])
            if not user:
                continue
            ok = send_compratore_match_email(
                to=user["email"],
                nome=user.get("nome"),
                match_count=len(matches),
                top_matches=matches,
                lead_id=lead["id"],
            )
            if ok:
                mark_notified([m["id"] for m in matches])
                inviate += 1
                print(f"[match-email]   user={user['email']} → {len(matches)} match notificati")
        except Exception as e:
            print(f"[match-email] errore lead {lead.get('id')}: {e}")

    print(f"[match-email] Completato — {inviate} email inviate")
    return {"email_inviate": inviate}


def run_full_pipeline():
    """Esecuzione end-to-end: match + email. Usato dallo scheduler."""
    print(f"\n{'='*58}\n[match] PIPELINE — {datetime.utcnow().isoformat()}\n{'='*58}")
    a = run_match_cron()
    b = run_match_email()
    print(f"[match] Done: {a} | {b}\n")
    return {**a, **b}


if __name__ == "__main__":
    run_full_pipeline()
