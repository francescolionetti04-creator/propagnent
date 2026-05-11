# PropAgent AI

Radar annunci immobiliari per agenti — trova privati e non in esclusiva prima degli altri.

## Avvio rapido

```bash
./start.sh
```

Poi apri `frontend/index.html` nel browser.

## Avvio manuale

```bash
# Backend (in una finestra terminale)
cd backend
uvicorn main:app --reload --port 8000

# Scraper scheduler (in un'altra finestra)
python scraper/scheduler.py
```

## Aggiornare manualmente gli annunci

Clicca il pulsante **⟳ Aggiorna ora** nell'app, oppure:

```bash
curl -X POST http://localhost:8000/scraper/avvia
```

## Struttura

```
propagnent/
├── backend/
│   ├── main.py          API FastAPI
│   ├── database.py      Gestione SQLite
│   ├── models.py        Struttura dati
│   └── requirements.txt
├── scraper/
│   ├── scraper.py       Raccoglie annunci da Subito.it
│   └── scheduler.py     Esegue lo scraper ogni 2 ore
└── frontend/
    └── index.html       Interfaccia web
```

## API

- `GET /annunci` — lista annunci (filtri: zona, tipo, fonte, sort, prezzo_max)
- `GET /stats` — statistiche aggregate
- `GET /alert` — nuovi annunci nelle ultime 2 ore
- `POST /scraper/avvia` — avvia scansione manuale

## Auth + Stripe (Sprint 2.1)

Endpoints:
- `POST /auth/signup` `{email,password,role,nome?,cognome?,telefono?,city?}` → invia email verifica
- `POST /auth/login` `{email,password}` → setta cookie `hr_session` (JWT, 7gg)
- `POST /auth/logout`
- `GET  /auth/verify?token=...` → marca email come verificata, redirect /accedi?verified=1
- `POST /auth/forgot-password` `{email}` → invia link di reset (1h validità)
- `POST /auth/reset-password` `{token,new_password}`
- `GET  /auth/me` → user corrente (richiede cookie)
- `GET  /api/me` → user corrente o `{user:null}`
- `POST /api/stripe/create-checkout-session` `{plan:'solo'|'agenzia', interval:'month'|'year'}`
- `POST /api/stripe/customer-portal`
- `POST /api/stripe/webhook` (firma `Stripe-Signature`)

Pagine pubbliche: `/`, `/pricing`, `/accedi`, `/signup`, `/forgot-password`,
`/reset-password`. Pagina protetta: `/app` (require_paid).

### ENV vars da settare su Render

```bash
# Generato con: python -c "import secrets; print(secrets.token_urlsafe(32))"
JWT_SECRET=<random-32-bytes>

# Resend.com (test ok con dominio onboarding@resend.dev finché DNS non sono ok)
RESEND_API_KEY=re_xxx
EMAIL_FROM="HouseRadar <onboarding@resend.dev>"

# Stripe test mode
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_PUBLISHABLE_KEY=pk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx

# Per i link nelle email + redirect Stripe
APP_BASE_URL=https://houseradar.it
```

### Founder bypass

5 founder vengono seedati al primo boot (tabella `users` vuota):
- info@houseradar.it (agente)
- francescolionetti04@gmail.com (privato)
- jmk.condor@libero.it (privato)
- gianlucacelli02@gmail.com (consulente)
- (5° slot Tommaso, da attivare in `scripts/seed_founders.py`)

Founder = `is_founder=true` + `is_email_verified=true`. Bypassano paywall.
Per il primo accesso: usa `/forgot-password` con la tua email.

## VPS Setup (systemd)

Il file `scripts/houseradar-scheduler.service` configura lo scheduler scraper come
servizio systemd persistente sul VPS (auto-restart, log su `/var/log/houseradar-scheduler.log`).

```bash
# Una sola volta sul VPS (46.224.225.174):
ssh root@46.224.225.174
cd /root/propagnent
git pull
sudo cp scripts/houseradar-scheduler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable houseradar-scheduler
sudo systemctl start houseradar-scheduler
sudo systemctl status houseradar-scheduler  # verifica che sia "active (running)"
```

Comandi utili dopo l'installazione:

```bash
sudo systemctl restart houseradar-scheduler        # riavvio (dopo git pull)
sudo journalctl -u houseradar-scheduler -f         # log live via journal
tail -f /var/log/houseradar-scheduler.log          # log file diretto
sudo systemctl stop houseradar-scheduler           # ferma
```

