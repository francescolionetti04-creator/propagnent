import sqlite3
import json
import os
import re

DB_PATH = os.path.join(os.path.dirname(__file__), "propagnent.db")

# Import condizionale: psycopg2 opzionale (non disponibile in ambienti SQLite-only)
try:
    import psycopg2
    import psycopg2.extras
    HAS_PG = True
except ImportError:
    HAS_PG = False

DATABASE_URL = os.environ.get("DATABASE_URL")
IS_PG = bool(DATABASE_URL) and HAS_PG

print(f"[DB] Modalità: {'PostgreSQL' if IS_PG else 'SQLite'}"
      + (f" (psycopg2 non installato — fallback SQLite)" if DATABASE_URL and not HAS_PG else ""))

# Mantenuta solo per retrocompatibilità — non inserita più nel DB
_ANNUNCI_ESEMPIO_LEGACY = [
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
]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers DB-agnostici
# ─────────────────────────────────────────────────────────────────────────────

def _sql(q: str) -> str:
    """
    Traduce SQL SQLite → PostgreSQL quando IS_PG=True.
    Trasformazioni:
      - ? → %s  (parametri)
      - BOOLEAN → SMALLINT  (evita confronti boolean/integer)
      - INTEGER PRIMARY KEY AUTOINCREMENT → SERIAL PRIMARY KEY
      - TIMESTAMP [DEFAULT CURRENT_TIMESTAMP] → TEXT
      - INSERT OR IGNORE INTO → INSERT INTO … ON CONFLICT DO NOTHING
      - % letterale in stringhe quoted → %% (escape psycopg2)
    """
    if not IS_PG:
        return q

    # Escape % letterale all'interno di stringhe quotate (es. LIKE '%val%')
    q = re.sub(r"'([^']*)'",
               lambda m: "'" + m.group(1).replace('%', '%%') + "'",
               q)
    # Placeholder parametri
    q = q.replace('?', '%s')
    # Tipi
    q = re.sub(r'\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b',
               'SERIAL PRIMARY KEY', q, flags=re.IGNORECASE)
    q = re.sub(r'\bBOOLEAN\b', 'SMALLINT', q, flags=re.IGNORECASE)
    # DEFAULT booleani → interi (dopo BOOLEAN→SMALLINT la colonna è SMALLINT)
    q = q.replace('DEFAULT TRUE',  'DEFAULT 1')
    q = q.replace('DEFAULT FALSE', 'DEFAULT 0')
    q = q.replace('DEFAULT true',  'DEFAULT 1')
    q = q.replace('DEFAULT false', 'DEFAULT 0')
    q = re.sub(r'\bTIMESTAMP\s+DEFAULT\s+CURRENT_TIMESTAMP\b',
               'TEXT', q, flags=re.IGNORECASE)
    q = re.sub(r'\bTIMESTAMP\b', 'TEXT', q, flags=re.IGNORECASE)
    # INSERT OR IGNORE → ON CONFLICT DO NOTHING
    if re.search(r'INSERT\s+OR\s+IGNORE\s+INTO', q, re.IGNORECASE):
        q = re.sub(r'INSERT\s+OR\s+IGNORE\s+INTO', 'INSERT INTO',
                   q, flags=re.IGNORECASE)
        q = q.rstrip().rstrip(';') + ' ON CONFLICT DO NOTHING'
    return q


def get_conn():
    """Restituisce una connessione al DB (PostgreSQL o SQLite)."""
    if IS_PG:
        return psycopg2.connect(DATABASE_URL)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _cur(conn):
    """
    Cursore con accesso per nome colonna, compatibile con entrambi i DB.
    psycopg2 DictCursor: row['col'] e row[0] entrambi funzionano.
    sqlite3 cursor: idem grazie a row_factory = sqlite3.Row.
    """
    if IS_PG:
        return conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    return conn.cursor()


def _to_dict(row) -> dict:
    """Converte una riga cursore in un dict Python puro."""
    if IS_PG:
        return {k: row[k] for k in row.keys()}
    return dict(row)


# ─────────────────────────────────────────────────────────────────────────────
# Schema e migrazioni
# ─────────────────────────────────────────────────────────────────────────────

