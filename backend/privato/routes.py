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


# ─── Sprint 5: Killer App #3 — WhatsApp Auto-Acquisizione ───────────────────

# Rate limit in-memory per generazione messaggi WhatsApp: 20/h per agente
_WA_RL_WINDOW = 3600
_WA_RL_MAX    = 20
_wa_rl: dict  = {}
_wa_rl_lock   = None

VALID_WA_STATUS = {"inviato", "letto", "risposto", "non_risposto"}


def _rate_limit_wa(user_id: int) -> Optional[int]:
    """Ritorna None se ok, oppure i secondi di retry-after."""
    import time
    import threading
    global _wa_rl_lock
    if _wa_rl_lock is None:
        _wa_rl_lock = threading.Lock()
    now = time.time()
    with _wa_rl_lock:
        hist = [t for t in _wa_rl.get(user_id, []) if now - t < _WA_RL_WINDOW]
        if len(hist) >= _WA_RL_MAX:
            retry = int(_WA_RL_WINDOW - (now - hist[0])) + 1
            _wa_rl[user_id] = hist
            return max(1, retry)
        hist.append(now)
        _wa_rl[user_id] = hist
        return None


class WhatsAppInviaIn(BaseModel):
    annuncio_id: int
    telefono:    Optional[str] = None  # Sprint 5.1: opzionale, fallback su annuncio.telefono
    messaggio:   str


def _wa_normalize_it_phone(tel: str) -> Optional[str]:
    """Replica server-side della validazione frontend normalizzaTelefono().
    Ritorna il numero "puro" (solo cifre, con prefisso 39) o None se non valido per WhatsApp."""
    if not tel:
        return None
    n = "".join(ch for ch in str(tel) if ch.isdigit())
    if not n:
        return None
    if n.startswith("00"):
        n = n[2:]
    if n.startswith("39"):
        return n if 11 <= len(n) <= 13 else None
    if n.startswith("3") and 9 <= len(n) <= 11:
        return "39" + n
    if n.startswith("0"):
        return None  # numero fisso
    return n


class WhatsAppStatusIn(BaseModel):
    status: Optional[str] = None
    note:   Optional[str] = None


@router_agent.post("/whatsapp/genera/{annuncio_id}")
def whatsapp_genera(annuncio_id: int,
                    telefono: Optional[str] = Query(None),
                    user=Depends(require_paid)):
    """Genera messaggio WhatsApp AI per un annuncio. Non salva nel DB.

    Sprint 5.1: accetta `?telefono=` opzionale per consentire all'agente di
    inserire manualmente un numero quando l'annuncio nel DB non lo possiede.
    Se l'annuncio non ha telefono e non ne viene passato uno, ritorna 400 con
    detail={error:"no_phone", url_originale: ...} così il frontend può mostrare
    il modal STEP 0 di inserimento manuale.
    """
    retry_after = _rate_limit_wa(user["id"])
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail=f"Hai raggiunto il limite di {_WA_RL_MAX} messaggi/ora. "
                   f"Riprova tra {retry_after // 60} min.",
        )

    from services.stima_service import get_annuncio_by_id
    ann = get_annuncio_by_id(annuncio_id)
    if not ann:
        raise HTTPException(404, "Annuncio non trovato")

    telefono_manual = (telefono or "").strip()
    telefono_db     = (ann.get("telefono") or "").strip()
    telefono_eff    = telefono_manual or telefono_db

    if not telefono_eff:
        raise HTTPException(
            status_code=400,
            detail={
                "error":         "no_phone",
                "detail":        "Questo annuncio non ha un numero di telefono. "
                                 "Inseriscilo manualmente.",
                "url_originale": ann.get("url_originale") or "",
            },
        )

    if telefono_manual:
        norm = _wa_normalize_it_phone(telefono_manual)
        if not norm:
            raise HTTPException(
                status_code=400,
                detail="Numero non valido per WhatsApp. Inserisci un cellulare italiano.",
            )

    from services.ai_whatsapp import (
        genera_messaggio_whatsapp, AIWhatsAppError,
        _build_prompt, _stima_costo_eur, CLAUDE_MODEL,
    )
    from services.stima_service import calcola_stima

    try:
        if telefono_manual:
            # Bypass del check telefono nel servizio: l'annuncio non ha numero in DB
            # ma l'agente ne ha fornito uno manualmente. Riusiamo gli helper del
            # servizio per garantire identico comportamento di generazione.
            stima  = calcola_stima(ann)
            prompt = _build_prompt(ann, stima, user or {})

            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise AIWhatsAppError("ANTHROPIC_API_KEY non configurata sul server")

            from anthropic import Anthropic
            client = Anthropic(api_key=api_key)
            resp = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            parts = []
            for block in (resp.content or []):
                t = getattr(block, "text", None)
                if t:
                    parts.append(t)
            messaggio = "\n".join(parts).strip()
            if not messaggio:
                raise AIWhatsAppError("Risposta vuota dall'API")

            return {"messaggio": messaggio, "telefono": telefono_manual}

        out = genera_messaggio_whatsapp(annuncio_id, user)
    except AIWhatsAppError as e:
        msg = str(e)
        low = msg.lower()
        if "non trovato" in low:
            raise HTTPException(404, "Annuncio non trovato")
        if "numero di telefono" in low or "non ha un numero" in low:
            raise HTTPException(400, msg)
        print(f"[whatsapp-ai] errore: {msg}")
        raise HTTPException(
            status_code=503,
            detail="Servizio AI temporaneamente non disponibile. Riprova tra qualche minuto.",
        )
    except Exception as e:
        print(f"[whatsapp-ai] errore inatteso: {e}")
        raise HTTPException(
            status_code=503,
            detail="Servizio AI temporaneamente non disponibile. Riprova tra qualche minuto.",
        )

    return {
        "messaggio": out["messaggio"],
        "telefono":  out["telefono"],
    }


