# PropAgent AI — Istruzioni complete per Claude Code

Ciao! Devi costruire un'app web completa per un agente immobiliare italiano chiamata **PropAgent AI**.
Leggi tutto questo file dall'inizio alla fine prima di iniziare, poi esegui tutto in ordine.

---

## COSA FA L'APP

Un radar di annunci immobiliari che aiuta un agente a trovare:
1. **Annunci di privati** (senza nessuna agenzia) — con indirizzo preciso e telefono
2. **Annunci di agenzie senza esclusiva** — stesso immobile pubblicato da più agenzie contemporaneamente
3. Ordina tutto per "chi arriva prima vince" — annunci nuovi in cima

---

## STRUTTURA DEL PROGETTO DA CREARE

```
propagnent/
├── backend/
│   ├── main.py          (API FastAPI)
│   ├── database.py      (gestione SQLite)
│   ├── models.py        (struttura dati)
│   └── requirements.txt
├── scraper/
│   ├── scraper.py       (raccoglie annunci da Subito.it)
│   └── scheduler.py     (esegue lo scraper ogni 2 ore)
└── frontend/
    └── index.html       (UI completa — vedi sezione FRONTEND)
```

---

## STEP 1 — Installa tutto

Crea la struttura cartelle e installa queste dipendenze Python:

```
fastapi
uvicorn
playwright
beautifulsoup4
requests
schedule
python-dateutil
aiohttp
```

Poi esegui: `playwright install chromium`

---

## STEP 2 — Database SQLite

Crea il file `backend/database.py` con questa tabella `annunci`:

```python
id INTEGER PRIMARY KEY AUTOINCREMENT
indirizzo TEXT NOT NULL
indirizzo_preciso BOOLEAN DEFAULT TRUE
zona TEXT
tipo TEXT
mq INTEGER
camere INTEGER
prezzo INTEGER
giorni_online INTEGER DEFAULT 0
fonte TEXT  -- valori: "privato", "agenzia", "noescl"
agenzie TEXT  -- JSON array con nomi agenzie se noescl
proprietario TEXT
telefono TEXT
intel_privato TEXT
intel_warning TEXT
ai_insight TEXT
is_nuovo BOOLEAN DEFAULT FALSE
data_inserimento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
url_originale TEXT UNIQUE
```

Poi inserisci questi 9 annunci di esempio nel database all'avvio se è vuoto:

```python
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
```

---

## STEP 3 — API FastAPI (backend/main.py)

Crea questi endpoint con CORS abilitato per tutte le origini:

### GET /annunci
Parametri query opzionali:
- `zona` (stringa)
- `tipo` (stringa)
- `fonte` (privato / noescl / agenzia)
- `sort` (new / priv / noescl / prezzo-asc / giorni)
- `prezzo_max` (intero)

Logica di sort:
- `new` → ordina per giorni_online ASC (più recenti prima)
- `priv` → privati prima, poi gli altri
- `noescl` → non-esclusiva prima, poi gli altri
- `prezzo-asc` → prezzo ASC
- `giorni` → giorni_online DESC (più vecchi prima)

Ritorna: lista di tutti i campi della tabella, con `agenzie` già parsato come array JSON.

### GET /stats
Ritorna:
```json
{
  "totale": 9,
  "privati": 5,
  "noescl": 4,
  "nuovi_oggi": 3,
  "indirizzi_precisi": 8
}
```

### GET /alert
Ritorna gli annunci con `is_nuovo = true` e questo formato:
```json
{
  "ha_alert": true,
  "testo": "3 nuovi annunci nelle ultime 2 ore — 1 privato a Verona Centro e 2 non in esclusiva a Garda.",
  "annunci": [...]
}
```

### POST /scraper/avvia
Avvia lo scraper manualmente in background e ritorna:
```json
{"status": "avviato", "messaggio": "Scraper in esecuzione..."}
```

---

## STEP 4 — Scraper (scraper/scraper.py)

Usa **Playwright** con browser headless per scrapare Subito.it.

URL da scrapare (categoria case in vendita):
```
https://www.subito.it/annunci-italia/vendita/immobili/?c=1&r=veneto&ci=114  (Verona)
https://www.subito.it/annunci-italia/vendita/immobili/?c=1&r=veneto&ci=118  (Lago di Garda area)
```

