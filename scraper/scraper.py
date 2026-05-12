"""
Scraper PropAgent AI — Idealista.it
Zone: Livorno e Pisa (Toscana)
Funziona con HTTP standard (no Playwright necessario).
"""

import os
import sqlite3
import json
import re
import sys
import time
import random
import urllib.request
import urllib.error
import http.cookiejar
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "propagnent.db")

# Import normalizza_annuncio (Sprint 5.0.2 SX)
_BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
try:
    from geo.comuni_toscana import normalizza_annuncio
except Exception:
    def normalizza_annuncio(indirizzo, zona=None):
        return None, None

# Tutte le 10 province toscane × paginazione dinamica fino a MAX_PAGES.
# Con esegui_scraper esce dal loop pagine appena trova una pagina vuota.
PROVINCE_TOSCANA = [
    "livorno", "pisa", "firenze", "siena", "arezzo",
    "lucca", "grosseto", "pistoia", "prato", "massa-carrara",
]
MAX_PAGES = 50

# Per retrocompatibilità: la lista viene ricalcolata dinamicamente in esegui_scraper.
URLS_DA_SCRAPARE = [
    (f"https://www.idealista.it/vendita-case/{prov}-provincia/?num_page={page}",
     prov.capitalize().replace("-", "-"))
    for prov in PROVINCE_TOSCANA
    for page in range(1, 4)  # solo per riferimento — esegui_scraper itera in modo dinamico
]