def init_db():
    conn = get_conn()
    cur = _cur(conn)

    cur.execute(_sql("""
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
            url_originale TEXT UNIQUE,
            foto_url TEXT,
            portale TEXT
        )
    """))

    # Migrazioni: aggiunge colonne mancanti
    if IS_PG:
        for col_def in [
            "ALTER TABLE annunci ADD COLUMN IF NOT EXISTS foto_url TEXT",
            "ALTER TABLE annunci ADD COLUMN IF NOT EXISTS portale TEXT",
            # Sprint 5.0.2 SX: campi geografici normalizzati
            "ALTER TABLE annunci ADD COLUMN IF NOT EXISTS citta VARCHAR(100) DEFAULT NULL",
            "ALTER TABLE annunci ADD COLUMN IF NOT EXISTS provincia VARCHAR(2) DEFAULT NULL",
            # Sprint 5.4: tipologia canonicalizzata (appartamento/casa_villa/terreno/garage/altro)
            "ALTER TABLE annunci ADD COLUMN IF NOT EXISTS tipologia VARCHAR(20) DEFAULT NULL",
        ]:
            cur.execute(col_def)
    else:
        for col_def in [
            "ALTER TABLE annunci ADD COLUMN foto_url TEXT",
            "ALTER TABLE annunci ADD COLUMN portale TEXT",
            "ALTER TABLE annunci ADD COLUMN citta TEXT",
            "ALTER TABLE annunci ADD COLUMN provincia TEXT",
            "ALTER TABLE annunci ADD COLUMN tipologia TEXT",
        ]:
            try:
                cur.execute(col_def)
            except Exception:
                pass  # colonna già presente
    # Indici geo + tipologia (idempotenti)
    for idx_def in [
        "CREATE INDEX IF NOT EXISTS idx_annunci_citta     ON annunci(citta)",
        "CREATE INDEX IF NOT EXISTS idx_annunci_provincia ON annunci(provincia)",
        "CREATE INDEX IF NOT EXISTS idx_annunci_tipologia ON annunci(tipologia)",
    ]:
        try:
            cur.execute(_sql(idx_def))
        except Exception:
            pass

    # Rimuove annunci di esempio (Verona/Garda) da versioni precedenti
    cur.execute(_sql(
        "DELETE FROM annunci WHERE url_originale LIKE 'https://esempio.it%%'"
        if IS_PG else
        "DELETE FROM annunci WHERE url_originale LIKE 'https://esempio.it%'"
    ))

    # Backfill portale per record privi di esso
    for stmt in [
        "UPDATE annunci SET portale='subito.it'      WHERE portale IS NULL AND url_originale LIKE '%%subito.it%%'" if IS_PG else
        "UPDATE annunci SET portale='subito.it'      WHERE portale IS NULL AND url_originale LIKE '%subito.it%'",
        "UPDATE annunci SET portale='idealista.it'   WHERE portale IS NULL AND url_originale LIKE '%%idealista.it%%'" if IS_PG else
        "UPDATE annunci SET portale='idealista.it'   WHERE portale IS NULL AND url_originale LIKE '%idealista.it%'",
        "UPDATE annunci SET portale='immobiliare.it' WHERE portale IS NULL AND url_originale LIKE '%%immobiliare.it%%'" if IS_PG else
        "UPDATE annunci SET portale='immobiliare.it' WHERE portale IS NULL AND url_originale LIKE '%immobiliare.it%'",
    ]:
        cur.execute(stmt)

    # Tabella OMI
    cur.execute(_sql("""
        CREATE TABLE IF NOT EXISTS omi_quotazioni (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            anno INTEGER,
            semestre INTEGER,
            comune TEXT,
            provincia TEXT,
            zona_omi TEXT,
            tipo_immobile TEXT,
            stato TEXT,
            prezzo_min REAL,
            prezzo_max REAL,
            updated_at TEXT
        )
    """))

    # ── Tabella users (auth) ─────────────────────────────────────────────
    cur.execute(_sql("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            nome TEXT,
            cognome TEXT,
            telefono TEXT,
            role TEXT NOT NULL,
            city TEXT,
            is_founder BOOLEAN DEFAULT FALSE,
            is_email_verified BOOLEAN DEFAULT FALSE,
            email_verification_token TEXT,
            password_reset_token TEXT,
            password_reset_expires TEXT,
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            subscription_status TEXT DEFAULT 'none',
            trial_ends_at TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """))
    # Indice email (case-sensitive su SQLite, ma noi memorizziamo già lowercase)
    try:
        cur.execute(_sql("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)"))
    except Exception:
        pass

    # Sprint 5.0.2: colonna tutorial_visto per modal welcome onboarding
    if IS_PG:
        try:
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS tutorial_visto BOOLEAN DEFAULT FALSE")
        except Exception:
            pass
    else:
        try:
            cur.execute("ALTER TABLE users ADD COLUMN tutorial_visto BOOLEAN DEFAULT 0")
        except Exception:
            pass  # colonna già presente

    # Sprint 5.0.2: bio_pubblica (max 200 caratteri) per profilo pubblico agenti
    if IS_PG:
        try:
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS bio_pubblica VARCHAR(200) DEFAULT NULL")
        except Exception:
            pass
    else:
        try:
            cur.execute("ALTER TABLE users ADD COLUMN bio_pubblica VARCHAR(200) DEFAULT NULL")
        except Exception:
            pass  # colonna già presente

    # ── Tabella app_config (key-value) ───────────────────────────────────
    cur.execute(_sql("""
        CREATE TABLE IF NOT EXISTS app_config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """))

    # ── Tabella lead_venditori (Privati che vogliono vendere casa) ───────
    cur.execute(_sql("""
        CREATE TABLE IF NOT EXISTS lead_venditori (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            indirizzo TEXT NOT NULL,
            citta TEXT NOT NULL,
            provincia TEXT NOT NULL,
            tipo_immobile TEXT,
            mq INTEGER,
            camere INTEGER,
            bagni INTEGER,
            prezzo_richiesto INTEGER,
            descrizione TEXT,
            urgenza TEXT DEFAULT 'media',
            telefono_privato TEXT,
            foto_url TEXT,
            status TEXT DEFAULT 'attivo',
            created_at TEXT,
            updated_at TEXT
        )
    """))
    try:
        cur.execute(_sql("CREATE INDEX IF NOT EXISTS idx_lead_user      ON lead_venditori(user_id)"))
        cur.execute(_sql("CREATE INDEX IF NOT EXISTS idx_lead_provincia ON lead_venditori(provincia)"))
        cur.execute(_sql("CREATE INDEX IF NOT EXISTS idx_lead_status    ON lead_venditori(status)"))
    except Exception:
        pass

    # ── Tabella lead_contatti (audit click "Contatta" agenti) ────────────
    cur.execute(_sql("""
        CREATE TABLE IF NOT EXISTS lead_contatti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_venditore_id INTEGER NOT NULL,
            agente_user_id INTEGER NOT NULL,
            contattato_at TEXT
        )
    """))
    try:
        cur.execute(_sql("CREATE INDEX IF NOT EXISTS idx_contatti_lead   ON lead_contatti(lead_venditore_id)"))
        cur.execute(_sql("CREATE INDEX IF NOT EXISTS idx_contatti_agente ON lead_contatti(agente_user_id)"))
    except Exception:
        pass

    # ── Tabella lead_compratori (preferenze ricerca casa) ────────────────
    cur.execute(_sql("""
        CREATE TABLE IF NOT EXISTS lead_compratori (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            province_interesse TEXT NOT NULL,
            zona_libera TEXT,
            tipo_immobile TEXT,
            mq_min INTEGER,
            mq_max INTEGER,
            camere_min INTEGER,
            prezzo_min INTEGER,
            prezzo_max INTEGER,
            urgenza TEXT DEFAULT 'media',
            note_aggiuntive TEXT,
            email_match_attivo BOOLEAN DEFAULT TRUE,
            status TEXT DEFAULT 'attivo',
            created_at TEXT,
            updated_at TEXT
        )
    """))
    try:
        cur.execute(_sql("CREATE INDEX IF NOT EXISTS idx_lead_c_user   ON lead_compratori(user_id)"))
        cur.execute(_sql("CREATE INDEX IF NOT EXISTS idx_lead_c_status ON lead_compratori(status)"))
    except Exception:
        pass

    # ── Tabella lead_match (annunci matchati al compratore) ──────────────
    cur.execute(_sql("""
        CREATE TABLE IF NOT EXISTS lead_match (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_compratore_id INTEGER NOT NULL,
            annuncio_id INTEGER NOT NULL,
            match_score INTEGER DEFAULT 0,
            notificato_via_email BOOLEAN DEFAULT FALSE,
            created_at TEXT,
            UNIQUE(lead_compratore_id, annuncio_id)
        )
    """))
    try:
        cur.execute(_sql("CREATE INDEX IF NOT EXISTS idx_match_lead     ON lead_match(lead_compratore_id)"))
        cur.execute(_sql("CREATE INDEX IF NOT EXISTS idx_match_notified ON lead_match(notificato_via_email)"))
    except Exception:
        pass

    # ── Sprint 4 Task A: log generazioni Script Chiamata AI ──────────────
    cur.execute(_sql("""
        CREATE TABLE IF NOT EXISTS script_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agente_user_id INTEGER NOT NULL,
            annuncio_id INTEGER NOT NULL,
            generato_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tokens_input INTEGER DEFAULT 0,
            tokens_output INTEGER DEFAULT 0,
            costo_eur REAL DEFAULT 0
        )
    """))
    try:
        cur.execute(_sql("CREATE INDEX IF NOT EXISTS idx_script_logs_agente ON script_logs(agente_user_id)"))
        cur.execute(_sql("CREATE INDEX IF NOT EXISTS idx_script_logs_at     ON script_logs(generato_at)"))
    except Exception:
        pass

    # ── Sprint 5: Killer App #3 WhatsApp Auto-Acquisizione ───────────────
    cur.execute(_sql("""
        CREATE TABLE IF NOT EXISTS whatsapp_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agente_user_id INTEGER NOT NULL,
            annuncio_id INTEGER NOT NULL,
            telefono_privato VARCHAR(20),
            messaggio_inviato TEXT,
            inviato_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status VARCHAR(20) DEFAULT 'inviato',
            note TEXT,
            aggiornato_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tokens_input INTEGER DEFAULT 0,
            tokens_output INTEGER DEFAULT 0,
            costo_eur REAL DEFAULT 0
        )
    """))
    # Soft-delete (idempotente)
    if IS_PG:
        try:
            cur.execute("ALTER TABLE whatsapp_messages ADD COLUMN IF NOT EXISTS removed_at TEXT")
        except Exception:
            pass
    else:
        try:
            cur.execute("ALTER TABLE whatsapp_messages ADD COLUMN removed_at TEXT")
        except Exception:
            pass  # colonna già presente
    for idx_def in [
        "CREATE INDEX IF NOT EXISTS idx_wa_agente     ON whatsapp_messages(agente_user_id)",
        "CREATE INDEX IF NOT EXISTS idx_wa_inviato_at ON whatsapp_messages(inviato_at)",
        "CREATE INDEX IF NOT EXISTS idx_wa_status     ON whatsapp_messages(status)",
    ]:
        try:
            cur.execute(_sql(idx_def))
        except Exception:
            pass

    # ── Sprint 5.0: agenzie multi-account (ombrello) ─────────────────────
    cur.execute(_sql("""
        CREATE TABLE IF NOT EXISTS agencies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_user_id INTEGER NOT NULL,
            nome_agenzia TEXT,
            piano TEXT DEFAULT 'agenzia',
            max_account_inclusi INTEGER DEFAULT 3,
            stripe_subscription_id TEXT,
            stripe_seat_item_id TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """))
    try:
        cur.execute(_sql("CREATE INDEX IF NOT EXISTS idx_agencies_owner ON agencies(owner_user_id)"))
    except Exception:
        pass

    cur.execute(_sql("""
        CREATE TABLE IF NOT EXISTS agency_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agency_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            ruolo_in_agenzia TEXT DEFAULT 'agent',
            invited_at TEXT,
            accepted_at TEXT,
            removed_at TEXT,
            UNIQUE(agency_id, user_id)
        )
    """))
    try:
        cur.execute(_sql("CREATE INDEX IF NOT EXISTS idx_agency_members_agency ON agency_members(agency_id)"))
        cur.execute(_sql("CREATE INDEX IF NOT EXISTS idx_agency_members_user   ON agency_members(user_id)"))
    except Exception:
        pass

    cur.execute(_sql("""
        CREATE TABLE IF NOT EXISTS agency_invites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agency_id INTEGER NOT NULL,
            invite_token TEXT UNIQUE NOT NULL,
            email_invitato TEXT NOT NULL,
            nome_invitato TEXT,
            invited_at TEXT,
            expires_at TEXT,
            accepted_at TEXT,
            accepted_by_user_id INTEGER,
            cancelled_at TEXT
        )
    """))
    try:
        cur.execute(_sql("CREATE INDEX IF NOT EXISTS idx_invites_token  ON agency_invites(invite_token)"))
        cur.execute(_sql("CREATE INDEX IF NOT EXISTS idx_invites_agency ON agency_invites(agency_id)"))
        cur.execute(_sql("CREATE INDEX IF NOT EXISTS idx_invites_email  ON agency_invites(email_invitato)"))
    except Exception:
        pass

    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# OMI
# ─────────────────────────────────────────────────────────────────────────────

def get_omi_zone_map() -> dict:
    """
    Restituisce una mappa {zona_houseradar: {min, max, anno, semestre, comune}}
    con fallback a 3 livelli: fascia preferita → qualsiasi fascia → media provinciale.
    """
    ZONE_COMUNE = {
        "Livorno Città":      ("Livorno",         "LI", ["Semicentrale", "Centrale"]),
        "Costa Livornese":    ("Cecina",           "LI", ["Centrale", "Semicentrale"]),
        "Val di Cornia":      ("Piombino",         "LI", ["Centrale"]),
        "Isola d'Elba":       ("Portoferraio",     "LI", ["Centrale"]),
        "Hinterland Livorno": ("Collesalvetti",    "LI", ["Periferica", "Semicentrale"]),
        "Pisa Città":         ("Pisa",             "PI", ["Semicentrale", "Centrale"]),
        "Valdera":            ("Pontedera",        "PI", ["Centrale"]),
        "Valdicecina":        ("Volterra",         "PI", ["Centrale"]),
        "Litorale Pisano":    ("Marina di Pisa",   "PI", ["Periferica", "Semicentrale"]),
        "Valdarno Pisano":    ("San Miniato",      "PI", ["Centrale"]),
    }
    conn = get_conn()
    cur = _cur(conn)
    result = {}

    for zona_hr, (comune, provincia, fasce_pref) in ZONE_COMUNE.items():
        row = None
        fonte = None

        # Livello 1: fascia preferita per il comune
        for fascia in fasce_pref:
            cur.execute(_sql("""
                SELECT AVG(prezzo_min), AVG(prezzo_max), MAX(anno), MAX(semestre)
                FROM omi_quotazioni
                WHERE lower(comune) = lower(?)
                  AND zona_omi = ?
                  AND stato = 'normale'
                  AND lower(tipo_immobile) LIKE '%abitazioni%'
            """), (comune, fascia))
            row = cur.fetchone()
            if row and row[0]:
                fonte = "comune+fascia"
                break

        # Livello 2: qualsiasi fascia per lo stesso comune
        if not (row and row[0]):
            cur.execute(_sql("""
                SELECT AVG(prezzo_min), AVG(prezzo_max), MAX(anno), MAX(semestre)
                FROM omi_quotazioni
                WHERE lower(comune) = lower(?)
                  AND stato = 'normale'
                  AND lower(tipo_immobile) LIKE '%abitazioni%'
            """), (comune,))
            row = cur.fetchone()
            if row and row[0]:
                fonte = "comune"

        # Livello 3: media provinciale
        if not (row and row[0]):
            cur.execute(_sql("""
                SELECT AVG(prezzo_min), AVG(prezzo_max), MAX(anno), MAX(semestre)
                FROM omi_quotazioni
                WHERE upper(provincia) = upper(?)
                  AND stato = 'normale'
                  AND lower(tipo_immobile) LIKE '%abitazioni%'
            """), (provincia,))
            row = cur.fetchone()
            if row and row[0]:
                fonte = f"provincia {provincia}"

        if row and row[0]:
            result[zona_hr] = {
                "min":      round(row[0]),
                "max":      round(row[1]),
                "anno":     row[2],
                "semestre": row[3],
                "comune":   comune,
                "_fonte":   fonte,
            }

    conn.close()
    return result


def upsert_omi(righe: list) -> int:
    """Inserisce o aggiorna le quotazioni OMI. Ritorna il numero di righe inserite."""
    conn = get_conn()
    cur = _cur(conn)
    n = 0
    now = __import__("datetime").datetime.now().isoformat()
    for r in righe:
        cur.execute(_sql("""
            INSERT INTO omi_quotazioni
              (anno, semestre, comune, provincia, zona_omi, tipo_immobile, stato,
               prezzo_min, prezzo_max, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """), (
            r["anno"], r["semestre"], r["comune"], r["provincia"],
            r["zona_omi"], r["tipo_immobile"], r["stato"],
            r["prezzo_min"], r["prezzo_max"], now
        ))
        n += 1
    conn.commit()
    conn.close()
    return n


def omi_ha_dati() -> bool:
    conn = get_conn()
    cur = _cur(conn)
    cur.execute("SELECT COUNT(*) FROM omi_quotazioni")
    c = cur.fetchone()[0]
    conn.close()
    return c > 0


def omi_e_aggiornato(max_giorni: int = 180) -> bool:
    """Ritorna True se i dati OMI sono presenti e aggiornati entro max_giorni."""
    conn = get_conn()
    cur = _cur(conn)
    cur.execute("SELECT MAX(updated_at) FROM omi_quotazioni")
    row = cur.fetchone()
    conn.close()
    if not row or not row[0]:
        return False
    from datetime import datetime
    try:
        last = datetime.fromisoformat(row[0])
        return (datetime.now() - last).days < max_giorni
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Annunci
# ─────────────────────────────────────────────────────────────────────────────

def get_comparabili(zona: str, tipo: str, mq=None, limit: int = 5) -> list:
    """
    Annunci recenti della stessa zona/tipo con superficie ±30% rispetto a mq.
    Usato per la sezione Comparabili del report PDF.
    """
    conn = get_conn()
    cur = _cur(conn)
    if mq:
        mq_min = int(mq * 0.70)
        mq_max = int(mq * 1.30)
        cur.execute(_sql("""
            SELECT * FROM annunci
            WHERE zona = ? AND tipo = ?
              AND mq BETWEEN ? AND ?
              AND prezzo IS NOT NULL
            ORDER BY data_inserimento DESC
            LIMIT ?
        """), (zona, tipo, mq_min, mq_max, limit))
    else:
        cur.execute(_sql("""
            SELECT * FROM annunci
            WHERE zona = ? AND tipo = ? AND prezzo IS NOT NULL
            ORDER BY data_inserimento DESC
            LIMIT ?
        """), (zona, tipo, limit))
    rows = [_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_annunci(zona=None, tipo=None, fonte=None, sort="new",
                prezzo_max=None, provincia=None, citta=None, q=None,
                tipologia=None):
    """Filtri:
      - zona: legacy (LIKE su zona/indirizzo) — mantenuto per compatibilità
      - tipo, fonte, prezzo_max, sort: invariati
      - provincia: codice 2 lettere (LI/PI/FI/...) — match esatto
      - citta: nome comune (es. "Cecina") — match esatto
      - q: ricerca testo libera su indirizzo OR zona OR citta (case-insensitive)
      - tipologia: CSV di una o più tra appartamento/casa_villa/terreno/garage/altro
                   (Sprint 5.4). Esempio: "appartamento,casa_villa"
    """
    conn = get_conn()
    cur = _cur(conn)

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

    # Sprint 5.0.2 SX: filtri geografici normalizzati
    if provincia:
        query += " AND provincia = ?"
        params.append(provincia.upper())
    if citta:
        query += " AND lower(citta) = lower(?)"
        params.append(citta)
    # Sprint 5.4: filtro tipologia (CSV)
    if tipologia:
        valori = [v.strip().lower() for v in str(tipologia).split(",") if v.strip()]
        if valori:
            placeholders = ",".join(["?"] * len(valori))
            query += f" AND tipologia IN ({placeholders})"
            params += valori
    if q:
        like = f"%{q.strip()}%"
        # case-insensitive: usiamo lower() (SQLite + Postgres compatibili)
        query += " AND (lower(indirizzo) LIKE lower(?) OR lower(zona) LIKE lower(?) OR lower(citta) LIKE lower(?))"
        params += [like, like, like]

    sort_map = {
        "new":        "giorni_online ASC",
        "priv":       "CASE WHEN fonte='privato' THEN 0 ELSE 1 END ASC, giorni_online ASC",
        "noescl":     "CASE WHEN fonte='noescl' THEN 0 ELSE 1 END ASC, giorni_online ASC",
        "prezzo-asc": "prezzo ASC",
        "giorni":     "giorni_online DESC",
    }
    query += f" ORDER BY {sort_map.get(sort, 'giorni_online ASC')}"

    cur.execute(_sql(query), params)
    rows = [_to_dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_conteggio_per_tipologia() -> dict:
    """Sprint 5.4: ritorna {tipologia: count} per dashboard / pillole filtro."""
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        SELECT COALESCE(tipologia, 'altro') AS tipologia, COUNT(*) AS n
          FROM annunci
         GROUP BY COALESCE(tipologia, 'altro')
         ORDER BY n DESC
    """))
    out = {}
    for row in cur.fetchall():
        if isinstance(row, dict):
            out[row["tipologia"]] = row["n"]
        else:
            out[row[0]] = row[1]
    conn.close()
    return out


