"""
Subito.it scraper — usa curl_cffi per impersonare Chrome a livello TLS
e bypassare la protezione Akamai Bot Manager.

Strategia:
- curl_cffi imposta lo stesso TLS fingerprint di Chrome (JA3/JA4 reale)
- Warm-up sulla homepage per ottenere i cookie di sessione
- Chiamata diretta all'API Hades con i cookie ricevuti
- Estrae advertiser.type == "p" per privati, "s" per agenzie
- Salva nel DB esistente (aggiunge agli annunci Idealista già presenti)
"""

import os
import json
import re
import random
import sqlite3
import time
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "propagnent.db")

# Parametri per le chiamate all'API interna di Subito.it (Hades)
# r = region (9 = Toscana), ci = city_id (Livorno=4, Pisa=7)
# advt=0 privati, advt=1 agenzie
RICERCHE = [
    {
        "label": "Livorno privati",
        "provincia": "Livorno",
        "city_id": "4",
        "advt": "0",
    },
    {
        "label": "Pisa privati",
        "provincia": "Pisa",
        "city_id": "7",
        "advt": "0",
    },
    {
        "label": "Livorno agenzie",
        "provincia": "Livorno",
        "city_id": "4",
        "advt": "1",
    },
    {
        "label": "Pisa agenzie",
        "provincia": "Pisa",
        "city_id": "7",
        "advt": "1",
    },
]

# URL base dell'API Hades di Subito.it
# c=6 = immobili (real estate), r=9 = Toscana, t=s = vendita
HADES_BASE = (
    "https://hades.subito.it/v1/search/items"
    "?c=6&r=9&t=s"
    "&lim=100&start=0"
)


def determina_zona(citta: str, provincia: str) -> str:
    c = (citta or "").lower()
    if "livorno" in c:
        return "Livorno Città"
    elif any(x in c for x in ["cecina", "rosignano", "castiglioncello"]):
        return "Costa Livornese"
    elif any(x in c for x in ["piombino", "campiglia", "san vincenzo", "populonia"]):
        return "Val di Cornia"
    elif any(x in c for x in ["elba", "portoferraio", "porto azzurro", "capoliveri", "marciana"]):
        return "Isola d'Elba"
    elif any(x in c for x in ["collesalvetti", "stagno", "vicarello"]):
        return "Hinterland Livorno"
    elif "pisa" in c:
        return "Pisa Città"
    elif any(x in c for x in ["cascina", "pontedera", "ponsacco"]):
        return "Valdera"
    elif any(x in c for x in ["volterra", "pomarance"]):
        return "Valdicecina"
    elif any(x in c for x in ["marina di pisa", "tirrenia", "calambrone"]):
        return "Litorale Pisano"
    elif any(x in c for x in ["santa croce", "fucecchio"]):
        return "Valdarno Pisano"
    return citta.title() if citta else (provincia + " Città")


def determina_tipo(titolo: str) -> str:
    t = (titolo or "").lower()
    if any(x in t for x in ["villa", "villetta", "bifamiliare"]):
        return "Villa"
    elif any(x in t for x in ["bilocale", "2 local", "due local"]):
        return "Bilocale"
    elif any(x in t for x in ["attico", "mansarda"]):
        return "Attico"
    elif any(x in t for x in ["rustico", "casale", "cascina", "fienile"]):
        return "Rustico"
    elif any(x in t for x in ["monolocale", "1 local", "uno local"]):
        return "Monolocale"
    return "Appartamento"


def estrai_features(features: list) -> dict:
    """Estrae mq, camere e prezzo dall'array features di Subito.

    I prezzi in Subito sono in euro interi (non centesimi), presenti
    nell'array features con uri='/price', non nel campo 'prices' che
    è sempre vuoto nelle risposte dell'API Hades.
    """
    mq = camere = prezzo = None
    for f in (features or []):
        uri = f.get("uri", "")
        vals = f.get("values", [])
        if not vals:
            continue
        key_val = vals[0].get("key", "")
        val = vals[0].get("value", "")
        uri_low = uri.lower()
        if uri_low in ("/price", "/prezzo") or "price" in uri_low:
            try:
                prezzo = int(re.sub(r"[^\d]", "", str(key_val)))
            except Exception:
                pass
        elif uri_low in ("/size",) or "superficie" in uri_low or "/mq" in uri_low:
            try:
                mq = int(re.sub(r"[^\d]", "", str(key_val or val)))
            except Exception:
                pass
        elif uri_low in ("/room", "/locali") or "locali" in uri_low or "camere" in uri_low or "vani" in uri_low:
            try:
                camere = int(re.sub(r"[^\d]", "", str(key_val or val)))
            except Exception:
                pass
    return {"mq": mq, "camere": camere, "prezzo": prezzo}


