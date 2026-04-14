"""Entry-point unico per Render e per avvio locale."""
import sys
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
# Aggiunge backend/ e scraper/ al path Python
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "scraper"))

# Importa l'app FastAPI (esegue init_db all'import)
from main import app  # noqa: E402, F401

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("start_server:app", host="0.0.0.0", port=port)
