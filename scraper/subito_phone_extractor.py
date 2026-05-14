"""
Subito.it phone extractor — Playwright

Apre la pagina dettaglio di un annuncio Subito, clicca "Mostra numero" e legge
il telefono dal DOM (selettore stabile: address[class*="__number"]).

Esporta:
  - async estrai_telefono_subito(url, timeout_ms=15000) -> str | None
  - estrai_telefono_subito_sync(url, timeout_ms=15000) -> str | None
        Wrapper sync per chiamare da codice non-async (subito_api.py è sync).
  - normalizza_telefono_it(raw) -> str | None
        Rimuove +39 / spazi / trattini, valida cellulare IT (3XX, 9-10 cifre).

Fallback graceful: ogni eccezione viene catturata, ritorna None. Mai crash.
"""

import asyncio
import logging
import re
import time
from typing import Optional

log = logging.getLogger(__name__)

_UA_DESKTOP = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def normalizza_telefono_it(raw: Optional[str]) -> Optional[str]:
    """Normalizza un cellulare italiano.

    Accetta input come "+39 333 9229902", "0039-333.922.9902", "3339229902".
    Ritorna solo cifre se cellulare IT valido (parte con 3, lunghezza 9-10).
    None altrimenti.
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    # Rimuovi prefisso internazionale italiano se presente
    if digits.startswith("0039"):
        digits = digits[4:]
    elif digits.startswith("39") and len(digits) > 10:
        digits = digits[2:]
    if not digits.startswith("3"):
        return None
    if not (9 <= len(digits) <= 10):
        return None
    return digits


async def estrai_telefono_subito(
    url_annuncio: str,
    timeout_ms: int = 15000,
) -> Optional[str]:
    """Estrae il numero di telefono dalla pagina dettaglio di un annuncio Subito.

    Returns telefono normalizzato (solo cifre) o None se non disponibile.
    Non solleva eccezioni: ogni errore Playwright/network → log warning + None.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.error("Playwright non installato. pip install playwright && playwright install chromium")
        return None

    started = time.monotonic()
    telefono_raw: Optional[str] = None
    browser = None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            context = await browser.new_context(
                user_agent=_UA_DESKTOP,
                locale="it-IT",
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            try:
                await page.goto(url_annuncio, wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception as e:
                log.warning(f"[phone] goto fallito {url_annuncio}: {e}")
                return None

            # Cookie banner Didomi (best-effort, opzionale)
            try:
                accept = page.locator("#didomi-notice-agree-button")
                if await accept.count() > 0:
                    await accept.first.click(timeout=2000)
                    await page.wait_for_timeout(300)
            except Exception:
                pass

            # Trova il bottone "Mostra numero" (gestito da JS lato client)
            try:
                button = page.get_by_role(
                    "button",
                    name=re.compile(r"Mostra numero", re.IGNORECASE),
                )
                if await button.count() == 0:
                    # Annuncio di agenzia o privato senza bottone visibile
                    return None
                await button.first.scroll_into_view_if_needed(timeout=3000)
                await button.first.click(timeout=5000)
            except Exception as e:
                log.info(f"[phone] no button su {url_annuncio}: {e}")
                return None

            # Attende l'address con il numero
            try:
                await page.wait_for_selector(
                    'address[class*="__number"]',
                    timeout=5000,
                    state="visible",
                )
                telefono_raw = await page.locator(
                    'address[class*="__number"]'
                ).first.inner_text()
            except Exception as e:
                log.info(f"[phone] number non apparso su {url_annuncio}: {e}")
                return None

    except Exception as e:
        log.warning(f"[phone] errore Playwright su {url_annuncio}: {e}")
        return None
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        elapsed = time.monotonic() - started
        log.info(f"[phone] {url_annuncio} → {'OK' if telefono_raw else 'MISS'} in {elapsed:.1f}s")

    return normalizza_telefono_it(telefono_raw)


def estrai_telefono_subito_sync(
    url_annuncio: str,
    timeout_ms: int = 15000,
) -> Optional[str]:
    """Wrapper sincrono di estrai_telefono_subito.

    Usato dal codice sync (subito_api.py, script di backfill). Internamente
    gira asyncio.run() su un loop dedicato. NON usare dentro un event loop
    già attivo (es. dentro un endpoint async FastAPI) — usa la versione
    async direttamente in quel caso.
    """
    try:
        return asyncio.run(estrai_telefono_subito(url_annuncio, timeout_ms))
    except RuntimeError as e:
        # Già dentro a un event loop — fallback con loop dedicato in thread
        if "asyncio.run() cannot be called" in str(e) or "running event loop" in str(e):
            import threading
            result: list = [None]

            def _runner():
                result[0] = asyncio.run(estrai_telefono_subito(url_annuncio, timeout_ms))

            t = threading.Thread(target=_runner, daemon=True)
            t.start()
            t.join()
            return result[0]
        log.warning(f"[phone-sync] runtime error: {e}")
        return None
    except Exception as e:
        log.warning(f"[phone-sync] errore: {e}")
        return None
