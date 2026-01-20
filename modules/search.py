import httpx
import urllib.parse
import re
import asyncio
from bs4 import BeautifulSoup
from core.logger import get_logger

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
            return text[:3000] # Megemelt keret a 12B-nek
    except Exception as e:
        log.error(f"Scrape hiba ({url}): {e}")
        return None

async def execute(query: str, config: dict = None):
    search_cfg = config.get("search", {}) if config else {}
    base_url = search_cfg.get("url", "http://127.0.0.1:8888")
    
    # Query finomítás: csak a legszükségesebb zajt vesszük ki
    q = query.lower()
    q = re.sub(r"^(szia|üdv|helló|mondd meg|keress rá)[\s,]*", "", q).strip()
    
    if not q:
        log.warning("Üres keresési kifejezés, abortálás.")
        return []

    encoded_query = urllib.parse.quote_plus(q)
    # Fontos: format=json és néha apageno=1 segíthet
    url = f"{base_url}/search?q={encoded_query}&format=json"
    
    log.info(f"Keresés indítása a SearXNG-n: '{q}'")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            if response.status_code != 200:
                log.error(f"SearXNG hiba: HTTP {response.status_code}")
                return []
                
            data = response.json()
            raw_results = data.get("results", [])
            
            if not raw_results:
                log.warning(f"SearXNG nem adott találatot erre: '{q}'")
                return []

            log.info(f"SearXNG {len(raw_results)} találatot adott. Scrape indítása a top 3-ra...")
            
            # Csak az első 3-at scrape-eljük a sebesség miatt
            scrape_tasks = [scrape_url(client, r.get("url")) for r in raw_results[:3]]
            scraped_data = await asyncio.gather(*scrape_tasks)

            formatted_results = []
            for i, r in enumerate(raw_results[:3]):
                content = scraped_data[i] if (i < len(scraped_data) and scraped_data[i]) else r.get("content", "")
                formatted_results.append({
                    "title": r.get("title", "Cím nélkül"),
                    "link": r.get("url", ""),
                    "content": content
                })
            
            return formatted_results 

    except Exception as e:
        log.error(f"Search modul kritikus hiba: {e}")
        return []