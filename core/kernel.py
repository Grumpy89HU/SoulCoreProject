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
        self.log.info("Kernel v1.5 (Origó + Unified Memory) aktív.")

    async def process_message(self, user_message: str, conv_id: str = "default_session"):
        """Teljes feldolgozási lánc + Memória beolvasás + Önreflexió."""
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

        # --- MEMÓRIA ÉS JEGYZETEK ELŐKÉSZÍTÉSE ---
        # Itt olvassuk ki az adatokat a DB-ből
        current_notes = self.db.get_notes_for_conversation(conv_id)
        global_memories = self.db.get_long_term_memories()
        
        # 3. Szintézis (Átadjuk a plusz infókat a generálónak)
        response = await self.generate_final_response(
            user_message, 
            module_result, 
            conv_id, 
            notes=current_notes, 
            memories=global_memories
        )

        # 4. ÖNREFLEXIÓ - Csak ha NEM meta-feladat
        if not is_task:
            self.log.info(f"Érdemi beszélgetés észlelve, önreflexió indítása...")
            asyncio.create_task(self._self_reflection(user_message, response, conv_id))
        else:
            self.log.debug("Meta-feladat észlelve, önreflexió kihagyva.")

        self.log.debug(f"Kész. Idő: {time.time() - start_time:.2f}s")
        return response

    async def generate_final_response(self, user_message: str, module_result: dict, conv_id: str, notes=None, memories=None):
        """Identitás + Jegyzetek + Memória + RAG összeillesztése."""
        base_identity = self.state_manager.assemble_system_prompt()
        
        # 1. JEGYZETEK (Rövidtávú - az aktuális conv_id-hoz)
        note_context = ""
        if notes:
            note_context = "\n--- SAJÁT JEGYZETEID (EBBŐL A BESZÉLGETÉSBŐL) ---\n"
            for topic, content in notes:
                note_context += f"📌 {topic}: {content}\n"
            note_context += "--- JEGYZETEK VÉGE ---\n"

        # 2. HOSSZÚTÁVÚ MEMÓRIA (Minden beszélgetésnél látszik)
        memory_context = ""
        if memories:
            memory_context = "\n--- HOSSZÚTÁVÚ ISMERETEK RÓLAD ---\n"
            for subject, predicate, obj in memories:
                memory_context += f"💡 {subject} {predicate}: {obj}\n"
            memory_context += "--- MEMÓRIA VÉGE ---\n"

        # Szigorú instruálás
        instruction = "\nFONTOS: A SAJÁT JEGYZETEK és a HOSSZÚTÁVÚ ISMERETEK a legfrissebb tények. Használd őket elsődleges forrásként!"
        style = "\nKözlési stílus: Tömör, precíz, adatvezérelt. Kerüld a metaforákat."

        full_system_prompt = f"{base_identity}\n{memory_context}\n{note_context}\n{instruction}\n{style}"

        if module_result:
            full_system_prompt += f"\n--- KÜLSŐ KONTEXTUS (INTERNET) ---\n{module_result['context']}\n"

        return await self.provider.generate_response(
            user_message, 
            system_prompt=full_system_prompt, 
            temp=self.state_manager.get_temperature()
        )

    async def _self_reflection(self, user_msg: str, assistant_res: str, conv_id: str):
        """Kinyeri a tényeket a válaszból és menti a jegyzettömbbe."""
        try:
            model_name = self.state_manager.config["provider"]["model"]
            reflection_prompt = (
                "### TASK: EXTRACT TECHNICAL FACTS ONLY\n"
                "Extract parameters, names, times, and hard facts from the conversation.\n"
                "IGNORE metaphors, emotions, and filler.\n"
                "FORMAT: Topic: Value\n"
                "STRICT RULE: Only output the list. No intro."
            )
            context = f"User: {user_msg}\nAI: {assistant_res}"
            
            reflection = await self.router_provider.generate_response(context, system_prompt=reflection_prompt, temp=0.1)
            
            # Meglévő jegyzetek a duplikáció elkerüléséhez
            past_notes = self.db.get_notes_for_conversation(conv_id)
            existing_contents = [c.strip() for t, c in past_notes] if past_notes else []

            for line in reflection.split('\n'):
                if ":" in line and len(line) > 5:
                    clean_line = re.sub(r'^[* \-\d.]+', '', line)
                    parts = clean_line.split(":", 1)
                    
                    if len(parts) == 2:
                        topic_tag = parts[0].strip()[:50]
                        content = parts[1].strip()

                        if content not in existing_contents:
                            self.db.add_short_term_note(
                                conv_id=conv_id, 
                                model_origin=model_name, 
                                topic_tag=topic_tag, 
                                content=content
                            )
                            existing_contents.append(content) 
            
        except Exception as e:
            self.log.error(f"Reflexió hiba: {e}")

    def _simple_combine(self, results):
        ctx = ""
        for i, r in enumerate(results[:3]):
            ctx += f"[{r['title']}]: {r['content']}\n"
        return {"context": ctx, "source": "Web"}

    async def rerank_results(self, query: str, search_results: list):
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