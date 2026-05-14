"""
Sprint 5.2 — Backfill telefoni Subito (Playwright).

Gira sul VPS Hetzner. Flusso:
  1. GET {HOUSERADAR_URL}/api/annunci/subito-senza-telefono?token=SYNC_TOKEN
  2. Per ogni annuncio: estrai_telefono_subito_sync(url) con rate limit
  3. Bufferizza i risultati e POST a batch di 50 verso
     {HOUSERADAR_URL}/api/annunci/telefono-batch

Esecuzione:
    python -m backend.scripts.backfill_subito_phones --limit 50 --dry-run
    python -m backend.scripts.backfill_subito_phones --limit 200

Env richieste:
    SYNC_TOKEN, HOUSERADAR_URL (default https://houseradar.onrender.com)
"""

import argparse
import logging
import os
import sys
import time
from typing import List, Dict, Optional

import requests

# Permetti import del modulo extractor (top-level scraper/)
_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_DIR, "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "scraper"))

from subito_phone_extractor import estrai_telefono_subito_sync  # noqa: E402


HOUSERADAR_URL = os.environ.get("HOUSERADAR_URL", "https://houseradar.onrender.com").rstrip("/")
SYNC_TOKEN     = os.environ.get("SYNC_TOKEN", "")

BATCH_SIZE     = 50
HTTP_TIMEOUT   = 60

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill")


def _fetch_lista(limit: int) -> List[Dict]:
    url = f"{HOUSERADAR_URL}/api/annunci/subito-senza-telefono"
    r = requests.get(
        url,
        params={"limit": limit, "token": SYNC_TOKEN},
        headers={"X-Sync-Token": SYNC_TOKEN},
        timeout=HTTP_TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise RuntimeError(f"Risposta inattesa: {data}")
    return data


def _push_batch(batch: List[Dict]) -> Dict:
    if not batch:
        return {"aggiornati": 0, "saltati": 0, "invalidi": 0}
    url = f"{HOUSERADAR_URL}/api/annunci/telefono-batch"
    r = requests.post(
        url,
        json=batch,
        headers={
            "X-Sync-Token": SYNC_TOKEN,
            "Content-Type": "application/json",
        },
        timeout=HTTP_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def run(limit: int, dry_run: bool, rate_limit_sec: float) -> int:
    if not SYNC_TOKEN:
        log.error("SYNC_TOKEN non impostato — esporta la env var prima di lanciare.")
        return 1

    log.info(f"Target Render: {HOUSERADAR_URL}")
    log.info(f"Modalità: {'DRY-RUN (no DB writes)' if dry_run else 'LIVE'}")
    log.info(f"Limit annunci: {limit} | rate limit per annuncio: {rate_limit_sec}s")

    try:
        lista = _fetch_lista(limit)
    except Exception as e:
        log.error(f"Errore GET subito-senza-telefono: {e}")
        return 2

    log.info(f"Ricevuti {len(lista)} annunci da processare")
    if not lista:
        log.info("Nessun annuncio da elaborare — esco.")
        return 0

    estratti: List[Dict] = []
    buffer:   List[Dict] = []
    riusciti  = 0
    falliti   = 0
    tot_aggiornati = 0
    tot_saltati    = 0
    tot_invalidi   = 0
    started = time.monotonic()

    for idx, ann in enumerate(lista, start=1):
        ann_id = ann.get("id")
        url    = ann.get("url")
        if not ann_id or not url:
            falliti += 1
            continue

        tel: Optional[str] = estrai_telefono_subito_sync(url)
        if tel:
            riusciti += 1
            estratti.append({"id": ann_id, "telefono": tel})
            buffer.append({"id": ann_id, "telefono": tel})
            log.info(f"[{idx}/{len(lista)}] id={ann_id} → {tel}")
        else:
            falliti += 1
            log.info(f"[{idx}/{len(lista)}] id={ann_id} → MISS")

        # Push batch quando piena (solo live)
        if not dry_run and len(buffer) >= BATCH_SIZE:
            try:
                resp = _push_batch(buffer)
                tot_aggiornati += resp.get("aggiornati", 0)
                tot_saltati    += resp.get("saltati", 0)
                tot_invalidi   += resp.get("invalidi", 0)
                log.info(f"  → batch {len(buffer)}: aggiornati={resp.get('aggiornati')}")
            except Exception as e:
                log.error(f"  → batch push fallito: {e}")
            buffer = []

        # Progress ogni 10
        if idx % 10 == 0:
            elapsed = time.monotonic() - started
            log.info(f"  progress: {idx}/{len(lista)} | "
                     f"riusciti={riusciti} falliti={falliti} | "
                     f"elapsed={elapsed:.0f}s")

        # Rate limit (skip dopo l'ultimo)
        if idx < len(lista):
            time.sleep(rate_limit_sec)

    # Flush finale
    if not dry_run and buffer:
        try:
            resp = _push_batch(buffer)
            tot_aggiornati += resp.get("aggiornati", 0)
            tot_saltati    += resp.get("saltati", 0)
            tot_invalidi   += resp.get("invalidi", 0)
            log.info(f"  → batch finale {len(buffer)}: aggiornati={resp.get('aggiornati')}")
        except Exception as e:
            log.error(f"  → batch finale push fallito: {e}")

    elapsed = time.monotonic() - started
    log.info("=" * 58)
    log.info(f"Riepilogo backfill ({elapsed:.0f}s totali):")
    log.info(f"  Annunci processati : {len(lista)}")
    log.info(f"  Telefoni estratti  : {riusciti}")
    log.info(f"  Falliti/MISS       : {falliti}")
    if dry_run:
        log.info(f"  DRY-RUN: nessuna scrittura DB. Telefoni in memoria: {len(estratti)}")
    else:
        log.info(f"  DB aggiornati      : {tot_aggiornati}")
        log.info(f"  DB saltati         : {tot_saltati} (già con telefono)")
        log.info(f"  DB invalidi        : {tot_invalidi}")
    log.info("=" * 58)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Backfill telefoni Subito via Playwright")
    parser.add_argument("--limit", type=int, default=50,
                        help="Massimo annunci da processare (default: 50)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Non scrive nel DB Render, solo log")
    parser.add_argument("--rate-limit-sec", type=float, default=4.0,
                        help="Secondi di pausa tra annunci (default: 4.0)")
    args = parser.parse_args()
    sys.exit(run(args.limit, args.dry_run, args.rate_limit_sec))


if __name__ == "__main__":
    main()
