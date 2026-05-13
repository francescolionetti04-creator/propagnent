# Istruzioni Test Manuali — HouseRadar

## Test Script AI (Sprint 4 Task A) dopo deploy

Prerequisiti:
- Deploy su Render completato
- `ANTHROPIC_API_KEY` configurata su Render (formato `sk-ant-api03-...`)
- Almeno un annuncio presente nel DB

Procedura:
1. Login come `info@houseradar.it` (agente founder)
2. Vai su `/app`, trova una card annuncio
3. Click bottone `Script` sulla card
4. Aspetta 3–5 sec → deve apparire modal con script generato AI
5. Se errore **503** → manca `ANTHROPIC_API_KEY` su Render
6. Se errore **401** → user non è agente o non è in trial/active
7. Verifica WhatsApp: click "Apri WhatsApp" → si apre `wa.me` con script pre-compilato
8. Verifica Rigenera: produce uno script diverso (decrementa contatore quota se presente)

## Test Welcome Tutorial Modal (Sprint 5.0.2)

1. Crea un nuovo utente agente (NON founder) con subscription `trialing` o `active`
2. Primo login su `/app` → deve apparire modal "Benvenuto in HouseRadar, {nome}!"
3. Click "Ho capito, vai alla dashboard" → POST `/api/agente/tutorial-visto` → modal chiuso
4. Refresh `/app` → modal NON deve più apparire (tutorial_visto=true)
5. Test "Salta per ora": al prossimo accesso il modal riappare (tutorial_visto resta false)
6. Test ESC: chiude modal SENZA marcare visto
7. Test con founder: il modal NON deve mai apparire

## Test Fix Ricerca Geografica (Sprint 5.0.2 SX)

Bug fixato: cercare "Cecina" mostrava 0 annunci perché `citta` e `provincia` erano
NULL nel DB. Sprint 5.0.2 SX normalizza i 444 annunci esistenti e abilita ricerca
testo + dropdown cascade Provincia → Città.

Prerequisiti:
- Deploy su Render completato (la migration `normalize_annunci_geo` parte
  automaticamente al primo boot, una sola volta, marcata in `app_config`).

Procedura:
1. **API zone disponibili**: `GET https://houseradar.it/api/agente/zone-disponibili`
   (con cookie sessione agente loggato)
   - Deve ritornare 10 province toscane con `count > 0` ciascuna
   - Es. atteso: `{"province":[{"codice":"LI","nome":"Livorno","count":96},...]}`
2. **Filtro provincia**: `GET https://houseradar.it/annunci?provincia=LI`
   - Deve ritornare ~96 annunci, tutti con `provincia:"LI"` nel JSON
3. **Filtro città**: `GET https://houseradar.it/annunci?provincia=LI&citta=Cecina`
   - Deve ritornare ~7 annunci di Cecina (numero esatto dipende da DB live)
   - Tutti con `citta:"Cecina"`, `provincia:"LI"`
4. **Ricerca testo libera**: `GET https://houseradar.it/annunci?q=Aurelia`
   - Deve ritornare annunci con "Aurelia" nell'indirizzo (case-insensitive)
5. **Frontend dropdown cascade**: login su `/app`
   - Sidebar filtri sezione "Annunci": dropdown Provincia popolato con
     "Livorno (N)", "Pisa (N)", … con counter live
   - Cambiando provincia, il dropdown Città si popola con i comuni di quella provincia
   - Quando Provincia = "Tutte le province", il dropdown Città è disabled
6. **Campo ricerca testo**: input "🔍 Cerca indirizzo, via o località" sopra i filtri
   - Digitando ad es. "Aurelia" → debounce 300ms → ricarica con `?q=Aurelia`
   - Contatore "🏠 N annunci trovati" si aggiorna in tempo reale
7. **Test scenario Gianluca**: seleziona Livorno → Cecina nei dropdown
   - Devono apparire ~7 card annunci di Cecina (non più ZERO)
8. **Empty state user-friendly**: prova `provincia=GR&citta=Pisa` (mismatch)
   - Deve mostrare "🔍 Nessun annuncio trovato con questi filtri.
     Prova a rimuovere qualche filtro o cerca con un termine più generico."

