"""
HouseRadar — Casa.it scraper (Playwright Stealth)
==================================================
Casa.it blocca curl_cffi con HTTP 403 → uso Playwright + playwright_stealth
per superare Cloudflare bot detection.

Selettori (verificati gennaio 2026):
- Card:    .csaSrpcard
- Link:    a[href*="/immobili/"]   →  /immobili/{ID}/
- Box:     .csaSrpcard__det__cont   ("€ 900.000 400 m² 6 locali 3 bagni")
- Prezzo:  .csaSrpcard__det__feats__text.first  →  €\\s*([\\d\\.]+)

Strategia anti-Cloudflare:
- chromium.launch headless con args anti-detection
- stealth_async sulla page
- Warm-up GET / con networkidle + sleep 2-4s
- Detect challenge dal title ("Just a moment", "Verifica") → wait 20s + retry 1x
- Pause 5-10s tra pagine, 15-25s tra province
"""

import os
import sys
import re
import json
import asyncio
import random
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _scraper_common import (
    log, PROVINCE_TOSCANA,
    salva_annunci_db,
)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "backend", "propagnent.db")
PORTALE = "casa.it"
PREFIX  = "Casa"
MAX_PAGES = 50

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/121.0.0.0 Safari/537.36")


# ─── Parser ──────────────────────────────────────────────────────────────────

_RE_PREZZO = re.compile(r"€\s*([\d\.]+)")
_RE_MQ     = re.compile(r"(\d+)\s*m²")
_RE_LOCALI = re.compile(r"(\d+)\s*locali", re.IGNORECASE)
_RE_BAGNI  = re.compile(r"(\d+)\s*bagn", re.IGNORECASE)


def _parse_prezzo(testo: str):
    m = _RE_PREZZO.search(testo or "")
    if not m:
        return None
    try:
        return int(m.group(1).replace(".", ""))
    except Exception:
        return None


def _build_jsonld_index(soup) -> dict:
    """Estrae da @graph i blocchi residenziali e li indicizza per URL."""
    idx = {}
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            blob = json.loads(tag.string or "{}")
        except Exception:
            continue
        graph = blob.get("@graph") if isinstance(blob, dict) else None
        items = graph or (blob if isinstance(blob, list) else [blob])
        for it in items:
            if not isinstance(it, dict):
                continue
            t = it.get("@type")
            if t in ("SingleFamilyResidence", "Apartment", "House", "Residence"):
                url = it.get("url") or ""
                if url:
                    idx[url.rstrip("/")] = {
                        "name":     it.get("name") or "",
                        "locality": (it.get("address") or {}).get("addressLocality") or "",
                        "rooms":    it.get("numberOfRooms"),
                    }
    return idx


def parse_pagina(html: str, provincia_hint: str) -> list:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    try:
        import lxml  # noqa: F401
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    jsonld = _build_jsonld_index(soup)
    annunci = []
    cards = soup.select(".csaSrpcard")
    log(f"  DEBUG html_len={len(html)} csaSrpcard={len(cards)}", prefix=PREFIX)

    for card in cards:
        link = card.select_one('a[href*="/immobili/"]')
        if not link:
            continue
        href = link.get("href", "")
        if href.startswith("/"):
            href = "https://www.casa.it" + href
        m_id = re.search(r"/immobili/(\d+)", href)
        if m_id:
            href = f"https://www.casa.it/immobili/{m_id.group(1)}/"

        det = card.select_one(".csaSrpcard__det__cont")
        det_text = det.get_text(" ", strip=True) if det else card.get_text(" ", strip=True)

        prezzo_el = card.select_one(".csaSrpcard__det__feats__text.first")
        prezzo = _parse_prezzo(prezzo_el.get_text() if prezzo_el else det_text)

        m_mq  = _RE_MQ.search(det_text);     mq = int(m_mq.group(1))   if m_mq else None
        m_loc = _RE_LOCALI.search(det_text); camere = int(m_loc.group(1)) if m_loc else None

        titolo = ""
        meta = jsonld.get(href.rstrip("/"))
        if meta and meta.get("name"):
            titolo = meta["name"]
            if meta.get("locality") and meta["locality"] not in titolo:
                titolo = f"{titolo} — {meta['locality']}"
        else:
            t_el = card.select_one("h2, h3, .csaSrpcard__det__title")
            titolo = (t_el.get_text(strip=True) if t_el else "")[:160]
        if not titolo:
            titolo = det_text[:120]

        img = card.select_one("img")
        foto = (img.get("src") or img.get("data-src")) if img else None

        annunci.append({
            "url": href,
            "titolo": titolo,
            "prezzo": prezzo,
            "mq": mq,
            "camere": camere,
            "inserzionista": "",
            "foto_url": foto,
            "provincia_hint": provincia_hint,
        })

    seen = set()
    deduped = []
    for a in annunci:
        if a["url"] in seen:
            continue
        seen.add(a["url"])
        deduped.append(a)
    return deduped