def get_zone_disponibili() -> dict:
    """Per dropdown cascade frontend: province + città per provincia con counter.
    Sprint 5.0.2 SX.
    """
    conn = get_conn(); cur = _cur(conn)
    cur.execute(_sql("""
        SELECT provincia, citta, COUNT(*) AS n
        FROM annunci
        WHERE provincia IS NOT NULL AND citta IS NOT NULL
        GROUP BY provincia, citta
        ORDER BY provincia, citta
    """))
    rows = cur.fetchall()
    conn.close()

    # Importa nomi province
    try:
        from geo.comuni_toscana import PROVINCE_TOSCANA
    except Exception:
        PROVINCE_TOSCANA = {}

    province_counter = {}
    citta_per_prov = {}
    for r in rows:
        prov = r[0] if not isinstance(r, dict) else r["provincia"]
        cit  = r[1] if not isinstance(r, dict) else r["citta"]
        n    = r[2] if not isinstance(r, dict) else r["n"]
        province_counter[prov] = province_counter.get(prov, 0) + int(n)
        citta_per_prov.setdefault(prov, []).append({"nome": cit, "count": int(n)})

    province = [
        {"codice": p, "nome": PROVINCE_TOSCANA.get(p, p), "count": province_counter[p]}
        for p in sorted(province_counter.keys())
    ]
    return {
        "province":           province,
        "citta_per_provincia": citta_per_prov,
    }


