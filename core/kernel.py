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
        # Fő modell (Kópé - 12B)
        self.provider = LLMProvider(cfg["provider"]["base_url"], cfg["provider"]["model"])
        
        # Kisegítő modell (RAG Cleaner / Router / Írnok - 1B)
        router_model = cfg.get("router", {}).get("model", cfg["provider"]["model"])
        self.small_provider = LLMProvider(cfg["provider"]["base_url"], router_model)
        
        rerank_cfg = cfg.get("reranker", {})
        self.reranker = Reranker(rerank_cfg) if rerank_cfg.get("enabled") else None
        self.modules = load_modules()
        self.log.info("Kernel v1.5.5 (SoulCore: Search Gatekeeper & Character Shield) aktív.")

    async def should_trigger_search(self, user_message: str) -> bool:
        """
        Belső döntéshozatali logika: megvizsgálja, hogy a lekérdezés megválaszolható-e 
        belső tudás (adminisztratív rövidítések) alapján, vagy szükséges-e a web.
        """
        decision_prompt = (
            "Internal Reasoning Engine: Analyze the following Hungarian query.\n"
            f"Query: \"{user_message}\"\n\n"
            "Task: Decide if external search is MANDATORY.\n"
            "- If it contains administrative shortcuts like 'an:', 'szül:', 'hrsz:', 'cgj:', 'lh:', the answer is INTERNAL (No search).\n"
            "- If it is a greeting or identity question, the answer is INTERNAL.\n"
            "- If it requires real-time facts (weather, current news, stock prices), the answer is SEARCH.\n"
            "Output ONLY '[SEARCH]' or '[INTERNAL]'."
        )
        
        try:
            decision = await self.small_provider.generate_response(
                decision_prompt, 
                system_prompt="You are a Search Decision Logic unit.", 
                temp=0.1
            )
            return "[SEARCH]" in decision.upper()
        except Exception as e:
            self.log.error(f"Search Decision hiba: {e}")
            return True # Hiba esetén inkább keressünk, hogy ne legyen infóhiány

    async def process_message(self, user_message: str, conv_id: str = "default_session"):
        start_time = time.time()
        module_result = None
        
        # --- 1. RADIKÁLIS SZŰRÉS (Hard-coded & AI-döntés) ---
        msg_lower = user_message.lower().strip()
        
        identity_terms = ["ki vagy", "mi a neved", "hogy hívnak", "neved", "ki beszél", "szia", "helló", "hogy vagy"]
        meta_terms = ["### task:", "follow-up", "generate", "címjavaslat", "suggest"]
        
        is_identity = any(t in msg_lower for t in identity_terms)
        is_meta = any(t in msg_lower for t in meta_terms)
        is_too_short = len(msg_lower.split()) < 3
        
        needs_search = False
        
        # Ha nem egyértelműen meta/identitás, megkérdezzük a logikai egységet
        if not is_identity and not is_meta and not is_too_short:
            needs_search = await self.should_trigger_search(user_message)

        # --- 2. KERESÉS VÉGREHAJTÁSA ---
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
        else:
            self.log.info("Keresés átugorva: Belső tudás vagy identitás-ág.")

        # --- 3. KONTEXTUS ÉS BELSŐ ADATOK ---
        current_notes = self.db.get_notes_for_conversation(conv_id)
        global_memories = self.db.get_long_term_memories()
        
        heartbeat_query = "SELECT raw_content FROM internal_thought_logs WHERE priority_level >= 1 ORDER BY id DESC LIMIT 3"
        raw_thoughts = self.db._execute(heartbeat_query, fetch_all=True)
        internal_thoughts = [t[0] for t in raw_thoughts] if raw_thoughts else []
        
        # --- 4. GENERÁLÁS ---
        response = await self.generate_final_response(
            user_message, 
            module_result, 
            conv_id, 
            notes=current_notes, 
            memories=global_memories, 
            internal_thoughts=internal_thoughts
        )

        # --- 5. AUDIT ---
        if not is_meta:
            asyncio.create_task(self._scribe_audit(user_message, response, conv_id))

        self.log.info(f"Kész. Keresés: {needs_search} | Identitás-ág: {is_identity} | Idő: {time.time() - start_time:.2f}s")
        return response

    async def generate_final_response(self, user_message: str, module_result: dict, conv_id: str, 
                                    notes=None, memories=None, internal_thoughts=None):
        
        cleaned_context = ""
        # RAG Tisztítás
        if module_result and module_result.get('context'):
            try:
                cleaner_prompt = self.state_manager.get_rag_preprocessor_prompt()
                cleaned_context = await self.small_provider.generate_response(
                    f"INPUT DATA:\n{module_result['context']}", 
                    system_prompt=cleaner_prompt, 
                    temp=0.1
                )
            except Exception as e:
                self.log.error(f"Cleaner hiba: {e}")
                cleaned_context = module_result['context']

        model_name = self.state_manager.config["provider"]["model"]
        full_system_prompt = self.state_manager.assemble_kope_system_prompt(
            model_name=model_name, 
            cleaned_context=cleaned_context
        )
        
        extras = []
        if memories: extras.append(f"Hosszútávú emlékek: {memories}")
        if notes: extras.append(f"Beszélgetési jegyzetek: {notes}")
        if internal_thoughts: extras.append(f"Rendszer reflexiók: {internal_thoughts}")
        
        if extras:
            full_system_prompt += "\n\n### RELEVÁNS BELSŐ INFORMÁCIÓK (Csak ha szükséges):\n" + "\n".join(extras)

        return await self.provider.generate_response(
            user_message, 
            system_prompt=full_system_prompt, 
            temp=0.85
        )

    async def _scribe_audit(self, user_msg: str, assistant_res: str, conv_id: str):
        try:
            scribe_prompt = self.state_manager.get_scribe_prompt()
            context = f"User: {user_msg}\nAssistant: {assistant_res}"
            audit_json = await self.small_provider.generate_response(context, system_prompt=scribe_prompt, temp=0.1)
            self.router_log.info(f"Scribe Audit: {audit_json}")
            
            reflection_prompt = "### TASK: EXTRACT TECHNICAL FACTS\nFORMAT: Topic: Value"
            reflection = await self.small_provider.generate_response(context, system_prompt=reflection_prompt, temp=0.1)
            
            model_name = self.state_manager.config["provider"]["model"]
            for line in reflection.split('\n'):
                if ":" in line:
                    parts = line.split(":", 1)
                    self.db.add_short_term_note(conv_id, model_name, parts[0].strip()[:50], parts[1].strip())
        except Exception as e:
            self.log.error(f"Audit hiba: {e}")

    def _simple_combine(self, results):
        ctx = ""
        for r in results[:3]:
            ctx += f"[{r.get('title', 'Web')}]: {r.get('content', '')}\n"
        return {"context": ctx}

    async def rerank_results(self, query: str, search_results: list):
        rag_cfg = self.state_manager.config.get("rag", {})
        threshold = rag_cfg.get("threshold", 0.15)
        passed = [f"Source: {res.get('title')}\n{res.get('content')}" 
                  for res in search_results 
                  if self.reranker.get_local_score(query, f"{res.get('title')} {res.get('content')}") >= threshold]
        return {"context": "\n\n".join(passed)} if passed else None