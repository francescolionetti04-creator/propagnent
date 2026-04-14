import sqlite3
import json
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "propagnent.db")

ANNUNCI_ESEMPIO = [
    {
        "indirizzo": "Via Leoncino 8, 37121 Verona",
        "indirizzo_preciso": True,
        "zona": "Verona Centro",
        "tipo": "Appartamento",
        "mq": 95, "camere": 3, "prezzo": 285000, "giorni_online": 0,
        "fonte": "privato", "agenzie": "[]",
        "proprietario": "Marco R.", "telefono": "347 ●●● ●●42",
        "intel_privato": "Annuncio pubblicato stamattina su Immobiliare.it. Nessun agente presente.",
        "intel_warning": "Zona molto richiesta — altri agenti potrebbero vederlo entro poche ore.",
        "ai_insight": "Privato puro. Prima mossa entro oggi è strategica.",
        "is_nuovo": True,
        "url_originale": "https://esempio.it/annuncio/1"
    },
    {
        "indirizzo": "Via Gardesana 44, 37016 Garda VR",
        "indirizzo_preciso": True,
        "zona": "Garda",
        "tipo": "Villa",
        "mq": 310, "camere": 5, "prezzo": 920000, "giorni_online": 18,
        "fonte": "noescl",
        "agenzie": '["Re/Max Garda", "Studio Benaco Immobiliare"]',
        "proprietario": None, "telefono": None,
        "intel_privato": None,
        "intel_warning": "Presente con 2 agenzie diverse. Nessuna ha l'esclusiva.",
        "ai_insight": "Il proprietario è stanco di gestire più agenti. Proponi mandato esclusiva.",
        "is_nuovo": False,
        "url_originale": "https://esempio.it/annuncio/2"
    },
    {
        "indirizzo": "Corso Porta Nuova 18, 37122 Verona",
        "indirizzo_preciso": True,
        "zona": "Verona Centro",
        "tipo": "Appartamento",
        "mq": 72, "camere": 2, "prezzo": 210000, "giorni_online": 3,
        "fonte": "privato", "agenzie": "[]",
        "proprietario": "Giulia T.", "telefono": "333 ●●● ●●19",
        "intel_privato": "Annuncio su Subito.it — canale non presidiato dagli agenti.",
        "intel_warning": "Zona con alta rotazione — ideale per investitore o prima casa.",
        "ai_insight": "Privato su Subito.it, raramente monitorato. Contatto immediato consigliato.",
        "is_nuovo": True,
        "url_originale": "https://esempio.it/annuncio/3"
    },
    {
        "indirizzo": "Loc. Castelrotto, Via Bure 3, 37029 San Pietro in Cariano VR",
        "indirizzo_preciso": True,
        "zona": "Valpolicella",
        "tipo": "Rustico",
        "mq": 280, "camere": 4, "prezzo": 390000, "giorni_online": 47,
        "fonte": "noescl",
        "agenzie": '["Tecnocasa Verona Ovest", "Gabetti San Pietro", "Agenzia Valpo Case"]',
        "proprietario": None, "telefono": None,
        "intel_privato": None,
        "intel_warning": "3 agenzie lo trattano. Proprietario aperto a mandati esclusivi.",
        "ai_insight": "Con 3 agenzie il proprietario è insoddisfatto. Momento ideale per esclusiva.",
        "is_nuovo": False,
        "url_originale": "https://esempio.it/annuncio/4"
    },
    {
        "indirizzo": "Via Mirabello 11, 37011 Bardolino VR",
        "indirizzo_preciso": True,
        "zona": "Bardolino",
        "tipo": "Bilocale",
        "mq": 58, "camere": 2, "prezzo": 268000, "giorni_online": 1,
        "fonte": "privato", "agenzie": "[]",
        "proprietario": "Fam. Bertolini", "telefono": "348 ●●● ●●77",
        "intel_privato": "Annuncio su Facebook Marketplace. Bilocale con terrazza vista lago.",
        "intel_warning": "Facebook Marketplace non monitorato dai portali standard — vantaggio competitivo.",
        "ai_insight": "Fonte non convenzionale. Pochissimi agenti monitorano questo canale.",
        "is_nuovo": True,
        "url_originale": "https://esempio.it/annuncio/5"
    },
    {
        "indirizzo": "Via Roma 33, 37038 Soave VR",
        "indirizzo_preciso": True,
        "zona": "Soave",
        "tipo": "Appartamento",
        "mq": 88, "camere": 3, "prezzo": 195000, "giorni_online": 22,
        "fonte": "noescl",
        "agenzie": '["Immobiliare Soave Srl", "Re/Max Verona Est"]',
        "proprietario": None, "telefono": None,
        "intel_privato": None,
        "intel_warning": "Su Idealista con 2 agenzie. Re/Max attivo da soli 5 giorni — probabile senza esclusiva.",
        "ai_insight": "Verifica se il mandato Re/Max è in esclusiva. Se no, hai spazio per subentrare.",
        "is_nuovo": False,
        "url_originale": "https://esempio.it/annuncio/6"
    },
    {
        "indirizzo": "Via Oberdan 7 (int. stimato), 37121 Verona",
        "indirizzo_preciso": False,
        "zona": "Verona Centro",
        "tipo": "Attico",
        "mq": 130, "camere": 4, "prezzo": 620000, "giorni_online": 9,
        "fonte": "privato", "agenzie": "[]",
        "proprietario": "Non indicato", "telefono": "Solo form online",
        "intel_privato": "Indirizzo stimato da AI — annuncio indica zona Veronetta con vista Arena.",
        "intel_warning": "Numero non visibile — contatto solo via form. Risposta media: 4 ore.",
        "ai_insight": "Indirizzo stimato con alta probabilità. Attico con vista Arena — valore elevato.",
        "is_nuovo": False,
        "url_originale": "https://esempio.it/annuncio/7"
    },
    {
        "indirizzo": "Via del Porto 2, 37010 Peschiera del Garda VR",
        "indirizzo_preciso": True,
        "zona": "Garda",
        "tipo": "Villa",
        "mq": 420, "camere": 6, "prezzo": 1150000, "giorni_online": 34,
        "fonte": "noescl",
        "agenzie": '["Coldwell Banker Garda", "Studio 37 Immobiliare"]',
        "proprietario": None, "telefono": None,
        "intel_privato": None,
        "intel_warning": "Prezzo calato da 1.280.000 a 1.150.000 in 30 giorni. Nessuna agenzia ha esclusiva confermata.",
        "ai_insight": "Calo del 10% con due agenzie non esclusive: il proprietario vuole chiudere.",
        "is_nuovo": False,
        "url_originale": "https://esempio.it/annuncio/8"
    },
    {
        "indirizzo": "Via Carducci 5, 37121 Verona",
        "indirizzo_preciso": True,
        "zona": "Verona Centro",
        "tipo": "Appartamento",
        "mq": 105, "camere": 3, "prezzo": 340000, "giorni_online": 5,
        "fonte": "privato", "agenzie": "[]",
        "proprietario": "Andrea M.", "telefono": "338 ●●● ●●03",
        "intel_privato": "Solo su Subito.it con prezzo trattabile. Ristrutturato 2023, foto professionali.",
        "intel_warning": "Zona Veronetta riqualificata — domanda in crescita del 14% anno su anno.",
        "ai_insight": "Privato preparato con immobile di qualità. Agire rapidamente è fondamentale.",
        "is_nuovo": False,
        "url_originale": "https://esempio.it/annuncio/9"
    }
]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS annunci (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            indirizzo TEXT NOT NULL,
            indirizzo_preciso BOOLEAN DEFAULT TRUE,
            zona TEXT,
            tipo TEXT,
            mq INTEGER,
            camere INTEGER,
            prezzo INTEGER,
            giorni_online INTEGER DEFAULT 0,
            fonte TEXT,
            agenzie TEXT,
            proprietario TEXT,
            telefono TEXT,
            intel_privato TEXT,
            intel_warning TEXT,
            ai_insight TEXT,
            is_nuovo BOOLEAN DEFAULT FALSE,
            data_inserimento TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            url_originale TEXT UNIQUE
        )
    """)
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM annunci")
    count = cur.fetchone()[0]
    if count == 0:
        for a in ANNUNCI_ESEMPIO:
            cur.execute("""
                INSERT OR IGNORE INTO annunci
                (indirizzo, indirizzo_preciso, zona, tipo, mq, camere, prezzo,
                 giorni_online, fonte, agenzie, proprietario, telefono,
                 intel_privato, intel_warning, ai_insight, is_nuovo, url_originale)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                a["indirizzo"], a["indirizzo_preciso"], a["zona"], a["tipo"],
                a["mq"], a["camere"], a["prezzo"], a["giorni_online"],
                a["fonte"], a["agenzie"], a["proprietario"], a["telefono"],
                a["intel_privato"], a["intel_warning"], a["ai_insight"],
                a["is_nuovo"], a["url_originale"]
            ))
        conn.commit()
        print(f"[DB] Inseriti {len(ANNUNCI_ESEMPIO)} annunci di esempio.")

    conn.close()