SESSION_HEADERS = [
    ("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    ("Accept", "text/html,application/xhtml+xml,*/*;q=0.9,image/avif,image/webp,*/*;q=0.8"),
    ("Accept-Language", "it-IT,it;q=0.9,en-US;q=0.7,en;q=0.5"),
    ("Accept-Encoding", "identity"),
    ("Connection", "keep-alive"),
    ("Upgrade-Insecure-Requests", "1"),
    ("Sec-Fetch-Dest", "document"),
    ("Sec-Fetch-Mode", "navigate"),
    ("Sec-Fetch-Site", "none"),
    ("Sec-Fetch-User", "?1"),
]

def crea_sessione():
    """Crea opener con sessione cookie, visita la homepage per inizializzarla."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = SESSION_HEADERS
    try:
        with opener.open("https://www.idealista.it/", timeout=15) as r:
            print(f"  Sessione inizializzata (cookie: {len(list(jar))})")
    except Exception as e:
        print(f"  Avviso sessione homepage: {e}")
    return opener

PAROLE_AGENZIA = [
    "agenzia", "immobiliare", "srl", "s.r.l", "snc", "sas", "spa",
    "studio", "group", "real estate", "casa", "property", "invest",
    "gestioni", "consulenza", "tecnocasa", "gabetti", "remax", "re/max",
    "coldwell", "century", "engel", "volkers", "mediocasa",
    "frimm", "professionisti", "associati", "costruzioni", "sviluppo"
]


def strip_tags(s: str) -> str:
    return re.sub(r'<[^>]+>', '', s or '').strip().replace('\n', ' ')


def is_agenzia(nome: str) -> bool:
    if not nome:
        return False
    nome_l = nome.lower()
    return any(p in nome_l for p in PAROLE_AGENZIA)


def estrai_prezzo(testo: str):
    t = re.sub(r'[€\.\s]', '', testo or '')
    m = re.search(r'(\d{4,9})', t)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    return None


def estrai_mq(dettagli: list):
    for d in dettagli:
        m = re.search(r'(\d+)\s*m[q²2]?', d, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def estrai_camere(dettagli: list):
    for d in dettagli:
        m = re.search(r'(\d+)\s*(local[ei]|camere?|vani?)', d, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def determina_zona(titolo: str, provincia_hint: str) -> str:
    t = (titolo or "").lower()
    if any(x in t for x in ["livorno"]):
        return "Livorno Città"
    elif any(x in t for x in ["cecina", "rosignano", "castiglioncello"]):
        return "Costa Livornese"
    elif any(x in t for x in ["piombino", "campiglia", "san vincenzo", "populonia"]):
        return "Val di Cornia"
    elif any(x in t for x in ["elba", "portoferraio", "porto azzurro", "capoliveri", "marciana"]):
        return "Isola d'Elba"
    elif any(x in t for x in ["collesalvetti", "stagno", "vicarello"]):
        return "Hinterland Livorno"
    elif any(x in t for x in ["pisa"]):
        return "Pisa Città"
    elif any(x in t for x in ["cascina", "pontedera", "ponsacco"]):
        return "Valdera"
    elif any(x in t for x in ["volterra", "pomarance"]):
        return "Valdicecina"
    elif any(x in t for x in ["santa croce", "fucecchio", "empoli"]):
        return "Valdarno Pisano"
    elif any(x in t for x in ["marina di pisa", "tirrenia", "calambrone"]):
        return "Litorale Pisano"
    elif provincia_hint == "Pisa":
        return "Pisa Città"
    else:
        return "Livorno Città"


def determina_tipo(titolo: str) -> str:
    t = (titolo or "").lower()
    if any(x in t for x in ["villa", "villetta", "bifamiliare"]):
        return "Villa"
    elif any(x in t for x in ["bilocale", "2 local"]):
        return "Bilocale"
    elif any(x in t for x in ["attico", "mansarda"]):
        return "Attico"
    elif any(x in t for x in ["rustico", "casale", "cascina", "fienile"]):
        return "Rustico"
    elif any(x in t for x in ["monolocale", "1 local", "studio"]):
        return "Monolocale"
    else:
        return "Appartamento"


def estrai_indirizzo(titolo: str):
    """Ritorna (indirizzo, preciso). Se il titolo contiene Via/Piazza/ecc è preciso."""
    m = re.search(r'(via|viale|piazza|corso|largo|vicolo|loc\.|localit[àa])\s+[\w\s,\.\-]+', titolo, re.IGNORECASE)
    if m:
        return titolo.strip(), True
    return titolo.strip(), False


def genera_intel(fonte: str, giorni: int, inserzionista: str, n_agenzie: int = 0) -> dict:
    if fonte == "privato":
        intel_priv = f"Annuncio privato su Idealista.it — nessun agente presente. Contatto diretto con {inserzionista or 'il proprietario'}."
        if giorni == 0:
            return {
                "intel_privato": intel_priv,
                "intel_warning": "Pubblicato oggi — sei tra i primi a vederlo. Agisci prima degli altri agenti.",
                "ai_insight": "Nuovo di giornata. Contatto immediato massimizza le chances di esclusiva."
            }
        elif giorni > 60:
            return {
                "intel_privato": intel_priv,
                "intel_warning": f"Online da {giorni} giorni senza agente — proprietario probabilmente frustrato.",
                "ai_insight": f"Invenduto da {giorni} giorni: ottimo momento per proporre i tuoi servizi."
            }
        else:
            return {
                "intel_privato": intel_priv,
                "intel_warning": "Privato attivo — concorrenza bassa, contatto diretto disponibile.",
                "ai_insight": "Privato raggiungibile senza intermediari. Proponi visita entro 24h."
            }
    elif fonte == "noescl":
        return {
            "intel_privato": None,
            "intel_warning": f"Gestito da {n_agenzie} agenzie senza esclusiva — proprietario insoddisfatto.",
            "ai_insight": f"Con {n_agenzie} agenzie in gioco proponi esclusiva con piano marketing concreto. Argomento chiave: la confusione di mercato abbassa il prezzo finale."
        }
    else:
        return {
            "intel_privato": None,
            "intel_warning": "Annuncio di agenzia — verifica se hanno mandato in esclusiva.",
            "ai_insight": "Contatta l'agenzia per verificare la situazione del mandato."
        }


def fetch_html(opener, url: str) -> str:
    req = urllib.request.Request(url, headers={"Referer": "https://www.idealista.it/"})
    with opener.open(req, timeout=20) as resp:
        raw = resp.read()
        return raw.decode("utf-8", errors="ignore")


def parse_pagina(html: str, provincia_hint: str) -> list:  # noqa: C901
    """Estrae annunci da una pagina Idealista."""
    annunci = []
    articles = re.findall(
        r'<article[^>]*data-element-id="(\d+)"[^>]*>(.*?)</article>',
        html, re.DOTALL
    )

    for adid, body in articles:
        try:
            # URL e titolo
            a_m = re.search(r'href="(/immobile/' + adid + r'/[^"]*)"[^>]*>(.*?)</a>', body, re.DOTALL)
            if not a_m:
                a_m = re.search(r'href="(/immobile/[^"]+)"[^>]*>(.*?)</a>', body, re.DOTALL)
            href = a_m.group(1) if a_m else f"/immobile/{adid}/"
            titolo = strip_tags(a_m.group(2) if a_m else "")

            # Prezzo
            price_m = re.search(r'class="[^"]*item-price[^"]*"[^>]*>(.*?)</(?:span|div)>', body, re.DOTALL)
            prezzo = estrai_prezzo(strip_tags(price_m.group(1))) if price_m else None

            # Dettagli (locali, mq, piano)
            dettagli_raw = re.findall(r'class="[^"]*item-detail[^"]*"[^>]*>(.*?)</span>', body, re.DOTALL)
            dettagli = [strip_tags(d) for d in dettagli_raw if strip_tags(d)]

            mq = estrai_mq(dettagli)
            camere = estrai_camere(dettagli)

            # Rilevamento privato vs agenzia
            # Cerchiamo "Privato" in prossimità di tag di contatto nell'article
            # Tutti gli altri casi → agenzia (default corretto su Idealista)
            priv_m = re.search(
                r'(?:contact|seller|advertiser|inserzionista)[^>]*>[^<]{0,60}[Pp]rivat',
                body, re.DOTALL
            )
            if not priv_m:
                # Controllo alternativo: "Privato" vicino a icone utente o link profilo
                priv_m = re.search(r'icon-user[^>]*>[^<]*[Pp]rivat|[Pp]rivato[^<]{0,30}(?:venditor|annuncio)', body, re.DOTALL)

            if priv_m:
                inserzionista = "Privato"
            else:
                # Default agenzia — recupera nome se disponibile
                logo_text = re.search(r'class="[^"]*logo-text[^"]*"[^>]*>(.*?)</span>', body, re.DOTALL)
                if logo_text and strip_tags(logo_text.group(1)):
                    inserzionista = strip_tags(logo_text.group(1))
                else:
                    inserzionista = "Agenzia"

            annunci.append({
                "id_idealista": adid,
                "titolo": titolo,
                "url": f"https://www.idealista.it{href}",
                "prezzo": prezzo,
                "dettagli": dettagli,
                "mq": mq,
                "camere": camere,
                "inserzionista": inserzionista,
                "provincia_hint": provincia_hint,
            })
        except Exception as e:
            print(f"  Errore parsing item {adid}: {e}")
            continue

    return annunci


def salva_nel_db(annunci_raw: list) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    nuovi = 0
    ora = datetime.now()

    # Raggruppa annunci di agenzie per titolo (rilevamento non-esclusiva)
    # Usa (titolo, url) per evitare falsi positivi da listing ripetuti su più pagine
    per_titolo: dict = {}
    seen_urls: set = set()
    for a in annunci_raw:
        url = a.get("url", "")
        if url in seen_urls:
            continue  # stesso annuncio su pagine diverse, ignora
        ins = a.get("inserzionista", "")
        if is_agenzia(ins):
            key = a["titolo"][:60].lower().strip()
            per_titolo.setdefault(key, []).append(a)
        seen_urls.add(url)

    for a in annunci_raw:
        url = a.get("url", "")
        titolo = a.get("titolo", "")
        if not url or not titolo:
            continue

        cur.execute("SELECT id FROM annunci WHERE url_originale = ?", (url,))
        if cur.fetchone():
            continue

        ins = a.get("inserzionista", "")
        fonte_raw = "agenzia" if is_agenzia(ins) else "privato"

        key = titolo[:50].lower().strip()
        agenzie_list = []
        if fonte_raw == "agenzia" and key in per_titolo and len(per_titolo[key]) > 1:
            fonte = "noescl"
            agenzie_list = list({x["inserzionista"] for x in per_titolo[key] if x["inserzionista"]})
        else:
            fonte = fonte_raw

        indirizzo, preciso = estrai_indirizzo(titolo)
        zona = determina_zona(titolo, a.get("provincia_hint", ""))
        tipo = determina_tipo(titolo)
        intel = genera_intel(fonte, 0, ins, len(agenzie_list))
        citta_n, provincia_n = normalizza_annuncio(indirizzo, zona)

        cur.execute("""
            INSERT INTO annunci (
                indirizzo, indirizzo_preciso, zona, tipo, mq, camere,
                prezzo, giorni_online, fonte, agenzie, proprietario, telefono,
                intel_privato, intel_warning, ai_insight,
                is_nuovo, data_inserimento, url_originale, portale,
                citta, provincia
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            indirizzo, preciso, zona, tipo,
            a.get("mq"), a.get("camere"), a.get("prezzo"),
            0, fonte,
            json.dumps(agenzie_list, ensure_ascii=False),
            ins if fonte == "privato" else None,
            None,
            intel["intel_privato"], intel["intel_warning"], intel["ai_insight"],
            True, ora.isoformat(), url, "idealista.it",
            citta_n, provincia_n,
        ))
        nuovi += 1

    conn.commit()
    conn.close()
    return nuovi


