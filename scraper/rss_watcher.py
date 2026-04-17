"""
HouseRadar — RSS Watcher (near real-time)
Controlla i feed RSS di Subito.it ogni 5 minuti.
Inserisce solo gli annunci nuovi, senza rifare lo scraping completo.
"""
import sys
import os
import re
import time
import sqlite3
import json
from datetime import datetime

# Assicura che backend/ sia nel path per importare database.py
_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_BACKEND = os.path.join(_ROOT, "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import feedparser
import requests as _requests
from bs4 import BeautifulSoup as _BS4

DB_PATH = os.path.join(_BACKEND, "propagnent.db")

# Contatore fallimenti consecutivi per feed (evita log storm)
_fail_count: dict = {}
MAX_FAILS = 3  # dopo 3 fallimenti consecutivi, logga solo ogni 10 cicli

_RSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HouseRadar-RSSBot/1.0)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

RSS_FEEDS = [
    {
        "url": "https://www.subito.it/annunci-toscana/vendita/immobili/livorno/?feed=rss",
        "zona_default": "Livorno Città",
    },
    {
        "url": "https://www.subito.it/annunci-toscana/vendita/immobili/pisa/?feed=rss",
        "zona_default": "Pisa Città",
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# Mappatura zona dal titolo RSS
# ─────────────────────────────────────────────────────────────────────────────
_ZONE_MAP = {
    "livorno": "Livorno Città",
    "pisa": "Pisa Città",
    "piombino": "Val di Cornia",
    "follonica": "Val di Cornia",
    "portoferraio": "Isola d'Elba",
    "elba": "Isola d'Elba",
    "cecina": "Valdicecina",
    "volterra": "Valdicecina",
    "pontedera": "Valdera",
    "cascina": "Valdera",
    "viareggio": "Litorale Pisano",
    "tirrenia": "Litorale Pisano",
    "marina di pisa": "Litorale Pisano",
    "rosignano": "Costa Livornese",
    "castiglioncello": "Costa Livornese",
    "antignano": "Costa Livornese",
    "ardenza": "Livorno Città",
    "montenero": "Livorno Città",
    "collesalvetti": "Hinterland Livorno",
    "colline livornesi": "Hinterland Livorno",
}

_TIPO_MAP = {
    "appartamento": "Appartamento",
    "bilocale": "Bilocale",
    "monolocale": "Monolocale",
    "trilocale": "Appartamento",
    "quadrilocale": "Appartamento",
    "villa": "Villa",
    "villetta": "Villa",
    "attico": "Attico",
    "rustico": "Rustico",
    "casale": "Rustico",
    "box": "Box/Garage",
    "garage": "Box/Garage",
    "negozio": "Negozio",
    "ufficio": "Ufficio",
    "capannone": "Capannone",
    "terreno": "Terreno",
}


def _parse_zona(text: str, default: str) -> str:
    low = text.lower()
    for k, v in _ZONE_MAP.items():
        if k in low:
            return v
    return default


def _parse_tipo(text: str) -> str:
    low = text.lower()
    for k, v in _TIPO_MAP.items():
        if k in low:
            return v
    return "Immobile"


def _parse_prezzo(text: str):
    """Estrae il primo numero intero >= 10000 dal testo (prezzo in €)."""
    # Cerca pattern come "150.000" o "150000" o "150,000"
    matches = re.findall(r"(\d[\d.,]{3,})", text)
    for m in matches:
        cleaned = re.sub(r"[.,]", "", m)
        try:
            val = int(cleaned)
            if 10_000 <= val <= 50_000_000:
                return val
        except ValueError:
            pass
    return None


def _parse_mq(text: str):
    """Estrae i mq dal testo (es. '85 mq', '85m²')."""
    m = re.search(r"(\d{2,4})\s*(?:mq|m²|m2)", text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _parse_camere(text: str):
    """Estrae il numero di camere/locali dal testo."""
    m = re.search(r"(\d)\s*(?:camere?|locali?|vani?)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # trilocale = 3, bilocale = 2, monolocale = 1, quadrilocale = 4
    for prefisso, n in [("quadri", 4), ("tri", 3), ("bi", 2), ("mono", 1)]:
        if prefisso in text.lower():
            return n
    return None


def _url_esiste(url: str) -> bool:
    """Controlla se l'URL è già nel DB."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM annunci WHERE url_originale = ?", (url,))
        exists = cur.fetchone() is not None
        conn.close()
        return exists
    except Exception as e:
        print(f"[RSS] Errore DB check: {e}")
        return True  # sicurezza: non inserire se non possiamo verificare


def _inserisci_annuncio(a: dict) -> bool:
    """Inserisce l'annuncio nel DB. Ritorna True se inserito."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            INSERT OR IGNORE INTO annunci
            (indirizzo, indirizzo_preciso, zona, tipo, mq, camere, prezzo,
             giorni_online, fonte, agenzie, proprietario, telefono,
             intel_privato, intel_warning, ai_insight, is_nuovo, url_originale)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            a.get("indirizzo"), a.get("indirizzo_preciso", False),
            a.get("zona"), a.get("tipo"),
            a.get("mq"), a.get("camere"), a.get("prezzo"),
            0,  # giorni_online = 0 (appena trovato)
            a.get("fonte", "privato"),
            json.dumps([]),  # agenzie
            a.get("proprietario"), None,  # telefono
            a.get("intel_privato"), a.get("intel_warning"), None,  # ai_insight
            True,  # is_nuovo = True
            a.get("url_originale"),
        ))
        conn.commit()
        inserted = cur.rowcount > 0
        conn.close()
        return inserted
    except Exception as e:
        print(f"[RSS] Errore inserimento: {e}")
        return False


def _item_to_annuncio(entry, zona_default: str) -> dict:
    """Converte un entry feedparser in un dict annuncio."""
    title = entry.get("title", "")
    summary = entry.get("summary", "")
    link = entry.get("link", "")

    # Testo combinato per l'estrazione
    full_text = f"{title} {summary}"

    zona = _parse_zona(full_text, zona_default)
    tipo = _parse_tipo(title)
    prezzo = _parse_prezzo(full_text)
    mq = _parse_mq(full_text)
    camere = _parse_camere(full_text)

    # Indirizzo: usa il titolo pulito come indirizzo approssimativo
    indirizzo = re.sub(r"\s+", " ", title.strip())[:200]

    intel_privato = f"Trovato via RSS feed Subito.it — {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    intel_warning = "Annuncio rilevato in tempo reale. Verifica se è privato o agenzia."

    return {
        "indirizzo": indirizzo,
        "indirizzo_preciso": False,
        "zona": zona,
        "tipo": tipo,
        "mq": mq,
        "camere": camere,
        "prezzo": prezzo,
        "fonte": "privato",   # RSS Subito privati di default (advt=0)
        "agenzie": [],
        "proprietario": None,
        "intel_privato": intel_privato,
        "intel_warning": intel_warning,
        "url_originale": link,
    }


def _scarica_entries(url: str) -> list:
    """
    Scarica e parsa un feed RSS restituendo una lista di dict-like entry.
    Strategia a tre livelli:
      1. requests fetch + feedparser.parse(content)  → gestisce XML malformato
      2. Se entries vuote e bozo: BeautifulSoup html.parser fallback
      3. Se tutto fallisce: lista vuota (non crasha mai)
    """
    # ── Livello 1: fetch manuale + feedparser ─────────────────────────
    try:
        resp = _requests.get(url, headers=_RSS_HEADERS, timeout=15)
        resp.raise_for_status()
        content = resp.content

        feed = feedparser.parse(content)
        if feed.entries:
            if feed.bozo:
                print(f"[RSS] Feed parsato con avvisi (bozo): {type(feed.bozo_exception).__name__} — {len(feed.entries)} entry trovate comunque")
            return feed.entries

        # entries vuote: prova se è un problema di encoding
        feed2 = feedparser.parse(resp.text)
        if feed2.entries:
            return feed2.entries

    except Exception as e:
        print(f"[RSS] Fetch/feedparser errore: {e}")
        content = None

    if not content:
        return []

    # ── Livello 2: BeautifulSoup fallback per XML malformato ──────────
    print(f"[RSS] feedparser vuoto — provo BeautifulSoup fallback...")
    try:
        soup = _BS4(content, "html.parser")
        entries = []
        for item in soup.find_all("item"):
            t = item.find("title")
            # <link> in RSS è testo tra tag, non attributo
            l = item.find("link")
            g = item.find("guid")
            d = item.find("description")

            link_val = ""
            if l:
                link_val = (l.get_text(strip=True) or "").strip()
            if not link_val and g:
                link_val = g.get_text(strip=True)

            title_val = t.get_text(strip=True) if t else ""
            desc_val = d.get_text(strip=True) if d else ""

            if link_val:
                entries.append({
                    "title": title_val,
                    "link": link_val,
                    "summary": desc_val,
                })
        if entries:
            print(f"[RSS] BS4 fallback OK: {len(entries)} entry trovate")
        return entries
    except Exception as e:
        print(f"[RSS] BS4 fallback errore: {e}")
        return []


def controlla_feed(feed_cfg: dict) -> int:
    """Controlla un singolo feed RSS e inserisce i nuovi annunci. Ritorna il numero di inseriti."""
    url = feed_cfg["url"]
    zona_default = feed_cfg["zona_default"]
    nuovi = 0
    fails = _fail_count.get(url, 0)

    # Se il feed ha già fallito molte volte, logga solo ogni 10 cicli
    if fails >= MAX_FAILS and fails % 10 != 0:
        _fail_count[url] = fails + 1
        return 0

    try:
        entries = _scarica_entries(url)

        if not entries:
            _fail_count[url] = fails + 1
            if fails < MAX_FAILS or fails % 10 == 0:
                print(f"[RSS] Nessuna entry da {url} (fallimenti consecutivi: {fails + 1})")
            return 0

        # Feed OK: azzera contatore fallimenti
        _fail_count[url] = 0

        for entry in entries:
            # Compatibilità sia con feedparser Entry che con dict plain
            if isinstance(entry, dict):
                link = entry.get("link", "")
                title = entry.get("title", "")
                summary = entry.get("summary", "")
            else:
                link = entry.get("link", "")
                title = entry.get("title", "")
                summary = entry.get("summary", "")

            if not link:
                continue
            if _url_esiste(link):
                continue

            # Crea un oggetto dict-compatibile per _item_to_annuncio
            entry_dict = {"title": title, "link": link, "summary": summary}
            annuncio = _item_to_annuncio(entry_dict, zona_default)
            if _inserisci_annuncio(annuncio):
                nuovi += 1
                print(f"[RSS] Nuovo annuncio: {annuncio['indirizzo'][:60]} — {annuncio['prezzo']} €")

    except Exception as e:
        _fail_count[url] = fails + 1
        print(f"[RSS] Errore ciclo feed {url}: {e}")

    return nuovi


def ciclo_rss():
    """Esegue un singolo ciclo su tutti i feed. Ritorna il totale inseriti."""
    totale = 0
    for feed_cfg in RSS_FEEDS:
        totale += controlla_feed(feed_cfg)
    return totale


def avvia_rss_watcher(intervallo_secondi: int = 300):
    """Loop infinito: controlla i feed RSS ogni `intervallo_secondi` secondi (default 5 min)."""
    print(f"[RSS] Watcher avviato — controllo ogni {intervallo_secondi // 60} minuti")
    print(f"[RSS] Feed monitorati: {len(RSS_FEEDS)}")

    while True:
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            nuovi = ciclo_rss()
            if nuovi > 0:
                print(f"[RSS] {ts} — {nuovi} nuov{'o' if nuovi == 1 else 'i'} annunci inseriti")
            else:
                print(f"[RSS] {ts} — nessun nuovo annuncio")
        except Exception as e:
            print(f"[RSS] Errore nel ciclo: {e}")

        time.sleep(intervallo_secondi)


if __name__ == "__main__":
    avvia_rss_watcher()
