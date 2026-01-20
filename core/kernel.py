import asyncio
import time
import re
from core.provider import LLMProvider
from core.state_manager import StateManager
from core.reranker import Reranker
from core.logger import get_logger
from core.database import DBManager
from modules import load_modules

class Kernel:
    def __init__(self, config_dir: str):
        self.log = get_logger("kernel")
        self.router_log = get_logger("router")
        self.state_manager = StateManager(config_dir)
        self.db = DBManager()
        
        cfg = self.state_manager.config
        self.provider = LLMProvider(cfg["provider"]["base_url"], cfg["provider"]["model"])
        router_model = cfg.get("router", {}).get("model", cfg["provider"]["model"])
        self.router_provider = LLMProvider(cfg["provider"]["base_url"], router_model)
        
        rerank_cfg = cfg.get("reranker", {})
        self.reranker = Reranker(rerank_cfg) if rerank_cfg.get("enabled") else None
        self.modules = load_modules()
        self.log.info("Kernel v1.5 (Origó + Jegyzetelő funkció) aktív.")

    async def process_message(self, user_message: str, conv_id: str = "default_session"):
        """Teljes feldolgozási lánc + ÖNREFLEXIÓ."""
        start_time = time.time()
        module_result = None

        # Ellenőrizzük, hogy belső meta-feladatról van-e szó
        is_task = user_message.strip().startswith("###") or "### task:" in user_message.lower()

        # 1. Router döntés
        needs_search = True
        try:
            router_sys = self.state_manager.config["router"]["system_prompt"]
            decision = await self.router_provider.generate_response(f"Query: {user_message}", system_prompt=router_sys, temp=0.1)
            if "NO" in decision.strip().upper()[:10]:
                needs_search = False
        except Exception as e:
            self.log.error(f"Router hiba: {e}")

        # 2. Keresés / RAG
        if needs_search:
            search_mod = self.modules.get("search")
            if search_mod:
                execute_fn = search_mod.execute if hasattr(search_mod, 'execute') else search_mod.get("execute")
                search_results = await execute_fn(user_message, self.state_manager.config)
                if search_results:
                    if self.reranker:
                        module_result = await self.rerank_results(user_message, search_results)
                    else:
                        module_result = self._simple_combine(search_results)

        # 3. Szintézis
        response = await self.generate_final_response(user_message, module_result, conv_id)

        # 4. ÖNREFLEXIÓ - Csak ha NEM meta-feladat és NEM üres
        if not is_task:
            self.log.info(f"Érdemi beszélgetés észlelve, önreflexió indítása...")
            asyncio.create_task(self._self_reflection(user_message, response, conv_id))
        else:
            self.log.debug("Meta-feladat észlelve, önreflexió kihagyva.")

        self.log.debug(f"Kész. Idő: {time.time() - start_time:.2f}s")
        return response

    async def generate_final_response(self, user_message: str, module_result: dict, conv_id: str):
        """Identitás + Jegyzetek visszatöltése + RAG."""
        base_identity = self.state_manager.assemble_system_prompt()
        model_name = self.state_manager.config["provider"]["model"]
        
        # Jegyzetek leolvasása a falról
        past_notes = self.db.get_notes_for_model(conv_id, model_name)
        note_context = ""
        if past_notes:
            note_context = "\n--- SAJÁT JEGYZETEID (A JEGYZETTÖMBÖDBŐL) ---\n"
            for topic, content in past_notes:
                note_context += f"📌 {topic}: {content}\n"
            note_context += "--- JEGYZETEK VÉGE ---\n"

        # Szigorúbb instruálás a jegyzetek használatára
        instruction = "\nFONTOS: A fenti SAJÁT JEGYZETEK a legfrissebb tények. Használd őket elsődleges forrásként!"
        

        full_system_prompt = f"{base_identity}\n{note_context}\n{instruction}"
        full_system_prompt += "\nKözlési stílus: Tömör, precíz, adatvezérelt. Kerüld a metaforákat."
        

        if module_result:
            full_system_prompt += f"\n--- KÜLSŐ KONTEXTUS ---\n{module_result['context']}\n"

        return await self.provider.generate_response(
            user_message, 
            system_prompt=full_system_prompt, 
            temp=self.state_manager.get_temperature()
        )

    async def _self_reflection(self, user_msg: str, assistant_res: str, conv_id: str):
        try:
            model_name = self.state_manager.config["provider"]["model"]
            # Kicsit szigorúbb prompt, hogy tiszta listát kapjunk
            # Módosított prompt a kernel.py-ban:
            reflection_prompt = (
                "### TASK: EXTRACT TECHNICAL FACTS ONLY\n"
                "Extract parameters, error codes, and hard rules from the text.\n"
                "IGNORE metaphors, jokes, and conversational filler.\n"
                "FORMAT: Topic: Value\n"
                "STRICT RULE: Only output the list. No intro, no outro."
            )
            context = f"User: {user_msg}\nAI: {assistant_res}"
            
            reflection = await self.router_provider.generate_response(context, system_prompt=reflection_prompt, temp=0.1)
            # 1. Beolvassuk a már meglévő jegyzeteket a szűréshez
            past_notes = self.db.get_notes_for_model(conv_id, model_name)
            existing_contents = [c.strip() for t, c in past_notes] if past_notes else []

            for line in reflection.split('\n'):
                # Csak akkor foglalkozunk a sorral, ha van benne kettőspont
                if ":" in line and len(line) > 10:
                    clean_line = re.sub(r'^[* \-\d.]+', '', line)
                    parts = clean_line.split(":", 1)
                    
                    if len(parts) == 2:
                        topic_tag = parts[0].strip()[:50]
                        content = parts[1].strip()

                        # 2. ELLENŐRZÉS: Csak akkor mentünk, ha ez az információ még nincs meg
                        if content not in existing_contents:
                            self.db.add_short_term_note(
                                conv_id=conv_id, 
                                model_origin=model_name, 
                                topic_tag=topic_tag, 
                                content=content
                            )
                            self.log.info(f"Új adat rögzítve: {topic_tag}")
                            # Frissítjük a listát, hogy egy válaszon belül se legyen duplikáció
                            existing_contents.append(content) 
                        else:
                            self.log.debug(f"Adat már ismert, rögzítés kihagyva: {topic_tag}")
            
            self.log.info(f"Reflexió szűrve és rögzítve a(z) {conv_id} csőhöz.")
        except Exception as e:
            self.log.error(f"Reflexió hiba: {e}")

    def _simple_combine(self, results):
        ctx = ""
        for i, r in enumerate(results[:3]):
            ctx += f"[{r['title']}]: {r['content']}\n"
        return {"context": ctx, "source": "Web"}

    async def rerank_results(self, query: str, search_results: list):
        """A találatok intelligens pontozása."""
        rag_cfg = self.state_manager.config.get("rag", {})
        threshold = rag_cfg.get("threshold", 0.15)
        passed_contents = []
        sources = []

        for i, res in enumerate(search_results):
            content = res.get('content', '')
            title = res.get('title', 'Weboldal')
            # A reranker dönti el, mennyire releváns a szöveg a kérdéshez
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