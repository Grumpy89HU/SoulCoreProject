import httpx
import urllib.parse
import re
import asyncio
import hashlib
from bs4 import BeautifulSoup
from core.logger import get_logger
from core.database import DBManager  # Most már a database.py-t használjuk

log = get_logger("module_search")

async def scrape_url(client, url):
    """Beolvassa az URL-t és tiszta szöveget csinál belőle."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = await client.get(url, timeout=5.0, follow_redirects=True, headers=headers)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for s in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                s.decompose()
            text = soup.get_text(separator=' ', strip=True)
            return text[:3000] 
    except Exception as e:
        log.error(f"Scrape hiba ({url}): {e}")
        return None

async def execute(query: str, config: dict = None):
    db = DBManager()
    
    # 1. Query tisztítás és Hash (Origó: A redundancia kiszűrése)
    q = query.lower()
    q = re.sub(r"^(szia|üdv|helló|mondd meg|keress rá)[\s,]*", "", q).strip()
    if not q: return []
    
    query_hash = hashlib.md5(q.encode()).hexdigest()

    # 2. Cache ellenőrzés (12 órás ablak)
    cached_data = db.get_cached_search(query_hash)
    if cached_data:
        log.info(f"CACHE TALÁLAT: '{q}' adatai az adatbázisból betöltve.")
        return cached_data

    # 3. Ha nincs cache: SearXNG + Scrape
    search_cfg = config.get("search", {}) if config else {}
    base_url = search_cfg.get("url", "http://127.0.0.1:8888")
    
    log.info(f"Nincs érvényes cache. SearXNG indítása: '{q}'")
    
    encoded_query = urllib.parse.quote_plus(q)
    url = f"{base_url}/search?q={encoded_query}&format=json"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            if response.status_code != 200: return []
                
            raw_results = response.json().get("results", [])[:3]
            if not raw_results: return []

            # Scrape indítása a top találatokra
            scrape_tasks = [scrape_url(client, r.get("url")) for r in raw_results]
            scraped_data = await asyncio.gather(*scrape_tasks)

            formatted_results = []
            for i, r in enumerate(raw_results):
                # Ha a scrape sikeres volt, azt használjuk, ha nem, a snippetet
                content = scraped_data[i] if (i < len(scraped_data) and scraped_data[i]) else r.get("content", "")
                formatted_results.append({
                    "title": r.get("title", "Cím nélkül"),
                    "link": r.get("url", ""),
                    "content": content
                })
            
            # 4. Mentés az adatbázisba jövőbeli használatra
            db.save_search(query_hash, q, formatted_results)
            log.info(f"Keresés kész. Eredmények 12 órára cache-elve.")
            
            return formatted_results 

    except Exception as e:
        log.error(f"Search modul kritikus hiba: {e}")
        return []