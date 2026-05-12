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
