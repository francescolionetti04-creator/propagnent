"""
HouseRadar — Immobiliare.it scraper
Usa requests + BeautifulSoup per estrarre il JSON inline nelle pagine React.

Strategia:
- La pagina è server-side rendered: il JSON è già nell'HTML dentro uno <script>
  senza src e senza id, con contenuto che inizia con window.__NEXT_DATA__ o contiene
  la chiave "realEstate". Nessun JS dinamico necessario.
- Paginazione con ?pag=N (25 annunci/pagina), fino a 8 pagine per città (200 ann.)
- Rilevamento non-esclusiva: se lo stesso indirizzo compare con 2+ agenzie diverse
  → fonte = "noescl"
"""

import os
import sys
import re
import json
import time
import random
import sqlite3
from datetime import datetime

import requests
from bs4 import BeautifulSoup

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend", "propagnent.db")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

RICERCHE = [
    {"label": "Livorno",  "slug": "livorno",  "provincia": "Livorno"},
    {"label": "Pisa",     "slug": "pisa",      "provincia": "Pisa"},
]

MAX_PAGINE = 8  # 8 × 25 = 200 annunci per città


# ─────────────────────────────────────────────────────────────────────────────
# Helpers geografici/tipologici (allineati con subito_api.py)
# ─────────────────────────────────────────────────────────────────────────────

def determina_zona(citta: str, macrozona: str, provincia: str) -> str:
    testo = (f"{citta} {macrozona}").lower()
    if any(x in testo for x in ["livorno", "ardenza", "antignano", "montenero", "shangai", "fiorentina"]):
        return "Livorno Città"
    if any(x in testo for x in ["cecina", "rosignano", "castiglioncello"]):
        return "Costa Livornese"
    if any(x in testo for x in ["piombino", "campiglia", "san vincenzo", "suvereto", "populonia"]):
        return "Val di Cornia"
    if any(x in testo for x in ["elba", "portoferraio", "porto azzurro", "capoliveri", "marciana"]):
        return "Isola d'Elba"
    if any(x in testo for x in ["collesalvetti", "stagno", "vicarello"]):
        return "Hinterland Livorno"
    if any(x in testo for x in ["pisa", "san giuliano", "cascine"]):
        return "Pisa Città"
    if any(x in testo for x in ["cascina", "pontedera", "ponsacco", "calcinaia", "capannoli"]):
        return "Valdera"
    if any(x in testo for x in ["volterra", "pomarance", "cecina val"]):
        return "Valdicecina"
    if any(x in testo for x in ["marina di pisa", "tirrenia", "calambrone", "marina"]):
        return "Litorale Pisano"
    if any(x in testo for x in ["santa croce", "fucecchio", "san miniato"]):
        return "Valdarno Pisano"
    return f"{provincia} Città"


def determina_tipo(nome_tipologia: str) -> str:
    t = (nome_tipologia or "").lower()
    if any(x in t for x in ["villa", "bifamiliare"]):
        return "Villa"
    if "bilocale" in t:
        return "Bilocale"
    if any(x in t for x in ["attico", "mansarda", "superattico"]):
        return "Attico"
    if any(x in t for x in ["rustico", "casale", "cascina", "fienile", "trullo", "masseria"]):
        return "Rustico"
    if "monolocale" in t:
        return "Monolocale"
    if any(x in t for x in ["box", "garage", "posto auto"]):
        return "Box/Garage"
    if "terreno" in t:
        return "Terreno"
    if "negozio" in t:
        return "Negozio"
    return "Appartamento"


def parse_mq(surface_str: str):
    """Estrae numero da '85 m²' → 85"""
    if not surface_str:
        return None
    m = re.search(r"(\d[\d.]*)", surface_str.replace(".", ""))
    return int(m.group(1)) if m else None


def parse_rooms(rooms_str: str):
    """Estrae numero da '3' o '3 locali' → 3"""
    if not rooms_str:
        return None
    m = re.search(r"(\d+)", str(rooms_str))
    return int(m.group(1)) if m else None