Per ogni annuncio estrai:
- **Titolo** dell'annuncio
- **Prezzo** (rimuovi €, punti, converti in intero)
- **Indirizzo** — cerca nel testo dell'annuncio pattern tipo "Via X N, CAP Città". Se non trovato, usa la zona indicata con `indirizzo_preciso = False`
- **Zona** (dalla breadcrumb o dal titolo)
- **Mq e camere** (dal corpo dell'annuncio se presenti)
- **Nome inserzionista** — se contiene "agenzia", "immobiliare", "srl", "studio", "group", "real estate", "casa", "property" → è un'agenzia, altrimenti è privato
- **Telefono** (se visibile nella pagina)
- **URL** dell'annuncio

Dopo aver raccolto tutti gli annunci:
- Controlla se lo stesso indirizzo compare con inserzionisti diversi → se sì, marcalo `fonte = "noescl"` e salva i nomi in `agenzie`
- Salva nel DB solo annunci con URL non già presente (evita duplicati)
- Marca `is_nuovo = True` gli annunci inseriti nell'ultima ora
- Aggiungi un delay random tra 3 e 8 secondi tra una pagina e l'altra

Genera automaticamente `intel_privato`, `intel_warning` e `ai_insight` in base a:
- Giorni online (se > 30: "Invenduto da X giorni — proprietario probabilmente motivato")
- Fonte privato: "Annuncio privato diretto su Subito.it — nessun agente presente"
- Non esclusiva: "Presente con N agenzie — nessuna ha l'esclusiva"

---

## STEP 5 — Scheduler (scraper/scheduler.py)

Crea uno script che:
- Esegue lo scraper subito all'avvio
- Poi lo ripete ogni 2 ore con la libreria `schedule`
- Stampa un log con timestamp ogni volta che inizia e finisce

```python
# avvio: python scraper/scheduler.py
```

---

## STEP 6 — Frontend (frontend/index.html)

Crea questo file HTML completo (tutto in un unico file, CSS e JS inclusi):

```html
<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PropAgent AI — Trova Case</title>
<style>
/* ========== RESET & BASE ========== */
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1a1a1a;background:#f5f5f3;min-height:100vh}
.app{max-width:1100px;margin:0 auto;padding:1.5rem}

/* ========== TOPBAR ========== */
.topbar{display:flex;align-items:center;justify-content:space-between;background:#fff;border:1px solid #e5e5e0;border-radius:12px;padding:1rem 1.25rem;margin-bottom:1.25rem;flex-wrap:wrap;gap:10px}
.logo{display:flex;align-items:center;gap:10px}
.logo-icon{width:36px;height:36px;background:#185FA5;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:18px;font-weight:700}
.logo-name{font-size:17px;font-weight:700;color:#1a1a1a}
.logo-sub{font-size:11px;color:#888;margin-top:1px}
.topbar-right{display:flex;align-items:center;gap:10px}
.live-badge{display:flex;align-items:center;gap:6px;background:#EAF3DE;border:1px solid #97C459;border-radius:20px;padding:5px 14px;font-size:12px;color:#27500A;font-weight:600}
.live-dot{width:7px;height:7px;border-radius:50%;background:#639922;animation:pulse-dot 1.5s infinite}
@keyframes pulse-dot{0%,100%{opacity:1}50%{opacity:.3}}
.btn-refresh{padding:7px 16px;background:#185FA5;color:#fff;border:none;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer}
.btn-refresh:hover{background:#0C447C}
.btn-refresh:disabled{background:#888;cursor:not-allowed}

/* ========== SEARCH PANEL ========== */
.search-panel{background:#fff;border:1px solid #e5e5e0;border-radius:12px;padding:1.25rem;margin-bottom:1rem}
.search-row{display:flex;gap:8px;margin-bottom:.85rem}
.search-row input{flex:1;padding:11px 16px;border:1px solid #d0d0cc;border-radius:8px;font-size:14px;outline:none;color:#1a1a1a;background:#fff}
.search-row input:focus{border-color:#185FA5;box-shadow:0 0 0 3px #B5D4F420}
.btn-search{padding:11px 22px;background:#185FA5;color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer}
.btn-search:hover{background:#0C447C}
.filter-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.fb-label{font-size:12px;color:#888;font-weight:600;white-space:nowrap}
.fb-chip{padding:5px 13px;border-radius:20px;border:1px solid #d0d0cc;font-size:12px;cursor:pointer;background:#fff;color:#666;white-space:nowrap;transition:all .12s;user-select:none}
.chip-privato.on{background:#EAF3DE;border-color:#639922;color:#27500A;font-weight:600}
.chip-noescl.on{background:#FAEEDA;border-color:#EF9F27;color:#633806;font-weight:600}
.chip-agenzia.on{background:#E6F1FB;border-color:#378ADD;color:#0C447C;font-weight:600}
.fb-sep{width:1px;height:20px;background:#e5e5e0;margin:0 4px}
.fb-select{font-size:12px;padding:5px 10px;border:1px solid #d0d0cc;border-radius:8px;background:#fff;color:#1a1a1a;cursor:pointer}

/* ========== ALERT BANNER ========== */
.alert-banner{background:#FAEEDA;border:1px solid #FAC775;border-radius:10px;padding:.85rem 1rem;margin-bottom:1rem;display:flex;align-items:flex-start;gap:10px}
.alert-icon{font-size:18px;flex-shrink:0}
.alert-text{font-size:13px;color:#633806;line-height:1.5}
.alert-text strong{font-weight:700;color:#412402}

/* ========== STATS ========== */
.stats-row{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:1.25rem}
.stat{background:#fff;border:1px solid #e5e5e0;border-radius:10px;padding:.85rem 1rem}
.stat-val{font-size:24px;font-weight:700}
.stat-lbl{font-size:11px;color:#888;margin-top:2px}
.stat-sub{font-size:11px;margin-top:4px;font-weight:600}

/* ========== RESULTS HEADER ========== */
.results-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:.85rem;flex-wrap:wrap;gap:8px}
.results-title{font-size:14px;color:#888}
.results-title span{font-weight:700;color:#1a1a1a}
.legend{display:flex;gap:10px;font-size:12px;color:#888;align-items:center}
.leg-dot{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:3px;vertical-align:middle}

/* ========== CARDS ========== */
.cards{display:flex;flex-direction:column;gap:.85rem}
.lcard{background:#fff;border-radius:12px;overflow:hidden;transition:box-shadow .15s}
.lcard:hover{box-shadow:0 4px 16px rgba(0,0,0,.07)}
.lcard-priv{border:2px solid #97C459}
.lcard-noescl{border:2px solid #EF9F27}
.lcard-agenzia{border:1px solid #e5e5e0}
.lcard-inner{display:flex}
.lcard-stripe{width:5px;flex-shrink:0}
.lcard-body{flex:1;padding:1rem 1.2rem}

.card-top{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:.65rem;flex-wrap:wrap}
.card-addr{font-size:15px;font-weight:700;color:#1a1a1a;display:flex;align-items:center;gap:7px;flex-wrap:wrap;line-height:1.3}
.addr-badge{display:inline-flex;align-items:center;gap:3px;border-radius:10px;padding:2px 8px;font-size:10px;font-weight:700;white-space:nowrap}
.addr-ok{background:#EAF3DE;border:1px solid #97C459;color:#27500A}
.addr-est{background:#FAEEDA;border:1px solid #FAC775;color:#633806}
.card-zona{font-size:12px;color:#888;margin-top:3px}
.badges{display:flex;flex-wrap:wrap;gap:5px;align-items:center}
.badge{padding:3px 10px;border-radius:12px;font-size:11px;font-weight:700;white-space:nowrap}
.b-priv{background:#EAF3DE;color:#27500A;border:1px solid #97C459}
.b-noescl{background:#FAEEDA;color:#633806;border:1px solid #EF9F27}
.b-new{background:#E6F1FB;color:#0C447C;border:1px solid #85B7EB}
.b-hot{background:#FCEBEB;color:#A32D2D;border:1px solid #F09595}

.specs{display:flex;border:1px solid #e5e5e0;border-radius:8px;overflow:hidden;margin:.65rem 0}
.spec{flex:1;padding:7px 8px;text-align:center;border-right:1px solid #e5e5e0}
.spec:last-child{border-right:none}
.spec-v{font-size:13px;font-weight:700;color:#1a1a1a}
.spec-l{font-size:10px;color:#888;margin-top:2px}

.intel-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:.65rem 0}
.ibox{border-radius:8px;padding:.65rem .9rem}
.ibox-g{background:#EAF3DE;border:1px solid #97C459}
.ibox-o{background:#FAEEDA;border:1px solid #FAC775}
.ibox-p{background:#EEEDFE;border:1px solid #AFA9EC}
.ibox-label{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px}
.ibox-label-g{color:#3B6D11}
.ibox-label-o{color:#854F0B}
.ibox-label-p{color:#3C3489}
.ibox-text{font-size:12px;line-height:1.5}
.ibox-text-g{color:#085041}
.ibox-text-o{color:#633806}
.ibox-text-p{color:#534AB7}
.ibox-tel{margin-top:6px;font-size:13px;font-weight:700;color:#27500A}

.noescl-box{background:#FAEEDA;border:1px solid #EF9F27;border-radius:8px;padding:.65rem .9rem;margin:.65rem 0}
.noescl-title{font-size:11px;font-weight:700;color:#412402;margin-bottom:3px}
.noescl-text{font-size:12px;color:#633806;line-height:1.4;margin-bottom:6px}
.agency-pills{display:flex;flex-wrap:wrap;gap:4px}
.ap{padding:2px 9px;border-radius:8px;background:#fff;border:1px solid #FAC775;font-size:11px;color:#633806;font-weight:600}

.card-footer{display:flex;gap:6px;margin-top:.85rem;padding-top:.85rem;border-top:1px solid #f0f0ec;flex-wrap:wrap}
.cf-btn{flex:1;min-width:120px;padding:8px 10px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;text-align:center;transition:all .12s;border:none}
.cf-outline{background:#f5f5f3;color:#1a1a1a;border:1px solid #d0d0cc}
.cf-outline:hover{background:#ebebea}
.cf-green{background:#EAF3DE;color:#27500A;border:1px solid #97C459}
.cf-green:hover{background:#C0DD97}
.cf-blue{background:#185FA5;color:#fff}
.cf-blue:hover{background:#0C447C}
.cf-amber{background:#FAEEDA;color:#633806;border:1px solid #EF9F27}
.cf-amber:hover{background:#FAC775}

/* ========== SPINNER ========== */
.spinner{display:none;text-align:center;padding:3rem;color:#888;font-size:14px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#185FA5;margin:0 3px;animation:blink 1s infinite}
.dot:nth-child(2){animation-delay:.2s}.dot:nth-child(3){animation-delay:.4s}
@keyframes blink{0%,100%{opacity:.2}50%{opacity:1}}

/* ========== MODAL ========== */
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:100;align-items:center;justify-content:center}
.modal-bg.open{display:flex}
.modal{background:#fff;border-radius:14px;padding:1.5rem;max-width:540px;width:92%;max-height:85vh;overflow-y:auto}
.modal h3{font-size:16px;font-weight:700;margin-bottom:.85rem;color:#1a1a1a}
.modal-text{font-size:13px;line-height:1.75;color:#333;white-space:pre-wrap;background:#f9f9f7;border-radius:8px;padding:1rem;border:1px solid #e5e5e0}
.modal-actions{display:flex;gap:8px;margin-top:1rem}
.modal-copy{flex:1;padding:9px;background:#EAF3DE;color:#27500A;border:1px solid #97C459;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer}
.modal-copy:hover{background:#C0DD97}
.modal-close{flex:1;padding:9px;background:#185FA5;color:#fff;border:none;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer}
.modal-close:hover{background:#0C447C}

/* ========== EMPTY STATE ========== */
.empty{text-align:center;padding:3rem;color:#888;font-size:14px}

/* ========== RESPONSIVE ========== */
@media(max-width:640px){
  .stats-row{grid-template-columns:1fr 1fr}
  .intel-grid{grid-template-columns:1fr}
  .card-footer{flex-direction:column}
  .cf-btn{min-width:unset}
  .topbar{flex-direction:column;align-items:flex-start}
}
</style>
</head>
<body>

<div class="app">

  <!-- TOPBAR -->
  <div class="topbar">
    <div class="logo">
      <div class="logo-icon">P</div>
      <div>
        <div class="logo-name">PropAgent AI</div>
        <div class="logo-sub">Radar annunci — privati &amp; non in esclusiva · Verona e Lago di Garda</div>
      </div>
    </div>
    <div class="topbar-right">
      <div class="live-badge"><div class="live-dot"></div>Live</div>
      <button class="btn-refresh" id="btn-refresh" onclick="avviaScraper()">⟳ Aggiorna ora</button>
    </div>
  </div>

  <!-- SEARCH -->
  <div class="search-panel">
    <div class="search-row">
      <input type="text" id="q" placeholder="Filtra per zona, tipo, indirizzo..." oninput="render()" />
      <button class="btn-search" onclick="render()">Cerca</button>
    </div>
    <div class="filter-bar">
      <span class="fb-label">Mostra:</span>
      <span class="fb-chip chip-privato on" id="f-priv" onclick="toggleF('priv')">✔ Privati</span>
      <span class="fb-chip chip-noescl on" id="f-noescl" onclick="toggleF('noescl')">⚠ Non in esclusiva</span>
      <span class="fb-chip chip-agenzia" id="f-ag" onclick="toggleF('ag')">Agenzie</span>
      <div class="fb-sep"></div>
      <span class="fb-label">Ordina:</span>
      <select class="fb-select" id="f-sort" onchange="render()">
        <option value="new">Più recenti</option>
        <option value="priv">Privati prima</option>
        <option value="noescl">Non esclusiva prima</option>
        <option value="prezzo-asc">Prezzo ↑</option>
        <option value="giorni">Più vecchi</option>
      </select>
      <span class="fb-label">Tipo:</span>
      <select class="fb-select" id="f-tipo" onchange="render()">
        <option value="">Tutti</option>
        <option>Appartamento</option>
        <option>Villa</option>
        <option>Bilocale</option>
        <option>Attico</option>
        <option>Rustico</option>
      </select>
    </div>
  </div>

  <!-- ALERT -->
  <div class="alert-banner" id="alert-banner" style="display:none">
    <div class="alert-icon">⚡</div>
    <div class="alert-text" id="alert-text"></div>
  </div>

  <!-- STATS -->
  <div class="stats-row">
    <div class="stat"><div class="stat-val" style="color:#3B6D11" id="st-priv">—</div><div class="stat-lbl">Annunci privati</div><div class="stat-sub" style="color:#3B6D11">contatto diretto</div></div>
    <div class="stat"><div class="stat-val" style="color:#854F0B" id="st-noescl">—</div><div class="stat-lbl">Non in esclusiva</div><div class="stat-sub" style="color:#854F0B">puoi inserirli</div></div>
    <div class="stat"><div class="stat-val" id="st-addr">—</div><div class="stat-lbl">Indirizzo preciso</div><div class="stat-sub" style="color:#888">verificato</div></div>
    <div class="stat"><div class="stat-val" style="color:#A32D2D" id="st-new">—</div><div class="stat-lbl">Nuovi oggi</div><div class="stat-sub" style="color:#A32D2D">ultimi inserimenti</div></div>
  </div>

  <!-- RESULTS -->
  <div class="results-header">
    <div class="results-title">Trovati <span id="cnt-tot">—</span> annunci</div>
    <div class="legend">
      <span><span class="leg-dot" style="background:#EAF3DE;border:1px solid #97C459"></span>Privato</span>
      <span><span class="leg-dot" style="background:#FAEEDA;border:1px solid #EF9F27"></span>Non esclusiva</span>
    </div>
  </div>

  <div id="spinner" class="spinner"><span class="dot"></span><span class="dot"></span><span class="dot"></span><br><br>Caricamento annunci...</div>
  <div class="empty" id="empty" style="display:none">Nessun annuncio trovato con i filtri selezionati.</div>
  <div class="cards" id="cards"></div>

</div>

<!-- MODAL SCRIPT -->
<div class="modal-bg" id="modal-bg" onclick="if(event.target===this)closeModal()">
  <div class="modal">
    <h3 id="modal-title"></h3>
    <div class="modal-text" id="modal-body"></div>
    <div class="modal-actions">
      <button class="modal-copy" onclick="copyModal()">📋 Copia testo</button>
      <button class="modal-close" onclick="closeModal()">Chiudi</button>
    </div>
  </div>
</div>

<script>
const API = 'http://localhost:8000';
let allData = [];
let showPriv = true, showNoescl = true, showAg = false;

/* ========== INIT ========== */
async function init() {
  await loadStats();
  await loadAlert();
  await loadAnnunci();
}

/* ========== API CALLS ========== */
async function loadStats() {
  try {
    const r = await fetch(`${API}/stats`);
    const d = await r.json();
    document.getElementById('st-priv').textContent = d.privati;
    document.getElementById('st-noescl').textContent = d.noescl;
    document.getElementById('st-addr').textContent = d.indirizzi_precisi;
    document.getElementById('st-new').textContent = d.nuovi_oggi;
  } catch(e) { console.error('Stats error:', e); }
}

async function loadAlert() {
  try {
    const r = await fetch(`${API}/alert`);
    const d = await r.json();
    if (d.ha_alert) {
      document.getElementById('alert-text').innerHTML = d.testo;
      document.getElementById('alert-banner').style.display = 'flex';
    }
  } catch(e) {}
}

async function loadAnnunci() {
  document.getElementById('spinner').style.display = 'block';
  document.getElementById('cards').innerHTML = '';
  document.getElementById('empty').style.display = 'none';
  try {
    const r = await fetch(`${API}/annunci`);
    allData = await r.json();
    render();
  } catch(e) {
    document.getElementById('spinner').style.display = 'none';
    document.getElementById('cards').innerHTML = '<div class="empty">Errore connessione al server. Assicurati che il backend sia avviato su localhost:8000</div>';
  }
}

async function avviaScraper() {
  const btn = document.getElementById('btn-refresh');
  btn.disabled = true;
  btn.textContent = '⟳ Scansione in corso...';
  try {
    await fetch(`${API}/scraper/avvia`, { method: 'POST' });
    setTimeout(async () => {
      await loadAnnunci();
      await loadStats();
      await loadAlert();
      btn.disabled = false;
      btn.textContent = '⟳ Aggiorna ora';
    }, 3000);
  } catch(e) {
    btn.disabled = false;
    btn.textContent = '⟳ Aggiorna ora';
  }
}

/* ========== RENDER ========== */
function toggleF(f) {
  if (f === 'priv') { showPriv = !showPriv; document.getElementById('f-priv').classList.toggle('on', showPriv); }
  if (f === 'ag') { showAg = !showAg; document.getElementById('f-ag').classList.toggle('on', showAg); }
  if (f === 'noescl') { showNoescl = !showNoescl; document.getElementById('f-noescl').classList.toggle('on', showNoescl); }
  render();
}

function render() {
  document.getElementById('spinner').style.display = 'none';
  const q = document.getElementById('q').value.toLowerCase();
  const tipo = document.getElementById('f-tipo').value;
  const sort = document.getElementById('f-sort').value;

  let data = allData.filter(d => {
    if (d.fonte === 'privato' && !showPriv) return false;
    if (d.fonte === 'noescl' && !showNoescl) return false;
    if (d.fonte === 'agenzia' && !showAg) return false;
    if (tipo && d.tipo !== tipo) return false;
    if (q && !d.indirizzo.toLowerCase().includes(q) && !d.zona.toLowerCase().includes(q) && !d.tipo.toLowerCase().includes(q)) return false;
    return true;
  });

  const sorts = {
    new: (a,b) => a.giorni_online - b.giorni_online,
    priv: (a,b) => (a.fonte==='privato'?0:1) - (b.fonte==='privato'?0:1),
    noescl: (a,b) => (a.fonte==='noescl'?0:1) - (b.fonte==='noescl'?0:1),
    'prezzo-asc': (a,b) => a.prezzo - b.prezzo,
    giorni: (a,b) => b.giorni_online - a.giorni_online
  };
  data.sort(sorts[sort] || sorts.new);

  document.getElementById('cnt-tot').textContent = data.length;

  const cards = document.getElementById('cards');
  const empty = document.getElementById('empty');

  if (data.length === 0) {
    cards.innerHTML = '';
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';
  cards.innerHTML = data.map(cardHTML).join('');
}

/* ========== CARD HTML ========== */
function fmt(n) { return n ? n.toLocaleString('it-IT') + ' €' : '—'; }

function cardHTML(d) {
  const isP = d.fonte === 'privato', isN = d.fonte === 'noescl';
  const stripe = isP ? '#639922' : isN ? '#EF9F27' : '#B4B2A9';
  const cls = isP ? 'lcard-priv' : isN ? 'lcard-noescl' : 'lcard-agenzia';
  const agenzie = typeof d.agenzie === 'string' ? JSON.parse(d.agenzie || '[]') : (d.agenzie || []);

  const addrB = d.indirizzo_preciso
    ? '<span class="addr-badge addr-ok">✔ indirizzo preciso</span>'
    : '<span class="addr-badge addr-est">~ stima AI</span>';

  const srcB = isP ? '<span class="badge b-priv">Privato — nessun agente</span>'
    : isN ? '<span class="badge b-noescl">⚠ Non in esclusiva</span>'
    : '<span class="badge" style="background:#f0f0ec;color:#888;border:1px solid #d0d0cc">Agenzia</span>';

  const newB = d.is_nuovo ? '<span class="badge b-new">● Nuovo</span>' : '';
  const hotB = d.giorni_online === 0 ? '<span class="badge b-hot">🔥 Oggi</span>' : '';

  const intel = isP ? `
    <div class="intel-grid">
      <div class="ibox ibox-g">
        <div class="ibox-label ibox-label-g">Contatto diretto</div>
        <div class="ibox-text ibox-text-g">${d.intel_privato || '—'}</div>
        ${d.telefono ? `<div class="ibox-tel">Tel: ${d.telefono}</div>` : ''}
      </div>
      <div class="ibox ibox-p">
        <div class="ibox-label ibox-label-p">✦ Strategia AI</div>
        <div class="ibox-text ibox-text-p">${d.ai_insight || '—'}</div>
      </div>
    </div>
    <div class="ibox ibox-o" style="margin-top:0">
      <div class="ibox-label ibox-label-o">Attenzione</div>
      <div class="ibox-text ibox-text-o">${d.intel_warning || '—'}</div>
    </div>`
  : `<div class="noescl-box">
      <div class="noescl-title">⚠ Gestito da più agenzie senza esclusiva</div>
      <div class="noescl-text">${d.intel_warning || '—'}</div>
      <div class="agency-pills">${agenzie.map(a => `<span class="ap">${a}</span>`).join('')}</div>
    </div>
    <div class="ibox ibox-p" style="margin-top:8px">
      <div class="ibox-label ibox-label-p">✦ Come acquisirlo</div>
      <div class="ibox-text ibox-text-p">${d.ai_insight || '—'}</div>
    </div>`;

  const esc = s => s.replace(/'/g, "\\'").replace(/"/g, '&quot;');

  const footer = isP ? `
    <button class="cf-btn cf-green" onclick="showScript('whatsapp','${esc(d.indirizzo)}','${esc(d.tipo)}',${d.mq},${d.prezzo},${d.giorni_online},'${esc(d.proprietario||'')}')">💬 WhatsApp</button>
    <button class="cf-btn cf-outline" onclick="showScript('telefono','${esc(d.indirizzo)}','${esc(d.tipo)}',${d.mq},${d.prezzo},${d.giorni_online},'${esc(d.proprietario||'')}')">📞 Script chiamata</button>
    <button class="cf-btn cf-blue" onclick="showScript('esclusiva','${esc(d.indirizzo)}','${esc(d.tipo)}',${d.mq},${d.prezzo},${d.giorni_online},'${esc(d.proprietario||'')}')">+ Proponi esclusiva</button>`
  : `
    <button class="cf-btn cf-amber" onclick="showScript('conquista','${esc(d.indirizzo)}','${esc(d.tipo)}',${d.mq},${d.prezzo},${d.giorni_online},'',${agenzie.length})">🎯 Conquista esclusiva</button>
    <button class="cf-btn cf-outline" onclick="showScript('telefono','${esc(d.indirizzo)}','${esc(d.tipo)}',${d.mq},${d.prezzo},${d.giorni_online},'')">📞 Script chiamata</button>
    <button class="cf-btn cf-blue" onclick="alert('Stima: €${d.mq ? Math.round(d.prezzo/d.mq).toLocaleString(\'it-IT\') : \'—\'}/m²\\nPrezzo: ${fmt(d.prezzo)}\\nZona: ${d.zona}')">💡 Valuta</button>`;

  return `<div class="lcard ${cls}">
    <div class="lcard-inner">
      <div class="lcard-stripe" style="background:${stripe}"></div>
      <div class="lcard-body">
        <div class="card-top">
          <div>
            <div class="card-addr">${d.indirizzo} ${addrB}</div>
            <div class="card-zona">${d.zona} · ${d.tipo}</div>
          </div>
          <div class="badges">${srcB}${newB}${hotB}</div>
        </div>
        <div class="specs">
          <div class="spec"><div class="spec-v">${fmt(d.prezzo)}</div><div class="spec-l">prezzo</div></div>
          <div class="spec"><div class="spec-v">${d.mq || '—'} m²</div><div class="spec-l">superficie</div></div>
          <div class="spec"><div class="spec-v">${d.camere || '—'}</div><div class="spec-l">camere</div></div>
          <div class="spec"><div class="spec-v">${d.giorni_online === 0 ? 'oggi' : d.giorni_online + ' gg'}</div><div class="spec-l">online</div></div>
          <div class="spec"><div class="spec-v">${d.mq && d.prezzo ? Math.round(d.prezzo/d.mq).toLocaleString('it-IT') + ' €' : '—'}</div><div class="spec-l">€/m²</div></div>
        </div>
        ${intel}
        <div class="card-footer">${footer}</div>
      </div>
    </div>
  </div>`;
}

/* ========== SCRIPTS ========== */
function showScript(tipo, addr, tipoImm, mq, prezzo, giorni, proprietario, nagenzie) {
  const p = fmt(prezzo);
  const scripts = {
    whatsapp: `Buongiorno ${proprietario || ''},
ho visto il suo annuncio per ${tipoImm.toLowerCase()} in ${addr}.

Sono un agente immobiliare della zona e ho clienti interessati a questa tipologia.

Sarebbe disponibile per una visita nei prossimi giorni?
Non le rubo più di 20 minuti.

Distinti saluti,
[Il tuo nome] — [La tua agenzia]`,

    telefono: `SCRIPT TELEFONATA — ${addr}

"Buongiorno, sono [Nome], agente immobiliare.
Ho visto il suo annuncio per il ${tipoImm.toLowerCase()} in ${addr}.

Ho clienti che cercano esattamente questa tipologia.
Le farebbe piacere che passassi a dare un'occhiata?
Ci vogliono solo 20 minuti — quando è libero questa settimana?"

[Se chiede la provvigione]:
"Non la disturbo con costi in questa fase — prima vediamo se c'è l'interesse giusto."

[Se dice no]:
"Capisco, posso lasciarle un contatto nel caso cambiasse idea?"`,

    esclusiva: `PROPOSTA MANDATO ESCLUSIVA
${tipoImm} — ${addr}

Gentile proprietario,

le propongo un mandato in esclusiva per la vendita del suo immobile.

Cosa otterrebbe:
• 1 solo referente — nessuna confusione
• Piano marketing professionale (foto, virtual tour, sponsorizzate)
• Accesso alla mia rete di acquirenti già qualificati
• Prezzo di vendita mediamente più alto del 4-7% rispetto al fai-da-te
• Obiettivo: vendere in 60 giorni al miglior prezzo

Sono disponibile per un incontro senza impegno.

[Nome Agente] — [Agenzia] — [Tel]`,

    conquista: `STRATEGIA: CONQUISTARE L'ESCLUSIVA
${addr} (attualmente con ${nagenzie || 'più'} agenzie)

1. APPROCCIO INIZIALE:
"So che ha già delle agenzie — voglio mostrarle cosa faccio di diverso in 15 minuti."

2. ARGOMENTI CHIAVE:
• Con più agenzie il mercato si confonde — gli acquirenti pensano "se è ancora lì c'è qualcosa che non va"
• L'esclusiva crea urgenza e scarsità = prezzo migliore
• Le mostro il mio piano marketing concreto, non promesse

3. LA PROPOSTA:
Esclusiva 90 giorni con clausola di uscita a 45 se non ci sono risultati concreti.

4. CHIUSURA:
"Cosa ha da perdere a provarci per 90 giorni?"`
  };

  const titles = {
    whatsapp: `💬 Messaggio WhatsApp — ${addr}`,
    telefono: `📞 Script telefonata — ${addr}`,
    esclusiva: `📋 Proposta esclusiva — ${addr}`,
    conquista: `🎯 Strategia conquista esclusiva — ${addr}`
  };

  document.getElementById('modal-title').textContent = titles[tipo];
  document.getElementById('modal-body').textContent = scripts[tipo];
  document.getElementById('modal-bg').classList.add('open');
}

function copyModal() {
  const text = document.getElementById('modal-body').textContent;
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.querySelector('.modal-copy');
    btn.textContent = '✔ Copiato!';
    setTimeout(() => btn.textContent = '📋 Copia testo', 2000);
  });
}

function closeModal() {
  document.getElementById('modal-bg').classList.remove('open');
}

/* ========== START ========== */
init();
</script>
</body>
</html>
```

---

## STEP 7 — Avvio con un solo comando

Crea un file `start.sh` nella root del progetto:

```bash
#!/bin/bash
echo "Avvio PropAgent AI..."

# Avvia backend
cd backend
uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!
cd ..

# Avvia scraper scheduler in background
python scraper/scheduler.py &
SCRAPER_PID=$!

echo ""
echo "✅ PropAgent AI avviato!"
echo "🌐 Apri nel browser: file://$(pwd)/frontend/index.html"
echo "🔌 API disponibile su: http://localhost:8000"
echo ""
echo "Premi CTRL+C per fermare tutto"

wait
```

Rendilo eseguibile con: `chmod +x start.sh`

---

## STEP 8 — README

Crea un file `README.md` con le istruzioni:

```markdown
# PropAgent AI

## Avvio
```
./start.sh
```
Poi apri `frontend/index.html` nel browser.

## Aggiornare manualmente gli annunci
Clicca il pulsante "⟳ Aggiorna ora" nell'app, oppure:
```
curl -X POST http://localhost:8000/scraper/avvia
```

## Struttura
- `backend/` — API FastAPI + database SQLite
- `scraper/` — raccoglie annunci da Subito.it ogni 2 ore  
- `frontend/` — interfaccia web (apri direttamente nel browser)
```

---

## NOTE FINALI PER CLAUDE CODE

- Usa **Python 3.10+**
- Il database SQLite si chiama `propagnent.db` e va nella cartella `backend/`
- Se Playwright ha problemi con Subito.it usa `stealth_mode` o un user-agent realistico
- Testa ogni step con un print/log prima di andare avanti
- Alla fine dimmi l'URL esatto per aprire l'app nel browser