## Test Sprint 5 — WhatsApp Auto-Acquisizione (Killer App #3)

Killer App #3: l'agente clicca un bottone su un annuncio di privato, il
backend genera un messaggio WhatsApp personalizzato con Claude Sonnet 4.5,
l'agente lo modifica se vuole e apre WhatsApp con messaggio precompilato +
numero del privato. Backend traccia status (inviato/letto/risposto).

Prerequisiti:
- `ANTHROPIC_API_KEY` configurata su Render
- Login come agente con subscription `trialing` o `active`
- Almeno un annuncio di privato con telefono valido (es. seedato)

Procedura:
1. Login come `info@houseradar.it`
2. Vai su `/app`, trova un annuncio di privato (chip verde "💚 Privato")
   con un numero di telefono (vedi card)
3. Click bottone **"💬 WhatsApp Auto"** sulla card
4. Aspetta 3-5 secondi → deve apparire modal "💬 WhatsApp Auto — {indirizzo}"
   con un messaggio italiano dentro la textarea (~80 parole, tono colloquiale)
5. Verifica counter caratteri sotto la textarea ("X caratteri")
6. Modifica liberamente il messaggio nella textarea
7. Click **"📱 Apri WhatsApp"** →
   - POST `/api/agente/whatsapp/invia` salva il record nel DB
   - Si apre `https://wa.me/393...` con il messaggio precompilato in WhatsApp Web/App
   - Toast "✓ Messaggio salvato. WhatsApp aperto." in fondo allo schermo
   - Modal si chiude
8. Sidebar → click **"💬 WhatsApp"** (tra "Lead proprietari" e "Chat (Presto)")
   - Counter sidebar mostra "1" (messaggio appena inviato, status='inviato')
   - Tab "Tutti" / "Inviati" / "Letti" / "Risposti" / "Senza risposta"
   - Lista mostra card: foto annuncio (o icona 🏠), indirizzo, prezzo,
     telefono mascherato (`+39 33X ●●● ●●XX`), data ("adesso"/"X min fa"),
     badge "🔵 Inviato", anteprima messaggio (3 righe)
9. Click sulla card → si apre modal dettaglio:
   - Messaggio completo
   - Dropdown status → cambia a **"✅ Risposto"** → "✓ Salvato"
   - Verifica: torna alla lista, badge cambia a "✅ Risposto"
   - Counter sidebar "💬 WhatsApp" scende a 0 (non più 'inviato')
10. Riapri il dettaglio → scrivi qualcosa nelle "Note private" →
    auto-save dopo ~800ms con "✓ Salvato automaticamente"
11. Click "📱 Riapri WhatsApp" → riapre `wa.me/` con lo stesso numero+messaggio
12. Click "📋 Copia testo" → toast "📋 Testo copiato"
13. Click "🗑 Elimina" → conferma → record marcato `removed_at`, sparisce dalla lista

Test edge cases:
- **Annuncio senza telefono**: click "💬 WhatsApp Auto" → backend ritorna **400**
  con messaggio "Questo annuncio non ha un numero di telefono..." → modal
  mostra errore + bottone "🔄 Rigenera" disponibile
- **Numero fisso (inizia con 0)**: la `normalizzaTelefono()` lato frontend
  rileva il caso e mostra warning rosso "Questo è un numero fisso, WhatsApp
  non funziona. Usa Script Chiamata per chiamarli." Bottone "📱 Apri WhatsApp"
  è disabilitato. Bottone "🔄 Rigenera" e "📋 Copia testo" restano attivi.
- **Rate limit (>20/h)**: 21° generazione consecutiva ritorna **429** con
  messaggio "Hai raggiunto il limite di 20 messaggi/ora. Riprova tra X min."
- **Errore Anthropic**: se `ANTHROPIC_API_KEY` non c'è o l'API è giù →
  **503** con "Servizio AI temporaneamente non disponibile. Riprova..."
- **ESC chiude i modali**: WhatsApp Auto → ESC → chiuso; Dettaglio → ESC → chiuso

