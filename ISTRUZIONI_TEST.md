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
