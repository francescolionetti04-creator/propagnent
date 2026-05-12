"""
HouseRadar — Sprint 5.0.2 Task SX (CRITICO)
Normalizza il campo citta + provincia degli annunci esistenti che hanno
citta IS NULL o provincia IS NULL.

Idempotente: può essere lanciato N volte senza danni (skip dei record già normalizzati).

Uso:
  python -m backend.scripts.normalize_annunci_geo
oppure dal main.py al boot via run().
"""

import os
import sys

# Risali a backend/ così possiamo importare database + geo
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from database import get_conn, _cur, _sql, _to_dict
from geo.comuni_toscana import normalizza_annuncio


def run() -> dict:
    """Normalizza tutti gli annunci con citta IS NULL o provincia IS NULL.

    Returns:
      {"updated": N, "not_found": M, "totale": K}
    """
    conn = get_conn()
    cur  = _cur(conn)

    # Filtra solo quelli ancora da normalizzare (idempotenza)
    cur.execute(_sql("""
        SELECT id, indirizzo, zona
        FROM annunci
        WHERE citta IS NULL OR provincia IS NULL
    """))
    rows = [_to_dict(r) for r in cur.fetchall()]

    updated = 0
    not_found = 0
    for r in rows:
        citta, provincia = normalizza_annuncio(r.get("indirizzo"), r.get("zona"))
        if not citta and not provincia:
            not_found += 1
            continue
        cur.execute(_sql("""
            UPDATE annunci SET citta = ?, provincia = ?
            WHERE id = ?
        """), (citta, provincia, r["id"]))
        updated += 1

    conn.commit()
    conn.close()

    print(f"[normalize_annunci_geo] updated={updated} not_found={not_found} "
          f"totale={len(rows)}")
    return {"updated": updated, "not_found": not_found, "totale": len(rows)}


if __name__ == "__main__":
    run()
