"""
HouseRadar — Killer App #2: Stima vendita probabile.

Calcola al volo:
  - prezzo_probabile  (prezzo finale stimato di chiusura)
  - riduzione_pct     (% di sconto medio rispetto al richiesto)
  - tempo_giorni      (tempo medio di vendita)
  - confidenza_pct    (0-95)
  - campione_size     (numero annunci simili usati)

L'algoritmo è pragmatico: usa la mediana di `giorni_online` e una riduzione
calibrata in base alla dimensione del campione di annunci simili in DB.
Quando avremo dati storici di chiusure vere, sostituiremo la sezione
`_riduzione_da_campione` con un calcolo basato sui dati reali.
"""

import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_conn, _cur, _sql, _to_dict


# Cache in-memory per evitare query ripetute (TTL implicito al boot)
_cache: dict = {}


def _query_simili(annuncio: dict) -> list:
    """Annunci comparabili: stessa zona/tipo + mq ±20%."""
    zona = annuncio.get("zona")
    tipo = annuncio.get("tipo")
    mq   = annuncio.get("mq")
    if not zona and not tipo:
        return []

    where = ["id != ?", "prezzo IS NOT NULL", "prezzo > 0"]
    params: list = [annuncio.get("id") or -1]

    if tipo:
        where.append("lower(tipo) = lower(?)")
        params.append(tipo)
    if zona:
        # match esatto OR LIKE per essere robusti a "Livorno Città" vs "Livorno"
        where.append("(zona = ? OR zona LIKE ?)")
        params.append(zona)
        params.append(f"%{zona.split()[0]}%")
    if mq:
        mq_min = int(mq * 0.80)
        mq_max = int(mq * 1.20)
        where.append("mq BETWEEN ? AND ?")
        params.extend([mq_min, mq_max])

    sql = f"""
        SELECT id, prezzo, mq, camere, giorni_online, fonte, data_inserimento
        FROM annunci
        WHERE {' AND '.join(where)}
        LIMIT 500
    """
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql(sql), params)
    rows = [_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def _mediana(values: list) -> Optional[float]:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid-1] + vals[mid]) / 2.0


def _riduzione_da_campione(simili: list, base: dict) -> float:
    """
    Stima riduzione: -3% baseline, calibrata sul comportamento del campione.
    Heuristica:
      - Più il campione ha mediana 'giorni_online' alta → mercato lento → maggior riduzione
      - In assenza di vendite reali nel DB, ci limitiamo a una scala 3%-10%.
    """
    n = len(simili)
    if n == 0:
        return -3.0
    gg = _mediana([s.get("giorni_online") for s in simili]) or 30
    if gg < 30:
        return -3.5
    if gg < 60:
        return -5.0
    if gg < 90:
        return -7.0
    return -10.0


def calcola_stima(annuncio: dict) -> dict:
    """Restituisce il dict di stima per un annuncio. Cache in-memory by id."""
    if not annuncio or not annuncio.get("prezzo"):
        return {
            "available": False,
            "reason": "Prezzo annuncio non disponibile",
            "campione_size": 0,
            "confidenza_pct": 0,
        }

    ann_id = annuncio.get("id")
    if ann_id and ann_id in _cache:
        return _cache[ann_id]

    simili = _query_simili(annuncio)
    n = len(simili)

    if n < 3:
        out = {
            "available":      False,
            "reason":         f"Solo {n} annunci simili nel DB — dati insufficienti per stima",
            "campione_size":  n,
            "confidenza_pct": 0,
        }
    else:
        riduzione = _riduzione_da_campione(simili, annuncio)
        tempo     = int(_mediana([s.get("giorni_online") for s in simili]) or 60)
        confidenza = min(95, 30 + n)  # 30 al min, 95 al max
        prezzo_prob = int(annuncio["prezzo"] * (1 + riduzione / 100.0))
        out = {
            "available":         True,
            "prezzo_probabile":  prezzo_prob,
            "prezzo_richiesto":  annuncio["prezzo"],
            "riduzione_pct":     round(riduzione, 1),
            "tempo_giorni":      tempo,
            "confidenza_pct":    confidenza,
            "campione_size":     n,
        }

    if ann_id:
        _cache[ann_id] = out
    return out


def get_annuncio_by_id(annuncio_id: int) -> Optional[dict]:
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("SELECT * FROM annunci WHERE id = ?"), (annuncio_id,))
    row = cur.fetchone()
    conn.close()
    return _to_dict(row) if row else None