def get_annunci(zona=None, tipo=None, fonte=None, sort="new", prezzo_max=None):
    conn = get_conn()
    cur = conn.cursor()

    query = "SELECT * FROM annunci WHERE 1=1"
    params = []

    if zona:
        query += " AND (zona LIKE ? OR indirizzo LIKE ?)"
        params += [f"%{zona}%", f"%{zona}%"]
    if tipo:
        query += " AND tipo = ?"
        params.append(tipo)
    if fonte:
        query += " AND fonte = ?"
        params.append(fonte)
    if prezzo_max:
        query += " AND prezzo <= ?"
        params.append(prezzo_max)

    sort_map = {
        "new": "giorni_online ASC",
        "priv": "CASE WHEN fonte='privato' THEN 0 ELSE 1 END ASC, giorni_online ASC",
        "noescl": "CASE WHEN fonte='noescl' THEN 0 ELSE 1 END ASC, giorni_online ASC",
        "prezzo-asc": "prezzo ASC",
        "giorni": "giorni_online DESC",
    }
    query += f" ORDER BY {sort_map.get(sort, 'giorni_online ASC')}"

    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_stats():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM annunci")
    totale = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM annunci WHERE fonte='privato'")
    privati = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM annunci WHERE fonte='noescl'")
    noescl = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM annunci WHERE is_nuovo=1")
    nuovi_oggi = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM annunci WHERE indirizzo_preciso=1")
    indirizzi_precisi = cur.fetchone()[0]
    conn.close()
    return {
        "totale": totale,
        "privati": privati,
        "noescl": noescl,
        "nuovi_oggi": nuovi_oggi,
        "indirizzi_precisi": indirizzi_precisi,
    }


