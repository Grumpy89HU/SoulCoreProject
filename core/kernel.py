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
        # Fő modell (Az aktuális Király - pl. Gemma3:12B)
        self.model_name = cfg["provider"]["model"]
        self.provider = LLMProvider(cfg["provider"]["base_url"], self.model_name)
        
        # Kisegítő modell (Az Írnok / Router - pl. Gemma3:1B)
        router_model = cfg.get("router", {}).get("model", self.model_name)
        self.small_provider = LLMProvider(cfg["provider"]["base_url"], router_model)
        
        rerank_cfg = cfg.get("reranker", {})
        self.reranker = Reranker(rerank_cfg) if rerank_cfg.get("enabled") else None
        self.modules = load_modules()
        
        self.log.info(f"Kernel v2.2 (SoulCore) aktív. Király: {self.model_name}")

    async def should_trigger_search(self, user_message: str) -> bool:
        """Megtartott funkció: 1B Router döntési logika."""
        decision_prompt = (
            "Internal Reasoning Engine: Analyze the following query.\n"
            f"Query: \"{user_message}\"\n\n"
            "Task: Decide if external search is MANDATORY.\n"
            "Output ONLY '[SEARCH]' or '[INTERNAL]'."
        )
        try:
            decision = await self.small_provider.generate_response(
                decision_prompt, system_prompt="Search Decision Logic.", temp=0.1
            )
            return "[SEARCH]" in decision.upper()
        except Exception:
            self.log.warning("Router hiba, alapértelmezett: INTERNAL")
            return False

    async def process_message(self, user_message: str, conv_id: str = "default_session"):
        """A teljes üzenetkezelési folyamat, aszinkron optimalizálással."""
        start_time = time.time()
        module_result = None
        
        # --- 1. RENDSZERÁLLAPOT ÉS SZŰRÉS ---
        freedom_mode = self.db.get_setting("freedom_mode", "false").lower() == "true"
        msg_lower = user_message.lower().strip()
        
        # Meta-kérések (pl. címadás) kiszűrése a nehéz folyamatok alól
        is_meta = any(t in msg_lower for t in ["### task:", "follow-up", "generate title"])
        
        # --- 2. PÁRHUZAMOS ADATGYŰJTÉS (Keresés indítása + Memória lekérés egyszerre) ---
        # Amíg az Ollama dolgozik a router döntésén, addig a DB-ből már hozzuk az adatokat
        if freedom_mode:
            current_notes_task = asyncio.to_thread(self.db.get_notes_by_model, self.model_name, 5)
        else:
            current_notes_task = asyncio.to_thread(self.db.get_notes_for_conversation, conv_id)
        
        global_memories_task = asyncio.to_thread(self.db.get_long_term_memories)

        # Router hívása (csak ha nem meta kérés)
        needs_search = False
        if not is_meta and len(msg_lower.split()) >= 3:
            needs_search = await self.should_trigger_search(user_message)

        # Keresés végrehajtása, ha szükséges
        # --- 2. KERESÉS ---
        if needs_search:
            search_mod = self.modules.get("search")
            
            # Ellenőrizzük, hogy a szótárban benne van-e az 'execute' kulcs
            if search_mod and isinstance(search_mod, dict) and "execute" in search_mod:
                try:
                    self.log.info("Keresési folyamat indítása...")
                    # Szótár kulcsként hívjuk meg a függvényt
                    search_results = await search_mod["execute"](user_message, self.state_manager.config)
                    
                    if search_results:
                        if self.reranker:
                            module_result = await self.rerank_results(user_message, search_results)
                        else:
                            module_result = self._simple_combine(search_results)
                except Exception as e:
                    self.log.error(f"Hiba a keresőmodul futtatása közben: {e}")
                    module_result = None
            else:
                # Ha nem szótár vagy nincs execute kulcs, akkor fallback vagy hiba
                type_name = type(search_mod).__name__
                self.log.error(f"Kritikus: A 'search' modul nem hívható vagy hibás struktúra (Típus: {type_name}).")
                needs_search = False

        # Megvárjuk az adatbázis válaszait (amik a háttérben már megérkeztek)
        current_notes, global_memories = await asyncio.gather(current_notes_task, global_memories_task)

        # --- 3. GENERÁLÁS (A Király válaszol) ---
        raw_response = await self.generate_final_response(
            user_message, module_result, conv_id, 
            notes=current_notes, memories=global_memories
        )

        # --- 4. ASZINKRON UTÓMUNKA (Post-processing) ---
        # Az Írnok mentési folyamata nem blokkolja a választ!
        asyncio.create_task(self._async_post_process(raw_response, conv_id, is_meta))

        # Publikus válasz tisztítása a tagektől
        clean_response = re.sub(r'<(notepad|task|logic)>.*?(</\1>|$)', '', raw_response, flags=re.DOTALL | re.IGNORECASE).strip()

        self.log.info(f"Kész. Idő: {time.time() - start_time:.2f}s")
        return clean_response

    async def _async_post_process(self, raw_response, conv_id, is_meta):
        """Megtartott funkció: Blokk-alapú kinyerés és mentés."""
        block_pattern = r'<(notepad|task|logic)>(.*?)(?=<(notepad|task|logic)>|$)'
        internal_blocks = re.findall(block_pattern, raw_response, flags=re.DOTALL | re.IGNORECASE)
        
        extracted_data = {}
        for tag, content, _ in internal_blocks:
            clean_content = re.sub(r'</.*?>', '', content).strip()
            extracted_data[tag.lower()] = clean_content

        if "notepad" in extracted_data and not is_meta:
            try:
                # Modell-pecsétes mentés (self.model_name használatával)
                self.db.add_short_term_note(conv_id, self.model_name, "Self-Notepad", extracted_data["notepad"], importance=0.7)
                self.router_log.info(f"[{self.model_name}] Scribe: Jegyzet rögzítve.")
            except Exception as e:
                self.log.error(f"Scribe mentési hiba: {e}")

    async def generate_final_response(self, user_message: str, module_result: dict, conv_id: str, 
                                    notes=None, memories=None):
        """Megtartott funkció: StateManager prompt összeállítás + RAG Pre-processor."""
        cleaned_context = ""
        if module_result and module_result.get('context'):
            # Megtartott funkció: RAG Pre-processor hívása (1B modell)
            cleaned_context = await self.small_provider.generate_response(
                f"INPUT DATA:\n{module_result['context']}", 
                system_prompt=self.state_manager.get_rag_preprocessor_prompt(), 
                temp=0.1
            )

        # Megtartott funkció: StateManager központi prompt összeállítása
        full_system_prompt = self.state_manager.assemble_kope_system_prompt(
            model_name=self.model_name, 
            cleaned_context=cleaned_context
        )
        
        extras = []
        if memories: extras.append(f"Global Knowledge (Library): {memories}")
        if notes: 
            try:
                formatted_list = []
                # Kijavított ciklus a DB tuple struktúrához
                for n in notes[::-1]:
                    # n[1] a tartalom (content) a database.py lekérdezése alapján
                    val = n[1] if isinstance(n, (tuple, list)) and len(n) > 1 else str(n)
                    formatted_list.append(f"- {val}")
                extras.append(f"Your Previous Internal Thoughts ({self.model_name}):\n" + "\n".join(formatted_list))
            except Exception as e:
                self.log.error(f"Memory formatting error: {e}")
        
        if extras:
            full_system_prompt += "\n\n### SOULCORE INTERNAL ACCESS:\n" + "\n".join(extras)

        # Kötelező instrukciók a kimenethez
        full_system_prompt += (
            "\n\nAdd a <notepad> section in ENGLISH at the end. "
            "Record your private reflections and state of the task. "
            "Respond in HUNGARIAN."
        )

        return await self.provider.generate_response(
            user_message, system_prompt=full_system_prompt, temp=0.8
        )

    def _simple_combine(self, results):
        """Fallback, ha nincs Reranker."""
        ctx = ""
        for r in results[:3]:
            ctx += f"[{r.get('title', 'Web')}]: {r.get('content', '')}\n"
        return {"context": ctx}

    async def rerank_results(self, query: str, search_results: list):
        """Megtartott funkció: Reranker alapú szűrés."""
        rag_cfg = self.state_manager.config.get("rag", {})
        passed = [f"Source: {res.get('title')}\n{res.get('content')}" 
                  for res in search_results 
                  if self.reranker.get_local_score(query, f"{res.get('title')} {res.get('content')}") >= rag_cfg.get("threshold", 0.15)]
        return {"context": "\n\n".join(passed)} if passed else None