def get_stats():
    conn = get_conn()
    cur = _cur(conn)

    cur.execute("SELECT COUNT(*) FROM annunci")
    totale = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM annunci WHERE fonte='privato'")
    privati = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM annunci WHERE fonte='noescl'")
    noescl = cur.fetchone()[0]
    cur.execute(_sql("SELECT COUNT(*) FROM annunci WHERE is_nuovo=1"))
    nuovi_oggi = cur.fetchone()[0]
    cur.execute(_sql("SELECT COUNT(*) FROM annunci WHERE indirizzo_preciso=1"))
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
    cur = _cur(conn)
    cur.execute(_sql(
        "SELECT * FROM annunci WHERE is_nuovo=1 ORDER BY giorni_online ASC"
    ))
    rows = [_to_dict(r) for r in cur.fetchall()]
    conn.close()

    if not rows:
        return {"ha_alert": False, "testo": "", "annunci": []}

    privati_new = [r for r in rows if r["fonte"] == "privato"]
    noescl_new  = [r for r in rows if r["fonte"] == "noescl"]

    parti = []
    if privati_new:
        zone = ", ".join(set(r["zona"] for r in privati_new if r.get("zona")))
        parti.append(f"<strong>{len(privati_new)} privat{'o' if len(privati_new)==1 else 'i'}</strong> ({zone})")
    if noescl_new:
        zone = ", ".join(set(r["zona"] for r in noescl_new if r.get("zona")))
        parti.append(f"<strong>{len(noescl_new)} non in esclusiva</strong> ({zone})")

    testo = (
        f"<strong>{len(rows)} nuov{'o' if len(rows)==1 else 'i'} "
        f"annunc{'io' if len(rows)==1 else 'i'} nelle ultime 2 ore</strong>"
        f" — {' e '.join(parti)}. Controlla subito prima degli altri agenti."
    )
    return {"ha_alert": True, "testo": testo, "annunci": rows}