# ─────────────────────────────────────────────────────────────────────────────
# Estrazione JSON dalla pagina
# ─────────────────────────────────────────────────────────────────────────────

def estrai_risultati_dalla_pagina(html: str) -> list:
    """
    Trova lo script inline che contiene '__NEXT_DATA__' oppure la chiave 'realEstate'
    ed estrae la lista di risultati.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Prima prova: cerca script con id="__NEXT_DATA__"
    script_tag = soup.find("script", attrs={"id": "__NEXT_DATA__"})

    # Seconda prova: script senza src che contiene "realEstate"
    if not script_tag:
        for tag in soup.find_all("script", src=False):
            content = tag.string or ""
            if '"realEstate"' in content:
                script_tag = tag
                break

    if not script_tag or not script_tag.string:
        return []

    try:
        data = json.loads(script_tag.string)
    except json.JSONDecodeError as e:
        print(f"  JSON parse error: {e}")
        return []

    # Naviga fino ai risultati — struttura Next.js
    try:
        queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
        for q in queries:
            stato = q.get("state", {}).get("data", {})
            if "results" in stato:
                return stato["results"]
            # Talvolta annidato più in profondità
            for key in ("searchResults", "listing"):
                if key in stato:
                    inner = stato[key]
                    if isinstance(inner, dict) and "results" in inner:
                        return inner["results"]
    except (KeyError, TypeError):
        pass

    return []


# ─────────────────────────────────────────────────────────────────────────────
# Conversione result → dict annuncio normalizzato
# ─────────────────────────────────────────────────────────────────────────────

def result_to_annuncio(result: dict, provincia: str) -> dict | None:
    try:
        re_data = result.get("realEstate", {})
        if not re_data:
            return None

        ann_id = re_data.get("id")

        # ── Tipo inserzionista ──────────────────────────────────────────────
        advertiser = re_data.get("advertiser", {})
        has_agency = "agency" in advertiser
        fonte_raw = "agenzia" if has_agency else "privato"
        inserzionista = ""
        if has_agency:
            inserzionista = advertiser.get("agency", {}).get("displayName", "").strip()
        else:
            inserzionista = advertiser.get("name", "").strip()

        # ── Prezzo ─────────────────────────────────────────────────────────
        prezzo = None
        price_block = re_data.get("price", {})
        price_value = price_block.get("value", {})
        if isinstance(price_value, dict):
            main = price_value.get("main")
            if main is not None:
                try:
                    prezzo = int(main)
                except (ValueError, TypeError):
                    # prova dal formattedValue: "€ 195.000"
                    fv = price_block.get("formattedValue", "")
                    m = re.sub(r"[^\d]", "", fv)
                    prezzo = int(m) if m else None

        # ── Superficie e camere ─────────────────────────────────────────────
        props = re_data.get("properties", [{}])
        prop = props[0] if props else {}
        mq = parse_mq(prop.get("surface", ""))
        camere = parse_rooms(prop.get("rooms"))

        # ── Tipo immobile ───────────────────────────────────────────────────
        tipologia = re_data.get("typology", {}).get("name", "")
        tipo = determina_tipo(tipologia)

        # ── Localizzazione ──────────────────────────────────────────────────
        location = re_data.get("location", {})
        citta = location.get("city", "")
        address = location.get("address", "").strip()
        macrozona_obj = location.get("macrozone") or [{}]
        if isinstance(macrozona_obj, list):
            macrozona = macrozona_obj[0].get("name", "") if macrozona_obj else ""
        else:
            macrozona = macrozona_obj.get("name", "")

        zona = determina_zona(citta, macrozona, provincia)

        # Indirizzo: usa address se presente (preciso), altrimenti titolo + città
        has_via = bool(address and re.search(r'\b(via|viale|piazza|corso|largo|vicolo)\b', address, re.IGNORECASE))
        if address:
            indirizzo = address
            if citta and citta.lower() not in address.lower():
                indirizzo = f"{address}, {citta}"
        else:
            title = re_data.get("title", "") or tipologia or "Immobile"
            indirizzo = f"{title}, {citta}" if citta else title

        # ── URL annuncio ────────────────────────────────────────────────────
        seo = result.get("seo", {})
        url = seo.get("url", "")
        if url and not url.startswith("http"):
            url = "https://www.immobiliare.it" + url

        if not url:
            return None

        # ── Foto (fino a 5) ─────────────────────────────────────────────────
        multimedia = re_data.get("multimedia", {})
        photos = multimedia.get("photos", []) or []
        foto_list = []
        for ph in photos[:5]:
            urls_ph = ph.get("urls", {}) or {}
            img_url = (
                urls_ph.get("large")
                or urls_ph.get("medium")
                or urls_ph.get("small")
                or ""
            )
            if img_url:
                foto_list.append(img_url)
        foto_url = json.dumps(foto_list) if foto_list else None

        return {
            "id_portale": ann_id,
            "indirizzo": indirizzo,
            "indirizzo_preciso": has_via,
            "zona": zona,
            "tipo": tipo,
            "mq": mq,
            "camere": camere,
            "prezzo": prezzo,
            "giorni_online": 0,
            "fonte_raw": fonte_raw,
            "inserzionista": inserzionista,
            "url": url,
            "foto_url": foto_url,
            "is_nuovo": True,
        }
    except Exception as e:
        print(f"  Errore parsing result: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Salvataggio nel DB (logica noescl identica a subito_api.py)
# ─────────────────────────────────────────────────────────────────────────────

def genera_intel(fonte: str, giorni: int, inserzionista: str, n_agenzie: int) -> dict:
    fonte_tag = "Immobiliare.it"
    if fonte == "privato":
        priv = f"Annuncio privato su {fonte_tag} — nessun agente presente. Contatto con {inserzionista or 'il proprietario'}."
        if giorni == 0:
            return {
                "intel_privato": priv,
                "intel_warning": "Pubblicato oggi — sei tra i primi a vederlo. Agisci prima degli altri agenti.",
                "ai_insight": "Nuovo di giornata su Immobiliare.it. Contatto immediato massimizza le chances di esclusiva.",
            }
        elif giorni > 60:
            return {
                "intel_privato": priv,
                "intel_warning": f"Online da {giorni} giorni senza agente — alta motivazione del proprietario.",
                "ai_insight": f"Invenduto da {giorni} giorni: ottimo momento per proporre i tuoi servizi.",
            }
        else:
            return {
                "intel_privato": priv,
                "intel_warning": f"Privato su {fonte_tag} — contatto diretto senza concorrenza agenzie.",
                "ai_insight": "Privato raggiungibile direttamente. Proponi visita entro 24h.",
            }
    elif fonte == "noescl":
        return {
            "intel_privato": None,
            "intel_warning": f"Gestito da {n_agenzie} agenzie su {fonte_tag} senza esclusiva confermata.",
            "ai_insight": f"Con {n_agenzie} agenzie proponi esclusiva: la confusione di mercato abbassa il prezzo finale.",
        }
    else:
        return {
            "intel_privato": None,
            "intel_warning": f"Annuncio di agenzia su {fonte_tag} — verifica mandato esclusiva.",
            "ai_insight": "Contatta l'agenzia per verificare la situazione del mandato.",
        }


def salva_annunci(annunci_raw: list) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    nuovi = 0
    ora = datetime.now()

    # Raggruppa agenzie per indirizzo (rilevamento non-esclusiva)
    per_indirizzo: dict = {}
    seen_urls: set = set()
    for a in annunci_raw:
        url = a.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        if a.get("fonte_raw") == "agenzia":
            key = (a.get("indirizzo", "")[:60]).lower().strip()
            per_indirizzo.setdefault(key, []).append(a)

    for a in annunci_raw:
        url = a.get("url", "")
        if not url:
            continue

        cur.execute("SELECT id FROM annunci WHERE url_originale = ?", (url,))
        if cur.fetchone():
            continue

        fonte_raw = a["fonte_raw"]
        key = (a.get("indirizzo", "")[:60]).lower().strip()
        agenzie_list = []

        if fonte_raw == "agenzia" and key in per_indirizzo and len(per_indirizzo[key]) > 1:
            fonte = "noescl"
            agenzie_list = list({x["inserzionista"] for x in per_indirizzo[key] if x.get("inserzionista")})
        else:
            fonte = fonte_raw

        intel = genera_intel(fonte, a.get("giorni_online", 0), a.get("inserzionista", ""), len(agenzie_list))

        cur.execute("""
            INSERT INTO annunci (
                indirizzo, indirizzo_preciso, zona, tipo, mq, camere,
                prezzo, giorni_online, fonte, agenzie, proprietario, telefono,
                intel_privato, intel_warning, ai_insight,
                is_nuovo, data_inserimento, url_originale, foto_url, portale
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            a.get("indirizzo"), a.get("indirizzo_preciso", False),
            a.get("zona"), a.get("tipo", "Appartamento"),
            a.get("mq"), a.get("camere"), a.get("prezzo"),
            a.get("giorni_online", 0),
            fonte,
            json.dumps(agenzie_list, ensure_ascii=False),
            a.get("inserzionista") if fonte == "privato" else None,
            None,  # telefono (non presente su immobiliare.it)
            intel["intel_privato"], intel["intel_warning"], intel["ai_insight"],
            True,  # is_nuovo
            ora.isoformat(), url,
            a.get("foto_url"), "immobiliare.it"
        ))
        nuovi += 1

    conn.commit()
    conn.close()
    return nuovi


