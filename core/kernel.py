import asyncio
import time
import re
from core.provider import LLMProvider
from core.state_manager import StateManager
from core.reranker import Reranker
from core.logger import get_logger
from modules import load_modules 

class Kernel:
    def __init__(self, config_dir: str):
        self.log = get_logger("kernel")
        self.router_log = get_logger("router")
        
        self.state_manager = StateManager(config_dir)
        cfg = self.state_manager.config
        
        # Fő modell (12B) és Router (4B) szolgáltatók
        self.provider = LLMProvider(cfg["provider"]["base_url"], cfg["provider"]["model"])
        router_model = cfg.get("router", {}).get("model", cfg["provider"]["model"])
        self.router_provider = LLMProvider(cfg["provider"]["base_url"], router_model)
        
        # Reranker szelektív betöltése
        rerank_cfg = cfg.get("reranker", {})
        if rerank_cfg.get("enabled"):
            self.reranker = Reranker(rerank_cfg)
        else:
            self.reranker = None
            self.log.info("Reranker kikapcsolva - betöltés átugorva.")
        
        # Modulok betöltése (pl. search.py)
        self.modules = load_modules()
        self.log.info(f"Kernel v1.3.6 (Origó) aktív. Fő: {cfg['provider']['model']} | Router: {router_model}")

    async def process_message(self, user_message: str):
        """A bejövő üzenet teljes feldolgozási lánca."""
        start_time = time.time()
        module_result = None

        # 1. BYPASS - Rendszerfeladatok (ne menjenek keresőre)
        if user_message.strip().startswith("### Task:"):
            return await self.generate_final_response(user_message)

        # 2. ROUTER DÖNTÉS
        router_sys = self.state_manager.config["router"]["system_prompt"]
        needs_search = True # Biztonsági alapértelmezés
        
        try:
            decision = await self.router_provider.generate_response(
                f"Query: {user_message}",
                system_prompt=router_sys,
                temp=0.1
            )
            # 4B-re optimalizált döntés: csak akkor NO, ha az egyértelműen szerepel
            if "NO" in decision.strip().upper()[:10]:
                needs_search = False
                self.router_log.info(f"DÖNTÉS: NO - Belső tudás használata.")
            else:
                self.router_log.info(f"DÖNTÉS: YES (Router kimenet: '{decision.strip()}')")
        except Exception as e:
            self.log.error(f"Router hiba, fallback YES-re: {e}")

        # 3. KERESÉS ÉS ADATFELDOLGOZÁS (RAG Lánc)
        if needs_search:
            search_mod = self.modules.get("search")
            if search_mod:
                # Keresési kifejezés tisztítása a Scraper számára
                search_query = re.sub(r"^(Szia|Helló|Üdv|Szevasz)[\s,]*", "", user_message, flags=re.IGNORECASE).strip()
                
                execute_fn = search_mod.execute if hasattr(search_mod, 'execute') else search_mod.get("execute")
                search_results = await execute_fn(search_query, self.state_manager.config)
                
                if search_results:
                    # Reranker megkísérlése, ha engedélyezve van
                    if self.reranker:
                        module_result = await self.rerank_results(user_message, search_results)
                    
                    # FALLBACK: Ha nincs reranker VAGY az mindent kiszűrt
                    if not module_result:
                        self.log.info("RAG Fallback: Top találatok strukturált összefűzése.")
                        combined_context = ""
                        sources = []
                        for i, r in enumerate(search_results[:3]):
                            content = r.get('content', '')
                            if content:
                                # Strukturált jelölés a 12B modellnek a jobb figyelemért
                                combined_context += f"--- DOKUMENTUM {i+1} (Forrás: {r['title']}) ---\n{content}\n\n"
                                sources.append(r['title'])
                        
                        if combined_context:
                            module_result = {
                                "context": combined_context.strip(),
                                "source": ", ".join(sources)
                            }
            else:
                self.log.error("Search modul nem található a rendszerben!")

        # 4. SZINTÉZIS (Végső válasz generálása)
        elapsed = time.time() - start_time
        self.log.debug(f"Kernel feldolgozási idő: {elapsed:.2f}s")
        return await self.generate_final_response(user_message, module_result)

    async def generate_final_response(self, user_message: str, module_result: dict = None):
        """
        Szigorú RAG szintézis: csak a kapott kontextusból dolgozik, ha az elérhető.
        """
        if module_result and module_result.get("context"):
            # Ez a sablon kényszeríti ki a forrásalapú válaszadást
            rag_prompt = (
                "Használd az alábbi dokumentumrészleteket a válaszadáshoz. "
                "Ha nem találod benne a választ, mondd azt, hogy nem tudod.\n\n"
                f"Kontextus:\n{module_result['context']}\n\n"
                f"A talált dokumentumok forrása: {module_result.get('source', 'Ismeretlen forrás')}"
            )
            
            final_query = f"Felhasználó kérdése: {user_message}"
            self.log.info(f"RAG szintézis indítása (Források: {module_result.get('source')})")
            
            # RAG esetén temp=0.0 a precizitásért
            return await self.provider.generate_response(final_query, system_prompt=rag_prompt, temp=0.0)

        else:
            # Fallback a modell belső tudására, ha nincs külső kontextus
            system_prompt = self.state_manager.assemble_system_prompt()
            temp = self.state_manager.get_temperature()
            self.log.info("Nincs releváns kontextus, szintézis belső tudás alapján.")
            return await self.provider.generate_response(user_message, system_prompt, temp)

    async def rerank_results(self, query: str, search_results: list):
        """A találatok pontozása és szűrése küszöbérték alapján."""
        rag_cfg = self.state_manager.config.get("rag", {})
        threshold = rag_cfg.get("threshold", 0.15)
        passed_contents = []
        sources = []

        for i, res in enumerate(search_results):
            content = res.get('content', '')
            title = res.get('title', 'Weboldal')
            score = self.reranker.get_local_score(query, f"{title} {content}")
            
            if score >= threshold:
                passed_contents.append(f"--- DOKUMENTUM {i+1} (Forrás: {title}) ---\n{content}")
                sources.append(title)

        if passed_contents:
            return {
                "context": "\n\n".join(passed_contents),
                "source": ", ".join(list(set(sources)))
            }
        return None