def determina_tipologia_da_titolo(titolo: str, tipo_hint: str = "") -> str:
    """Sprint 5.4: canonicalizza la tipologia immobile a 1 di 5 valori
    (appartamento/casa_villa/terreno/garage/altro) usando keyword nel titolo
    e nel campo `tipo` (es. "Villa", "Bilocale").

    Heuristic title-based — accettata fragilità per i 5 portali non-Subito
    (Sprint 5.4 v1). Subito popola `tipologia` direttamente da Hades
    `category.friendly_name`, salta questo fallback.
    """
    t = (titolo or "").lower() + " " + (tipo_hint or "").lower()
    if any(x in t for x in [
        "villa", "villino", "villetta", "bifamiliare", "trifamiliare",
        "casale", "rustico", "cascina", "casa indipendente", "fienile",
        "casolare", "casa singola",
    ]):
        return "casa_villa"
    if any(x in t for x in [
        "terreno", "terreni", "agricolo", "edificabile", "fondo agricolo",
    ]):
        return "terreno"
    if any(x in t for x in [
        "garage", " box ", "box auto", "posto auto", "posto moto", "autorimessa",
    ]):
        return "garage"
    # Esclusioni implicite (rientreranno in "altro")
    if any(x in t for x in [
        "ufficio", "uffici", "magazzino", "capannone", "negozio", "fondo commerciale",
        "locale commerciale", "loft", "mansarda", "multiproprieta", "multiproprietà",
    ]):
        return "altro"
    # Default per appartamenti/bilocali/trilocali/monolocali/attici
    return "appartamento"