# ─── Playwright Stealth ──────────────────────────────────────────────────────

def _is_cf_challenge(title: str) -> bool:
    t = (title or "").lower()
    return ("just a moment" in t) or ("verifica" in t) or ("attendere" in t)


async def _fetch_page(page, url: str) -> str:
    """Fetch single page, gestisce Cloudflare challenge con retry 1x."""
    for attempt in range(2):
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            log(f"    goto error: {e}", prefix=PREFIX)
            if attempt == 0:
                await page.wait_for_timeout(5000)
                continue
            raise

        title = await page.title()
        if _is_cf_challenge(title):
            log(f"    Cloudflare challenge ('{title}') — attendo 20s...", prefix=PREFIX)
            await page.wait_for_timeout(20000)
            title = await page.title()
            if _is_cf_challenge(title):
                if attempt == 0:
                    log("    Challenge ancora attivo — retry", prefix=PREFIX)
                    continue
                raise RuntimeError(f"Cloudflare blocca dopo retry: {title}")
        return await page.content()
    raise RuntimeError("Fetch fallito dopo retry")


async def _scrapa_async() -> list:
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async
    except ImportError:
        # Fallback: continua senza stealth (verrà bloccato ma logga chiaramente)
        async def stealth_async(_p):
            return None

    tutti = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=UA,
            locale="it-IT",
            timezone_id="Europe/Rome",
            extra_http_headers={"Accept-Language": "it-IT,it;q=0.9"},
        )
        page = await context.new_page()
        await stealth_async(page)

        # Warm-up homepage
        log("Warm-up homepage...", prefix=PREFIX)
        try:
            await page.goto("https://www.casa.it/", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(random.randint(2000, 4000))
        except Exception as e:
            log(f"  Warm-up error: {e}", prefix=PREFIX)

        for i, prov in enumerate(PROVINCE_TOSCANA):
            prov_label = prov.capitalize().replace("-", "-")
            log(f"\n[{i+1}/{len(PROVINCE_TOSCANA)}] Provincia: {prov_label}", prefix=PREFIX)

            for page_n in range(1, MAX_PAGES + 1):
                url = f"https://www.casa.it/vendita/residenziale/{prov}-provincia/?page={page_n}"
                log(f"  Pagina {page_n}: {url}", prefix=PREFIX)
                try:
                    html = await _fetch_page(page, url)
                    ann = parse_pagina(html, prov_label)
                    log(f"    → {len(ann)} annunci", prefix=PREFIX)
                    if not ann:
                        log("    Pagina vuota — stop", prefix=PREFIX)
                        break
                    tutti.extend(ann)
                except Exception as e:
                    log(f"    Errore: {e} — passo a prossima provincia", prefix=PREFIX)
                    break
                await page.wait_for_timeout(random.randint(5000, 10000))

            if i < len(PROVINCE_TOSCANA) - 1:
                inter = random.randint(15000, 25000)
                log(f"  Pausa inter-provincia: {inter/1000:.1f}s", prefix=PREFIX)
                await page.wait_for_timeout(inter)

        await browser.close()
    return tutti


def scrapa_casa() -> int:
    log(f"Avvio scraping {PORTALE} (Playwright Stealth) — "
        f"{datetime.now().strftime('%d/%m/%Y %H:%M')}", prefix=PREFIX)
    log(f"Province: {len(PROVINCE_TOSCANA)}", prefix=PREFIX)
    try:
        tutti = asyncio.run(_scrapa_async())
    except Exception as e:
        log(f"Errore generale Playwright: {e}", prefix=PREFIX)
        return 0
    log(f"Totale raccolti: {len(tutti)}", prefix=PREFIX)
    nuovi = salva_annunci_db(tutti, DB_PATH, PORTALE)
    log(f"Nuovi inseriti: {nuovi}", prefix=PREFIX)
    return nuovi


if __name__ == "__main__":
    scrapa_casa()
