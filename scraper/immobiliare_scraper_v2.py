# Cloudflare bypass attivo via playwright-stealth + warm-up + challenge wait
"""
HouseRadar — Immobiliare.it scraper v2 (Playwright Stealth)
============================================================
Cloudflare blocca curl_cffi e Playwright vanilla → uso playwright-stealth.

URL: https://www.immobiliare.it/vendita-case/{provincia}/?pag=N

Selettori (verificati nel browser):
- Card:    li[class*="in-listingCard"]  oppure  [data-cy="listing-item-card"]
- Prezzo:  [class*="in-listingCardPrice"]  →  €\\s*([\\d\\.]+)
- Titolo:  a[class*="in-listingCardTitle"]
- URL:     a[href*="/annunci/"]

Strategia anti-Cloudflare identica a casa_scraper.py.
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
PORTALE = "immobiliare.it"
PREFIX  = "Imm-v2"
MAX_PAGES = 50

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/121.0.0.0 Safari/537.36")


# ─── Parser ──────────────────────────────────────────────────────────────────

_RE_PREZZO = re.compile(r"€\s*([\d\.]+)")
_RE_MQ     = re.compile(r"(\d+)\s*m[²2]", re.IGNORECASE)
_RE_LOCALI = re.compile(r"(\d+)\s*local", re.IGNORECASE)


def _parse_prezzo(testo: str):
    m = _RE_PREZZO.search(testo or "")
    if not m:
        return None
    try:
        return int(m.group(1).replace(".", ""))
    except Exception:
        return None


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

    annunci = []

    # Strategia A: __NEXT_DATA__ (più affidabile se presente)
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.S,
    )
    if m:
        try:
            data = json.loads(m.group(1))
            for it in _walk_listings(data):
                rec = _from_immobiliare_json(it, provincia_hint)
                if rec:
                    annunci.append(rec)
        except Exception as e:
            log(f"  NEXT_DATA parse: {e}", prefix=PREFIX)

    # Strategia B: DOM card (fallback se NEXT_DATA assente)
    if not annunci:
        cards = soup.select('li[class*="in-listingCard"]') or \
                soup.select('[data-cy="listing-item-card"]')
        log(f"  DEBUG html_len={len(html)} cards_dom={len(cards)}", prefix=PREFIX)
        for card in cards:
            link = card.select_one('a[href*="/annunci/"]')
            if not link:
                continue
            href = link.get("href", "")
            if href.startswith("/"):
                href = "https://www.immobiliare.it" + href

            tit_el = card.select_one('a[class*="in-listingCardTitle"]')
            titolo = tit_el.get_text(strip=True) if tit_el else (link.get("title") or "")
            if not titolo:
                titolo = card.get_text(" ", strip=True)[:120]

            prz_el = card.select_one('[class*="in-listingCardPrice"]')
            prezzo = _parse_prezzo(prz_el.get_text() if prz_el else card.get_text())

            text = card.get_text(" ", strip=True)
            mq     = (int(_RE_MQ.search(text).group(1)) if _RE_MQ.search(text) else None)
            camere = (int(_RE_LOCALI.search(text).group(1)) if _RE_LOCALI.search(text) else None)

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

    # Dedup
    seen = set()
    deduped = []
    for a in annunci:
        if a["url"] in seen:
            continue
        seen.add(a["url"])
        deduped.append(a)
    return deduped


def _walk_listings(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("results", "items", "list") and isinstance(v, list):
                for it in v:
                    if isinstance(it, dict):
                        yield it
            else:
                yield from _walk_listings(v)
    elif isinstance(obj, list):
        for it in obj:
            yield from _walk_listings(it)


def _from_immobiliare_json(it: dict, hint: str):
    re_obj = it.get("realEstate") if isinstance(it.get("realEstate"), dict) else it
    if not isinstance(re_obj, dict):
        return None
    titolo = re_obj.get("title") or re_obj.get("name") or ""
    if not titolo:
        return None
    properties = re_obj.get("properties") or []
    prop = properties[0] if properties else {}

    url = re_obj.get("seoUrl") or re_obj.get("url") or it.get("seoUrl") or ""
    if url and url.startswith("/"):
        url = "https://www.immobiliare.it" + url

    pr = re_obj.get("price") or {}
    prezzo = pr.get("value") if isinstance(pr, dict) else None
    if isinstance(prezzo, (int, float)):
        prezzo = int(prezzo)
    else:
        prezzo = _parse_prezzo(str(prezzo or ""))

    mq = prop.get("surface")
    try:
        mq = int(re.sub(r"\D", "", str(mq))) if mq else None
    except Exception:
        mq = None
    cam = prop.get("rooms") or prop.get("bedRoomsNumber")
    try:
        cam = int(cam) if cam else None
    except Exception:
        cam = None

    inserz = ""
    if isinstance(re_obj.get("advertiser"), dict):
        adv = re_obj["advertiser"]
        if isinstance(adv.get("agency"), dict):
            inserz = adv["agency"].get("displayName") or adv["agency"].get("label") or ""
        else:
            inserz = adv.get("displayName") or ""

    foto = None
    multimedia = prop.get("multimedia") or {}
    if isinstance(multimedia, dict):
        photos = multimedia.get("photos") or []
        if photos and isinstance(photos[0], dict):
            foto = photos[0].get("urls", {}).get("large") or photos[0].get("url")

    return {
        "url": url,
        "titolo": titolo,
        "prezzo": prezzo,
        "mq": mq,
        "camere": cam,
        "inserzionista": inserz,
        "foto_url": foto,
        "provincia_hint": hint,
    }


# ─── Playwright Stealth ──────────────────────────────────────────────────────

def _is_cf_challenge(title: str) -> bool:
    t = (title or "").lower()
    return ("just a moment" in t) or ("verifica" in t) or ("attendere" in t)


async def _fetch_page(page, url: str) -> str:
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
            log(f"    Cloudflare ('{title}') — attendo 20s...", prefix=PREFIX)
            await page.wait_for_timeout(20000)
            title = await page.title()
            if _is_cf_challenge(title):
                if attempt == 0:
                    log("    Challenge persistente — retry", prefix=PREFIX)
                    continue
                raise RuntimeError(f"Cloudflare blocca dopo retry: {title}")
        return await page.content()
    raise RuntimeError("Fetch fallito dopo retry")


async def _scrapa_async() -> list:
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async
    except ImportError:
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

        log("Warm-up homepage...", prefix=PREFIX)
        try:
            await page.goto("https://www.immobiliare.it/", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(random.randint(2000, 4000))
        except Exception as e:
            log(f"  Warm-up error: {e}", prefix=PREFIX)

        for i, prov in enumerate(PROVINCE_TOSCANA):
            prov_label = prov.capitalize().replace("-", "-")
            log(f"\n[{i+1}/{len(PROVINCE_TOSCANA)}] Provincia: {prov_label}", prefix=PREFIX)

            for page_n in range(1, MAX_PAGES + 1):
                url = f"https://www.immobiliare.it/vendita-case/{prov}/?pag={page_n}"
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


def scrapa_immobiliare_v2() -> int:
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
    scrapa_immobiliare_v2()