def upsert_sync_annunci(annunci: list) -> dict:
    """
    Upsert annunci via /api/sync (es. da Idealista locale).
    Ritorna {"inseriti": N, "aggiornati": N, "totale": N}.
    """
    conn = get_conn()
    cur = _cur(conn)
    inseriti = aggiornati = 0
    now = __import__("datetime").datetime.now().isoformat()

    for a in annunci:
        url = a.get("url_originale") or a.get("url", "")
        if not url:
            continue

        cur.execute(_sql(
            "SELECT id FROM annunci WHERE url_originale = ?"
        ), (url,))
        row = cur.fetchone()

        if row:
            cur.execute(_sql("""
                UPDATE annunci SET
                    prezzo        = COALESCE(?, prezzo),
                    mq            = COALESCE(?, mq),
                    camere        = COALESCE(?, camere),
                    giorni_online = COALESCE(?, giorni_online),
                    foto_url      = COALESCE(?, foto_url)
                WHERE url_originale = ?
            """), (a.get("prezzo"), a.get("mq"), a.get("camere"),
                   a.get("giorni_online"), a.get("foto_url"), url))
            aggiornati += 1
        else:
            # Sprint 5.0.2 SX: normalizza citta+provincia (se non già forniti)
            citta_n = a.get("citta")
            provincia_n = a.get("provincia")
            if not citta_n or not provincia_n:
                try:
                    from geo.comuni_toscana import normalizza_annuncio
                    c2, p2 = normalizza_annuncio(a.get("indirizzo"), a.get("zona"))
                    citta_n = citta_n or c2
                    provincia_n = provincia_n or p2
                except Exception:
                    pass
            # Sprint 5.4: tipologia canonicalizzata. Subito invia già il valore
            # da Hades category.friendly_name; altri portali → fallback dal titolo.
            tipologia_in = a.get("tipologia")
            if not tipologia_in:
                tipologia_in = determina_tipologia_da_titolo(
                    a.get("indirizzo") or a.get("titolo") or "",
                    a.get("tipo") or "",
                )

            cur.execute(_sql("""
                INSERT INTO annunci (
                    indirizzo, indirizzo_preciso, zona, tipo, mq, camere,
                    prezzo, giorni_online, fonte, agenzie, proprietario, telefono,
                    intel_privato, intel_warning, ai_insight,
                    is_nuovo, data_inserimento, url_originale, foto_url, portale,
                    citta, provincia, tipologia
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """), (
                a.get("indirizzo"), a.get("indirizzo_preciso", False),
                a.get("zona"), a.get("tipo", "Appartamento"),
                a.get("mq"), a.get("camere"), a.get("prezzo"),
                a.get("giorni_online", 0),
                a.get("fonte", "agenzia"),
                a.get("agenzie", "[]"),
                a.get("proprietario"),
                a.get("telefono"),
                a.get("intel_privato"), a.get("intel_warning"), a.get("ai_insight"),
                a.get("is_nuovo", True),
                a.get("data_inserimento", now),
                url,
                a.get("foto_url"),
                a.get("portale", "idealista.it"),
                citta_n, provincia_n,
                tipologia_in,
            ))
            inseriti += 1

    conn.commit()
    conn.close()
    return {"inseriti": inseriti, "aggiornati": aggiornati, "totale": inseriti + aggiornati}