def get_alert():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM annunci WHERE is_nuovo=1 ORDER BY giorni_online ASC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    if not rows:
        return {"ha_alert": False, "testo": "", "annunci": []}

    privati_new = [r for r in rows if r["fonte"] == "privato"]
    noescl_new = [r for r in rows if r["fonte"] == "noescl"]

    parti = []
    if privati_new:
        zone = ", ".join(set(r["zona"] for r in privati_new))
        parti.append(f"<strong>{len(privati_new)} privat{'o' if len(privati_new)==1 else 'i'}</strong> ({zone})")
    if noescl_new:
        zone = ", ".join(set(r["zona"] for r in noescl_new))
        parti.append(f"<strong>{len(noescl_new)} non in esclusiva</strong> ({zone})")

    testo = f"<strong>{len(rows)} nuov{'o' if len(rows)==1 else 'i'} annunc{'io' if len(rows)==1 else 'i'} nelle ultime 2 ore</strong> — {' e '.join(parti)}. Controlla subito prima degli altri agenti."

    return {"ha_alert": True, "testo": testo, "annunci": rows}


def insert_annuncio(a: dict):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT OR IGNORE INTO annunci
            (indirizzo, indirizzo_preciso, zona, tipo, mq, camere, prezzo,
             giorni_online, fonte, agenzie, proprietario, telefono,
             intel_privato, intel_warning, ai_insight, is_nuovo, url_originale)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            a.get("indirizzo"), a.get("indirizzo_preciso", True),
            a.get("zona"), a.get("tipo"),
            a.get("mq"), a.get("camere"), a.get("prezzo"),
            a.get("giorni_online", 0), a.get("fonte", "agenzia"),
            json.dumps(a.get("agenzie", [])) if isinstance(a.get("agenzie"), list) else a.get("agenzie", "[]"),
            a.get("proprietario"), a.get("telefono"),
            a.get("intel_privato"), a.get("intel_warning"), a.get("ai_insight"),
            a.get("is_nuovo", False), a.get("url_originale")
        ))
        conn.commit()
        inserted = cur.rowcount > 0
    except Exception as e:
        print(f"[DB] Errore inserimento: {e}")
        inserted = False
    finally:
        conn.close()
    return inserted