@router_agent.post("/whatsapp/invia")
def whatsapp_invia(body: WhatsAppInviaIn, user=Depends(require_paid)):
    """Salva il messaggio come 'inviato' (ottimistico, prima del click WhatsApp).

    Sprint 5.1: se body.telefono non viene fornito, fallback su annuncio.telefono.
    Il telefono effettivamente salvato è quello usato per contattare il privato
    (manuale se fornito dall'agente, altrimenti quello del DB).
    """
    from database import get_conn as _gc, _cur as _gcur, _sql as _gsql

    telefono  = (body.telefono or "").strip()
    messaggio = (body.messaggio or "").strip()
    if not messaggio:
        raise HTTPException(400, "Messaggio vuoto")

    conn = _gc(); cur = _gcur(conn)
    try:
        cur.execute(_gsql("SELECT id, telefono FROM annunci WHERE id = ?"),
                    (body.annuncio_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            raise HTTPException(404, "Annuncio non trovato")
        if not telefono:
            ann_tel = row[1] if not isinstance(row, dict) else row.get("telefono")
            telefono = (ann_tel or "").strip()

        cur.execute(_gsql("""
            INSERT INTO whatsapp_messages
                (agente_user_id, annuncio_id, telefono_privato, messaggio_inviato, status)
            VALUES (?, ?, ?, ?, 'inviato')
        """), (user["id"], body.annuncio_id, telefono[:20], messaggio))
        conn.commit()

        # ID dell'ultimo inserimento (SQLite + Postgres compat)
        try:
            new_id = cur.lastrowid  # SQLite
        except Exception:
            new_id = None
        if not new_id:
            cur.execute(_gsql("""
                SELECT id FROM whatsapp_messages
                WHERE agente_user_id = ? AND annuncio_id = ?
                ORDER BY id DESC LIMIT 1
            """), (user["id"], body.annuncio_id))
            row = cur.fetchone()
            new_id = row[0] if row else None
    finally:
        conn.close()

    return {"success": True, "id": new_id}


@router_agent.get("/whatsapp/inbox")
def whatsapp_inbox(user=Depends(require_paid)):
    """Lista messaggi WhatsApp dell'agente con info annuncio collegato."""
    from database import get_conn as _gc, _cur as _gcur, _sql as _gsql, _to_dict as _gto

    conn = _gc(); cur = _gcur(conn)
    cur.execute(_gsql("""
        SELECT  w.id, w.annuncio_id, w.telefono_privato, w.messaggio_inviato,
                w.inviato_at, w.status, w.note, w.aggiornato_at,
                a.indirizzo, a.citta, a.provincia, a.prezzo, a.mq, a.tipo,
                a.foto_url, a.url_originale
        FROM whatsapp_messages w
        LEFT JOIN annunci a ON a.id = w.annuncio_id
        WHERE w.agente_user_id = ? AND w.removed_at IS NULL
        ORDER BY w.inviato_at DESC
    """), (user["id"],))
    rows = [_gto(r) for r in cur.fetchall()]
    conn.close()

    counters = {"tutti": 0, "inviato": 0, "letto": 0, "risposto": 0, "non_risposto": 0}
    for r in rows:
        counters["tutti"] += 1
        st = r.get("status") or "inviato"
        if st in counters:
            counters[st] += 1

    return {"messaggi": rows, "counters": counters}


@router_agent.patch("/whatsapp/{wa_id}/status")
def whatsapp_update_status(wa_id: int, body: WhatsAppStatusIn,
                           user=Depends(require_paid)):
    """Aggiorna status e/o note di un messaggio (solo del proprietario)."""
    from database import get_conn as _gc, _cur as _gcur, _sql as _gsql
    from datetime import datetime

    new_status = body.status
    new_note   = body.note
    if new_status is not None and new_status not in VALID_WA_STATUS:
        raise HTTPException(400, f"Status non valido. Usa: {sorted(VALID_WA_STATUS)}")

    conn = _gc(); cur = _gcur(conn)
    cur.execute(_gsql("""
        SELECT agente_user_id, removed_at FROM whatsapp_messages WHERE id = ?
    """), (wa_id,))
    row = cur.fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "Messaggio non trovato")
    owner_id  = row[0] if not isinstance(row, dict) else row["agente_user_id"]
    removed   = row[1] if not isinstance(row, dict) else row["removed_at"]
    if owner_id != user["id"]:
        conn.close(); raise HTTPException(403, "Non autorizzato")
    if removed:
        conn.close(); raise HTTPException(404, "Messaggio rimosso")

    now = datetime.utcnow().isoformat()
    if new_status is not None and new_note is not None:
        cur.execute(_gsql("""
            UPDATE whatsapp_messages
            SET status = ?, note = ?, aggiornato_at = ?
            WHERE id = ?
        """), (new_status, new_note, now, wa_id))
    elif new_status is not None:
        cur.execute(_gsql("""
            UPDATE whatsapp_messages SET status = ?, aggiornato_at = ? WHERE id = ?
        """), (new_status, now, wa_id))
    elif new_note is not None:
        cur.execute(_gsql("""
            UPDATE whatsapp_messages SET note = ?, aggiornato_at = ? WHERE id = ?
        """), (new_note, now, wa_id))
    else:
        conn.close(); raise HTTPException(400, "Nessun campo da aggiornare (status o note)")
    conn.commit(); conn.close()
    return {"success": True}


@router_agent.delete("/whatsapp/{wa_id}")
def whatsapp_delete(wa_id: int, user=Depends(require_paid)):
    """Soft delete del messaggio."""
    from database import get_conn as _gc, _cur as _gcur, _sql as _gsql
    from datetime import datetime

    conn = _gc(); cur = _gcur(conn)
    cur.execute(_gsql("""
        SELECT agente_user_id, removed_at FROM whatsapp_messages WHERE id = ?
    """), (wa_id,))
    row = cur.fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "Messaggio non trovato")
    owner_id  = row[0] if not isinstance(row, dict) else row["agente_user_id"]
    removed   = row[1] if not isinstance(row, dict) else row["removed_at"]
    if owner_id != user["id"]:
        conn.close(); raise HTTPException(403, "Non autorizzato")
    if removed:
        conn.close(); return {"success": True}  # idempotente

    cur.execute(_gsql("""
        UPDATE whatsapp_messages SET removed_at = ? WHERE id = ?
    """), (datetime.utcnow().isoformat(), wa_id))
    conn.commit(); conn.close()
    return {"success": True}


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