Endpoints attesi (curl con cookie sessione):
- `POST   /api/agente/whatsapp/genera/{annuncio_id}` → `{messaggio, telefono}`
- `POST   /api/agente/whatsapp/invia`                → `{success:true, id}` (body: `{annuncio_id, telefono, messaggio}`)
- `GET    /api/agente/whatsapp/inbox`                → `{messaggi[], counters{}}`
- `PATCH  /api/agente/whatsapp/{id}/status`          → `{success:true}` (body: `{status}` e/o `{note}`)
- `DELETE /api/agente/whatsapp/{id}`                 → `{success:true}` (soft delete)


## Test Sprint 5.1 — Manual phone input (annuncio senza telefono)

Premessa: oggi quasi nessun annuncio ha il campo `telefono` popolato (gli scraper
non riescono a estrarre il numero, Sprint 5.2 lo risolverà con Playwright).
Sprint 5.1 introduce un input manuale del numero direttamente nel modal
"💬 WhatsApp Auto" così l'agente può comunque procedere.

1. Login come `info@houseradar.it` (founder).
2. Vai su `/app`, trova una card di privato **senza telefono** (la maggior parte oggi).
3. Click **"💬 WhatsApp Auto"** sulla card.
4. Modal si apre con uno spinner breve "Verifico annuncio…".
5. Backend ritorna **400** con `detail.error="no_phone"` → appare lo **STEP 0**:
   - Icona 📞
   - Titolo "Numero non disponibile"
   - Testo "Questo annuncio non ha un telefono nel nostro database…"
   - Pulsante azzurro **"🔗 Apri annuncio originale ↗"** che apre `url_originale`
     in nuova scheda (verifica)
   - Label "Numero del privato"
   - Input `<input type="tel">` con placeholder "+39 333 1234567"
   - Help text grigio "Formato: numero italiano con prefisso +39"
   - Pulsanti **"Annulla"** + **"✓ Genera messaggio"** (quest'ultimo disabilitato)
6. Validazione real-time mentre digiti:
   - Vuoto → help "Inserisci un numero" rosso, bottone disabilitato
   - `0123` (fisso) → help "I numeri fissi non supportano WhatsApp" rosso
   - `333 12` (<9 cifre) → help "Numero troppo corto" rosso
   - `333 1234567 1234567` (>13 cifre) → help "Numero troppo lungo" rosso
   - `333 1234567` (valido) → help **"✓ Verrà usato: +39 333 1234567"** verde,
     bottone abilitato
7. Click **"✓ Genera messaggio"** → spinner "Generando messaggio con AI…" →
   modal cambia: appare la textarea col messaggio AI, telefono mascherato
   `+39 333 ●●● ●●67` sotto.
8. Click **"📱 Apri WhatsApp"** → si apre `https://wa.me/393331234567?text=…`
   con il messaggio precompilato; il record viene salvato lato server con il
   numero inserito manualmente.
9. Vai sulla tab **"💬 WhatsApp"** in sidebar → il record appare in lista con
   il numero che hai inserito manualmente, status "🔵 Inviato".

Banner suggerimento:
- Apri tab "💬 WhatsApp" la prima volta → in alto compare il banner azzurro
  "💡 Suggerimento: se un annuncio non ha telefono…" con la X in alto a destra.
- Click su X → il banner sparisce e `localStorage.wa_banner_dismissed === "1"`.
- Refresh pagina → il banner resta nascosto (persistenza ok).

Edge cases Sprint 5.1:
- **Annuncio CON telefono in DB**: il flusso resta quello di Sprint 5 — nessun
  STEP 0, modal va diretto allo spinner di generazione AI.
- **Numero manuale invalido inviato al backend**: se l'agente bypassa il
  frontend, il backend valida via `_wa_normalize_it_phone` e ritorna 400
  "Numero non valido per WhatsApp."
- **Rigenera (♻)** dopo STEP 0: il pulsante "🔄 Rigenera" riusa lo stesso
  numero manuale (`_waUsedManual=true`) — non riapre lo STEP 0.
- **ESC su STEP 0**: chiude il modal (equivale ad "Annulla").

Endpoints aggiornati Sprint 5.1:
- `POST /api/agente/whatsapp/genera/{annuncio_id}?telefono=<num>` →
  - 200 `{messaggio, telefono}` se ann.telefono presente OPPURE `?telefono` passato
  - 400 `{detail:{error:"no_phone", detail, url_originale}}` se nessun telefono disponibile
- `POST /api/agente/whatsapp/invia` body ora ha `telefono` opzionale; se assente,
  fallback su `annuncio.telefono` del DB.

## Test Sprint 5.1.1 — UX refinement WhatsApp

Obiettivo: il bottone WhatsApp deve apparire solo dove ha davvero senso e con
uno styling che comunichi al volo se l'agente farà 1 click o se dovrà inserire
il numero a mano. Il help text dello STEP 0 non deve mai mostrare "errori"
prima che l'utente abbia interagito col campo.

Differenziazione bottoni per tipo annuncio:
1. Vai su `/app`, scrolla la lista delle card annunci.
2. Verifica i bottoni nel footer di ogni card a seconda del tipo:
   - **Annuncio AGENZIA** (badge grigio "Agenzia"): **NESSUN** bottone
     WhatsApp. Se l'annuncio ha un `telefono` nel DB, compare invece
     **"📞 Chiama"** (cf-blue) che apre `tel:<numero>`. Se non c'è telefono,
     il bottone Chiama è omesso del tutto.
   - **Annuncio PRIVATO CON telefono** (badge verde "Privato"): bottone
     **"💬 WhatsApp Auto"** in verde tenue **pieno**, con font-weight 600 e
     leggera ombra (classe `cf-prominent` aggiuntiva).
   - **Annuncio PRIVATO SENZA telefono** (badge verde "Privato", tel mancante):
     bottone **"💬 WhatsApp"** in stile **outline** (bordo verde HouseRadar
     #0F6E56, sfondo trasparente, testo verde) — comunica visivamente che
     "richiede un passaggio in più".
   - **Annuncio NO ESCLUSIVA** (badge arancio): nessun WhatsApp,
     comportamento Conquista/Script/Valuta invariato + eventuale Chiama se
     telefono presente.
3. **Hover desktop** sul bottone "💬 WhatsApp" outline → appare il tooltip
   nativo `Telefono non in database — sarà richiesto inserimento manuale`.
4. Click sul bottone outline → si apre il modal WhatsApp Auto direttamente
   sullo **STEP 0** (numero non disponibile).
5. Click sul bottone "💬 WhatsApp Auto" pieno → modal va dritto allo spinner
   "Verifico annuncio…" e poi alla generazione AI (flusso Sprint 5 invariato).

Fix help text STEP 0 (stato touched):
6. Riapri lo STEP 0 (click sul bottone outline di un annuncio privato senza
   telefono):
   - **Stato iniziale** (input vuoto, mai toccato): help text grigio
     **"Formato: numero italiano con o senza prefisso +39"**. NON deve
     comparire "Inserisci un numero" rosso.
   - Pulsante "✓ Genera messaggio" disabilitato.
7. Digita `0` → help **"I numeri fissi non supportano WhatsApp"** ROSSO.
8. Digita `333 12` → help **"Numero troppo corto"** ROSSO.
9. Digita `333 1234567 1234567` → help **"Numero troppo lungo"** ROSSO.
10. Digita `333 1234567` (valido) → help **"✓ Verrà usato: +39 333 1234567"**
    verde, pulsante abilitato.
11. **Cancella tutto** dal campo (Ctrl+A → Backspace): l'input torna vuoto e
    il help text torna **grigio neutro** "Formato: numero italiano con o senza
    prefisso +39" (non rosso!). Pulsante disabilitato.
12. Chiudi e riapri il modal: il touched torna a `false`, il help è di nuovo
    quello iniziale grigio.

Vincoli rispettati:
- Backend Sprint 5/5.1 invariato (endpoint, validazione, DB).
- Nessuna modifica a scraper, scheduler, index/pricing/profilo_pubblico.
- Retro-compatibilità: privato con telefono → flusso Sprint 5 diretto.

