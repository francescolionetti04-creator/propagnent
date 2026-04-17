"""Entry-point unico per Render e per avvio locale."""
import sys
import os
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
# Aggiunge backend/ e scraper/ al path Python
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "scraper"))

# Importa l'app FastAPI (esegue init_db all'import)
from main import app  # noqa: E402, F401

# RSS Watcher — disabilitato su Render: Subito.it restituisce 403 sugli IP cloud.
# Per uso locale: decommenta le righe qui sotto.
# try:
#     from rss_watcher import avvia_rss_watcher
#     threading.Thread(target=avvia_rss_watcher, daemon=True, name="rss-watcher").start()
#     print("[Startup] RSS Watcher avviato in background (ogni 5 min)")
# except Exception as _e:
#     print(f"[Startup] RSS Watcher non avviato: {_e}")
print("[Startup] RSS Watcher disabilitato su Render (403 IP cloud)")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("start_server:app", host="0.0.0.0", port=port)
