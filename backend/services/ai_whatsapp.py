"""
HouseRadar Sprint 5 — Killer App #3: WhatsApp Auto-Acquisizione.

Genera un messaggio WhatsApp breve (max ~80 parole) per il primo contatto
con un proprietario di immobile, via Claude Sonnet 4.5. Riusa i dati
dell'annuncio + la stima vendita probabile.

ENV richiesto in produzione: ANTHROPIC_API_KEY.
"""

import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.stima_service import calcola_stima, get_annuncio_by_id


# Pricing Sonnet 4.5 (USD per 1M tokens) e conversione approssimativa EUR
_PRICE_IN_USD_PER_MTOK  = 3.0
_PRICE_OUT_USD_PER_MTOK = 15.0
_USD_TO_EUR             = 0.92

CLAUDE_MODEL = "claude-sonnet-4-5"


class AIWhatsAppError(Exception):
    """Errore generico di generazione messaggio (rete, API down, key mancante)."""


def _stima_text(stima: dict) -> str:
    if not stima or not stima.get("available"):
        return "Stima vendita: non disponibile."
    return (
        f"Stima vendita probabile: €{stima['prezzo_probabile']:,} "
        f"({stima['riduzione_pct']}% vs richiesto)."
    ).replace(",", ".")


def _build_prompt(ann: dict, stima: dict, agente: dict) -> str:
    indirizzo     = ann.get("indirizzo") or "(indirizzo non specificato)"
    tipo          = ann.get("tipo") or "immobile"
    prezzo        = ann.get("prezzo") or 0
    mq            = ann.get("mq") or "—"
    citta         = ann.get("citta") or ann.get("zona") or ""
    provincia     = ann.get("provincia") or ""
    giorni        = ann.get("giorni_online") or 0

    nome_agente    = (agente.get("nome") or "").strip()
    cognome_agente = (agente.get("cognome") or "").strip()
    nome_full      = (nome_agente + " " + cognome_agente).strip() or "l'agente"
    citta_agente   = (agente.get("city") or "").strip() or "—"

    prezzo_str = f"{prezzo:,}".replace(",", ".") if prezzo else "n/d"
    luogo = f"{citta}{f' ({provincia})' if provincia else ''}".strip() or "—"

    return (
        "Sei assistente per agenti immobiliari italiani. Genera UN MESSAGGIO "
        "WHATSAPP breve (massimo 80 parole) per il PRIMO contatto con un "
        "proprietario di immobile.\n\n"
        "ANNUNCIO:\n"
        f"- Indirizzo: {indirizzo}\n"
        f"- Città: {luogo}\n"
        f"- Tipo: {tipo}\n"
        f"- Prezzo: €{prezzo_str}\n"
        f"- Mq: {mq}\n"
        f"- Online da: {giorni} giorni\n"
        f"- {_stima_text(stima)}\n\n"
        f"L'AGENTE è {nome_full} di {citta_agente}.\n\n"
        "REGOLE:\n"
        "- Massimo 80 parole (whatsapp è breve).\n"
        "- Tono italiano cordiale, professionale ma colloquiale (non \"Gentile signore\").\n"
        "- NO formule trite tipo \"Spero questo messaggio La trovi bene\".\n"
        "- NON dare per scontato di avere già parlato con la persona.\n"
        "- Saluto, presentazione (chi sei e perché scrivi), gancio (l'annuncio), "
        "proposta concreta (un appuntamento, una chiamata).\n"
        "- Termina con domanda diretta che invita risposta.\n"
        "- Solo il messaggio, niente preamboli.\n\n"
        "ESEMPIO DI STILE:\n"
        "\"Buongiorno, sono Mario di HouseRadar. Ho visto il suo annuncio per "
        "l'appartamento in Via Roma 12 a Livorno a 250.000€. Seguo quella zona "
        "e mi farebbe piacere parlarne con lei 5 minuti. Le va bene se ci "
        "sentiamo domani in mattinata? Buona giornata.\""
    )


def _stima_costo_eur(tok_in: int, tok_out: int) -> float:
    usd = (tok_in  / 1_000_000.0) * _PRICE_IN_USD_PER_MTOK \
        + (tok_out / 1_000_000.0) * _PRICE_OUT_USD_PER_MTOK
    return round(usd * _USD_TO_EUR, 4)


def genera_messaggio_whatsapp(annuncio_id: int, agente: dict) -> dict:
    """
    Genera il messaggio WhatsApp via Claude Sonnet 4.5.

    Ritorna: {"messaggio": str, "telefono": str|None, "annuncio": dict,
              "tokens_input": int, "tokens_output": int, "costo_eur": float}
    Solleva: AIWhatsAppError (annuncio mancante, key mancante, errore API).
    """
    ann = get_annuncio_by_id(annuncio_id)
    if not ann:
        raise AIWhatsAppError("Annuncio non trovato")

    telefono = (ann.get("telefono") or "").strip()
    if not telefono:
        raise AIWhatsAppError(
            "Questo annuncio non ha un numero di telefono. "
            "Riprova con un altro annuncio."
        )

    stima  = calcola_stima(ann)
    prompt = _build_prompt(ann, stima, agente or {})

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise AIWhatsAppError("ANTHROPIC_API_KEY non configurata sul server")

    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise AIWhatsAppError(f"SDK anthropic non installato: {e}")

    try:
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,  # WhatsApp è breve
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        raise AIWhatsAppError(f"Errore Anthropic API: {e}")

    parts = []
    for block in (resp.content or []):
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    messaggio = "\n".join(parts).strip()
    if not messaggio:
        raise AIWhatsAppError("Risposta vuota dall'API")

    tok_in  = int(getattr(resp.usage, "input_tokens", 0) or 0)
    tok_out = int(getattr(resp.usage, "output_tokens", 0) or 0)

    return {
        "messaggio":     messaggio,
        "telefono":      telefono,
        "annuncio":      ann,
        "tokens_input":  tok_in,
        "tokens_output": tok_out,
        "costo_eur":     _stima_costo_eur(tok_in, tok_out),
    }