def esegui_scraper() -> int:
    print(f"\n{'='*50}")
    print(f"Avvio scraping Idealista — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"Province toscane: {len(PROVINCE_TOSCANA)} (max {MAX_PAGES} pag/cad)")
    print(f"{'='*50}\n")

    tutti = []
    opener = crea_sessione()
    time.sleep(2)

    for i, prov in enumerate(PROVINCE_TOSCANA):
        prov_label = prov.capitalize().replace("-", "-")
        print(f"\n>>> [{i+1}/{len(PROVINCE_TOSCANA)}] Provincia: {prov_label}")
        for page in range(1, MAX_PAGES + 1):
            url = f"https://www.idealista.it/vendita-case/{prov}-provincia/?num_page={page}"
            print(f"  Pagina {page}: {url}")
            try:
                html = fetch_html(opener, url)
                annunci = parse_pagina(html, prov_label)
                print(f"    → {len(annunci)} annunci")
                if not annunci:
                    print("    Pagina vuota — stop paginazione")
                    break
                tutti.extend(annunci)
            except urllib.error.HTTPError as e:
                print(f"    HTTP {e.code}: {e.reason} — passo a prossima provincia")
                break
            except Exception as e:
                print(f"    Errore: {e} — passo a prossima provincia")
                break
            time.sleep(random.uniform(3, 7))
        if i < len(PROVINCE_TOSCANA) - 1:
            inter = random.uniform(10, 15)
            print(f"  Pausa inter-provincia: {inter:.1f}s")
            time.sleep(inter)

    print(f"\nTotale annunci raccolti: {len(tutti)}")
    nuovi = salva_nel_db(tutti)
    print(f"Nuovi inseriti nel DB: {nuovi}")
    print(f"Scraping completato — {datetime.now().strftime('%H:%M:%S')}\n")
    return nuovi


async def esegui_tutto() -> dict:
    """Esegui Idealista + Subito.it e restituisce conteggi."""
    import asyncio
    from subito_api import scrapa_subito

    print("\n>>> FASE 1: Idealista.it <<<")
    n_idealista = esegui_scraper()

    print("\n>>> FASE 2: Subito.it <<<")
    n_subito = await scrapa_subito()

    return {"idealista": n_idealista, "subito": n_subito, "totale": n_idealista + n_subito}


if __name__ == "__main__":
    import asyncio
    result = asyncio.run(esegui_tutto())
    print(f"\nRiepilogo finale: Idealista={result['idealista']} | Subito={result['subito']} | Totale={result['totale']}")
