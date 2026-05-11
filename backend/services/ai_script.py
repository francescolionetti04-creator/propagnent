"""
HouseRadar Sprint 4 — Killer App #1: Script Chiamata AI.

Genera lo script telefonico (30-45 sec) per un annuncio, da Claude Sonnet 4.5.
Riusa i dati dell'annuncio + la stima vendita probabile per agganciare l'apertura.

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


class AIScriptError(Exception):
    """Errore generico di generazione script (rete, API down, key mancante)."""


def _stima_text(stima: dict) -> str:
    """Riepilogo compatto della stima da inserire nel prompt."""
    if not stima or not stima.get("available"):
        return "Stima vendita: non disponibile (campione insufficiente)."
    return (
        f"Stima vendita: €{stima['prezzo_probabile']:,} "
        f"({stima['riduzione_pct']}% vs richiesto), "
        f"tempo medio {stima['tempo_giorni']} giorni, "
        f"confidenza {stima['confidenza_pct']}%."
    ).replace(",", ".")


def _build_prompt(ann: dict, stima: dict, agente: dict) -> str:
    indirizzo     = ann.get("indirizzo") or "(indirizzo non specificato)"
    tipo          = ann.get("tipo") or "immobile"
    prezzo        = ann.get("prezzo") or 0
    mq            = ann.get("mq") or "—"
    giorni        = ann.get("giorni_online") or 0
    nome_agente   = (agente.get("nome") or "").strip() or "l'agente"
    citta_agente  = (agente.get("city") or "").strip() or "—"

    prezzo_str = f"{prezzo:,}".replace(",", ".") if prezzo else "n/d"

    return (
        "Sei assistente per agenti immobiliari italiani. "
        "Genera SCRIPT CHIAMATA di 30-45 secondi. "
        f"Annuncio: {indirizzo}, {tipo}, €{prezzo_str}, {mq}mq, online da {giorni} giorni. "
        f"{_stima_text(stima)} "
        f"Agente: {nome_agente} di {citta_agente}. "
        "Struttura: 1) APERTURA (5s) 2) AGGANCIO (10s) 3) PROPOSTA (15s) 4) CHIUSURA (10s). "
        "Tono italiano colloquiale toscano, no aziendalese. "
        "Solo lo script, niente preamboli."
    )


def _stima_costo_eur(tok_in: int, tok_out: int) -> float:
    usd = (tok_in  / 1_000_000.0) * _PRICE_IN_USD_PER_MTOK \
        + (tok_out / 1_000_000.0) * _PRICE_OUT_USD_PER_MTOK
    return round(usd * _USD_TO_EUR, 4)


def genera_script_chiamata(annuncio_id: int, agente: dict) -> dict:
    """
    Genera lo script chiamata via Claude Sonnet 4.5.

    Ritorna: {"script": str, "tokens_input": int, "tokens_output": int, "costo_eur": float}
    Solleva: AIScriptError (annuncio mancante, key mancante, errore API).
    """
    ann = get_annuncio_by_id(annuncio_id)
    if not ann:
        raise AIScriptError("Annuncio non trovato")

    stima = calcola_stima(ann)
    prompt = _build_prompt(ann, stima, agente or {})

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise AIScriptError("ANTHROPIC_API_KEY non configurata sul server")

    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise AIScriptError(f"SDK anthropic non installato: {e}")

    try:
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        raise AIScriptError(f"Errore Anthropic API: {e}")

    # Estrai il testo (sommando i blocchi text)
    parts = []
    for block in (resp.content or []):
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    script = "\n".join(parts).strip()
    if not script:
        raise AIScriptError("Risposta vuota dall'API")

    tok_in  = int(getattr(resp.usage, "input_tokens", 0) or 0)
    tok_out = int(getattr(resp.usage, "output_tokens", 0) or 0)

    return {
        "script":        script,
        "tokens_input":  tok_in,
        "tokens_output": tok_out,
        "costo_eur":     _stima_costo_eur(tok_in, tok_out),
    }