# ─────────────────────────────────────────────────────────────────────────────
# Scraper principale
# ─────────────────────────────────────────────────────────────────────────────

def scrapa_immobiliare() -> int:
    """
    Scrapa Immobiliare.it per Livorno e Pisa usando requests + BeautifulSoup.
    Estrae il JSON inline dalla pagina React (Next.js SSR).
    """
    print(f"\n{'='*50}")
    print(f"Immobiliare.it scraper — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"Zone: Livorno e Pisa | Metodo: requests + BeautifulSoup (JSON inline)")
    print(f"{'='*50}\n")

    session = requests.Session()
    session.headers.update(HEADERS)

    # Warm-up sulla homepage
    try:
        session.get("https://www.immobiliare.it/", timeout=15)
        print("Warm-up homepage OK")
        time.sleep(random.uniform(1.5, 3.0))
    except Exception as e:
        print(f"Warm-up fallito (non critico): {e}")

    tutti_raw = []

    for ricerca in RICERCHE:
        label = ricerca["label"]
        slug = ricerca["slug"]
        provincia = ricerca["provincia"]

        print(f"\n── {label} ──────────────────────────────")
        pag_annunci = 0

        for pag in range(1, MAX_PAGINE + 1):
            url = f"https://www.immobiliare.it/vendita-case/{slug}/?pag={pag}"
            print(f"  Pagina {pag}: {url}")

            try:
                resp = session.get(url, timeout=20)
                print(f"  Status: {resp.status_code}")

                if resp.status_code == 200:
                    risultati = estrai_risultati_dalla_pagina(resp.text)
                    print(f"  Risultati estratti: {len(risultati)}")

                    if not risultati:
                        print("  → Nessun risultato, fine paginazione")
                        break

                    for r in risultati:
                        ann = result_to_annuncio(r, provincia)
                        if ann:
                            tutti_raw.append(ann)
                            pag_annunci += 1

                elif resp.status_code == 404:
                    print("  → 404, fine paginazione")
                    break
                else:
                    print(f"  → HTTP {resp.status_code}, skip")

            except Exception as e:
                print(f"  Errore: {e}")

            delay = random.uniform(2.0, 4.5)
            print(f"  Pausa {delay:.1f}s...")
            time.sleep(delay)

        print(f"  Totale {label}: {pag_annunci} annunci")

    print(f"\nAnnunci Immobiliare.it raccolti: {len(tutti_raw)}")
    nuovi = salva_annunci(tutti_raw)
    print(f"Nuovi nel DB: {nuovi}")
    print(f"Completato — {datetime.now().strftime('%H:%M:%S')}\n")
    return nuovi


if __name__ == "__main__":
    scrapa_immobiliare()
