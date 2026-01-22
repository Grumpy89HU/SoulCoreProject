import httpx
import asyncio
from core.database import DBManager
from core.logger import get_logger

log = get_logger("ollama_core")

async def discover_models_loop():
    """Percenkénti ellenőrzés az Ollama modellek után."""
    db = DBManager()
    
    while True:
        async with httpx.AsyncClient() as client:
            try:
                # Az Ollama API lekérdezése
                response = await client.get("http://localhost:11434/api/tags", timeout=5.0)
                
                if response.status_code == 200:
                    models = response.json().get('models', [])
                    for m in models:
                        tag = m.get('name')
                        size = m.get('size')
                        
                        # SQL HELYETT: Meghívjuk a dedikált metódust
                        db.update_ollama_model(tag, size)
                    
                    log.debug(f"Ollama szinkron kész: {len(models)} modell.")
                
            except Exception as e:
                log.error(f"Ollama Discovery hiba: {e}")

        # Várakozás 60 másodpercig (vagy amennyit a config engedne)
        await asyncio.sleep(60)

# Elindítás a main.py-ban:
# asyncio.create_task(discover_models_loop())
async def ollama_generate(model: str, prompt: str):
    """Szöveggenerálás az Ollama API-val httpx használatával."""
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False # A belső monológokhoz nem kell stream, egyben kérjük a választ
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, timeout=30.0)
            if response.status_code == 200:
                return response.json().get("response", "")
            else:
                log.error(f"Ollama hiba: {response.status_code}")
                return ""
        except Exception as e:
            log.error(f"Ollama hívás hiba: {e}")
            return ""