def insert_annuncio(a: dict):
    conn = get_conn()
    cur = _cur(conn)
    now = __import__("datetime").datetime.now().isoformat()
    try:
        cur.execute(_sql("""
            INSERT OR IGNORE INTO annunci
            (indirizzo, indirizzo_preciso, zona, tipo, mq, camere, prezzo,
             giorni_online, fonte, agenzie, proprietario, telefono,
             intel_privato, intel_warning, ai_insight,
             is_nuovo, url_originale, data_inserimento)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """), (
            a.get("indirizzo"), a.get("indirizzo_preciso", True),
            a.get("zona"), a.get("tipo"),
            a.get("mq"), a.get("camere"), a.get("prezzo"),
            a.get("giorni_online", 0), a.get("fonte", "agenzia"),
            json.dumps(a.get("agenzie", [])) if isinstance(a.get("agenzie"), list) else a.get("agenzie", "[]"),
            a.get("proprietario"), a.get("telefono"),
            a.get("intel_privato"), a.get("intel_warning"), a.get("ai_insight"),
            a.get("is_nuovo", False), a.get("url_originale"), now,
        ))
        conn.commit()
        inserted = cur.rowcount > 0
    except Exception as e:
        print(f"[DB] Errore inserimento: {e}")
        inserted = False
    finally:
        conn.close()
    return inserted