def genera_intel(fonte: str, giorni: int, nome: str, n_agenzie: int = 0) -> dict:
    if fonte == "privato":
        priv = f"Annuncio privato su Subito.it — nessun agente presente. Contatto con {nome or 'il proprietario'}."
        if giorni == 0:
            return {"intel_privato": priv,
                    "intel_warning": "Pubblicato oggi — sei tra i primi a vederlo. Agisci prima degli altri agenti.",
                    "ai_insight": "Nuovo di giornata. Contatto immediato massimizza le chances di esclusiva."}
        elif giorni > 60:
            return {"intel_privato": priv,
                    "intel_warning": f"Online da {giorni} giorni senza agente — alta motivazione del proprietario.",
                    "ai_insight": f"Invenduto da {giorni} giorni: ottimo momento per proporre i tuoi servizi."}
        else:
            return {"intel_privato": priv,
                    "intel_warning": "Privato attivo — contatto diretto senza concorrenza agenzie.",
                    "ai_insight": "Privato raggiungibile direttamente. Proponi visita entro 24h."}
    elif fonte == "noescl":
        return {
            "intel_privato": None,
            "intel_warning": f"Gestito da {n_agenzie} agenzie senza esclusiva — proprietario insoddisfatto.",
            "ai_insight": f"Con {n_agenzie} agenzie proponi esclusiva: la confusione di mercato abbassa il prezzo finale."
        }
    else:
        return {
            "intel_privato": None,
            "intel_warning": "Annuncio di agenzia — verifica se hanno mandato in esclusiva.",
            "ai_insight": "Contatta l'agenzia per verificare la situazione del mandato."
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
        if not url or not a.get("titolo"):
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
                is_nuovo, data_inserimento, url_originale
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            a.get("indirizzo"), a.get("indirizzo_preciso", False),
            a.get("zona"), a.get("tipo", "Appartamento"),
            a.get("mq"), a.get("camere"), a.get("prezzo"),
            a.get("giorni_online", 0),
            fonte,
            json.dumps(agenzie_list, ensure_ascii=False),
            a.get("inserzionista") if fonte == "privato" else None,
            a.get("telefono"),
            intel["intel_privato"], intel["intel_warning"], intel["ai_insight"],
            a.get("is_nuovo", True),
            ora.isoformat(), url
        ))
        nuovi += 1

    conn.commit()
    conn.close()
    return nuovi


def parse_ads_json(data: dict, provincia: str) -> list:
    """Converte la risposta JSON dell'API Subito in lista di annunci normalizzati."""
    annunci = []
    ads = data.get("ads", [])
    for a in ads:
        try:
            titolo = a.get("subject", "").strip()
            if not titolo:
                continue

            # Advertiser
            adv = a.get("advertiser", {})
            adv_type = adv.get("type", 0)
            inserzionista = adv.get("name", "").strip()
            # type "p" o 0 = privato, "s" o 1 = negozio/agenzia
            is_priv = str(adv_type) in ("p", "0") or adv_type == 0
            fonte_raw = "privato" if is_priv else "agenzia"

            # Geo
            geo = a.get("geo", {})
            citta = geo.get("city", {}).get("value", "")
            comune = geo.get("town", {}).get("value", "")
            zona = determina_zona(comune or citta, provincia)

            # Indirizzo
            indirizzo_raw = titolo
            has_via = bool(re.search(r'\b(via|viale|piazza|corso|largo|vicolo)\b', titolo, re.IGNORECASE))
            if not has_via and citta:
                indirizzo_raw = f"{titolo}, {comune or citta}"

            # Features (include prezzo — il campo 'prices' è sempre vuoto nell'API)
            feats = estrai_features(a.get("features", []))

            # URL
            urls = a.get("urls", {}) or {}
            ann_url = urls.get("default", "")

            # Tipo immobile
            tipo = determina_tipo(titolo)

            annunci.append({
                "titolo": titolo,
                "indirizzo": indirizzo_raw,
                "indirizzo_preciso": has_via,
                "zona": zona,
                "tipo": tipo,
                "mq": feats.get("mq"),
                "camere": feats.get("camere"),
                "prezzo": feats.get("prezzo"),
                "giorni_online": 0,
                "fonte_raw": fonte_raw,
                "inserzionista": inserzionista,
                "telefono": None,
                "url": ann_url,
                "is_nuovo": True,
            })
        except Exception as e:
            print(f"  Errore parsing annuncio: {e}")
            continue
    return annunci


