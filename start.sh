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
echo "PropAgent AI avviato!"
echo "Apri nel browser: file://$(pwd)/frontend/index.html"
echo "API disponibile su: http://localhost:8000"
echo ""
echo "Premi CTRL+C per fermare tutto"

trap "kill $BACKEND_PID $SCRAPER_PID 2>/dev/null" EXIT
wait