def scrapa_subito() -> int:
    """
    Usa curl_cffi per impersonare Chrome a livello TLS e bypassare Akamai.
    1. Warm-up sulla homepage per ottenere i cookie di sessione
    2. Chiama l'API Hades direttamente con i cookie ricevuti
    """
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        print("curl_cffi non installato — esegui: pip3 install curl_cffi")
        return 0

    print(f"\n{'='*50}")
    print(f"Subito.it scraper — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"Zone: Livorno e Pisa | Metodo: curl_cffi Chrome impersonation")
    print(f"{'='*50}\n")

    # Sessione curl_cffi che impersona Chrome 120
    session = cffi_requests.Session(impersonate="chrome120")
    session.headers.update({
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    })

    # ── Warm-up: homepage Subito.it per far settare i cookie di sessione ──
    print("Warm-up: homepage Subito.it...")
    try:
        r = session.get("https://www.subito.it/", timeout=20)
        print(f"  Status: {r.status_code} | Cookie ricevuti: {len(session.cookies)}")
        time.sleep(random.uniform(2, 4))
    except Exception as e:
        print(f"  Warm-up homepage fallito: {e}")

    # ── Warm-up 2: pagina categoria immobili Toscana ──
    print("Warm-up 2: pagina immobili Toscana...")
    try:
        r2 = session.get(
            "https://www.subito.it/annunci-toscana/vendita/immobili/",
            headers={
                "Referer": "https://www.subito.it/",
                "Sec-Fetch-Site": "same-origin",
            },
            timeout=20,
        )
        print(f"  Status: {r2.status_code} | Cookie totali: {len(session.cookies)}")
        time.sleep(random.uniform(2, 4))
    except Exception as e:
        print(f"  Warm-up 2 fallito: {e}")

    print()

    tutti_raw = []

    for ricerca in RICERCHE:
        label = ricerca["label"]
        provincia = ricerca["provincia"]
        city_id = ricerca["city_id"]
        advt = ricerca["advt"]

        api_url = f"{HADES_BASE}&ci={city_id}&advt={advt}"
        print(f"Chiamata API: {label}")
        print(f"  URL: {api_url}")

        try:
            resp = session.get(
                api_url,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://www.subito.it/annunci-toscana/vendita/immobili/",
                    "Origin": "https://www.subito.it",
                    "Sec-Fetch-Site": "same-site",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Dest": "empty",
                },
                timeout=20,
            )
            print(f"  Status: {resp.status_code}")

            if resp.status_code == 200:
                data = resp.json()
                ads = data.get("ads", [])
                print(f"  Risposta OK: {len(ads)} ads")
                annunci = parse_ads_json(data, provincia)
                print(f"  Annunci validi: {len(annunci)}")
                tutti_raw.extend(annunci)
            else:
                print(f"  Errore HTTP {resp.status_code} — risposta: {resp.text[:200]}")

        except Exception as e:
            print(f"  Errore richiesta: {e}")

        delay = random.uniform(3, 6)
        print(f"  Pausa {delay:.1f}s...\n")
        time.sleep(delay)

    print(f"Annunci Subito.it raccolti: {len(tutti_raw)}")
    nuovi = salva_annunci(tutti_raw)
    print(f"Nuovi nel DB: {nuovi}")
    print(f"Completato — {datetime.now().strftime('%H:%M:%S')}\n")
    return nuovi


if __name__ == "__main__":
    scrapa_subito()
