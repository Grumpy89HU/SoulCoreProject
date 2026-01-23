import asyncio
import time
import re
from core.provider import LLMProvider
from core.state_manager import StateManager
from core.reranker import Reranker
from core.logger import get_logger
from core.database import DBManager
from modules import load_modules
from datetime import datetime, timedelta

class Kernel:
    def __init__(self, config_dir: str):
        self.log = get_logger("kernel")
        self.router_log = get_logger("router")
        self.state_manager = StateManager(config_dir)
        self.db = DBManager()
        
        cfg = self.state_manager.config
        self.model_name = cfg["provider"]["model"]
        self.provider = LLMProvider(cfg["provider"]["base_url"], self.model_name)
        
        router_model = cfg.get("router", {}).get("model", self.model_name)
        self.small_provider = LLMProvider(cfg["provider"]["base_url"], router_model)
        
        rerank_cfg = cfg.get("reranker", {})
        self.reranker = Reranker(rerank_cfg) if rerank_cfg.get("enabled") else None
        self.modules = load_modules()
        
        self.log.info(f"Kernel v2.2 (SoulCore) aktív. Király: {self.model_name}")

    async def should_trigger_search(self, user_message: str) -> bool:
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
        self.log.info(f"--- BEÉRKEZŐ ADATOK ---")
        self.log.info(f"User Message: {user_message[:50]}...")
        self.log.info(f"Received conv_id: {conv_id}")
        
        start_time = time.time()
        module_result = None
        
        freedom_mode = self.db.get_setting("freedom_mode", "false").lower() == "true"
        msg_lower = user_message.lower().strip()
        is_meta = any(t in msg_lower for t in ["### task:", "follow-up", "generate title"])
        
        if freedom_mode:
            current_notes_task = asyncio.to_thread(self.db.get_notes_by_model, self.model_name, 5)
        else:
            current_notes_task = asyncio.to_thread(self.db.get_notes_for_conversation, conv_id)
        
        global_memories_task = asyncio.to_thread(self.db.get_long_term_memories)

        needs_search = False
        if not is_meta and len(msg_lower.split()) >= 3:
            needs_search = await self.should_trigger_search(user_message)

        if needs_search:
            search_mod = self.modules.get("search")
            if search_mod and isinstance(search_mod, dict) and "execute" in search_mod:
                try:
                    self.log.info("Keresési folyamat indítása...")
                    search_results = await search_mod["execute"](user_message, self.state_manager.config)
                    if search_results:
                        if self.reranker:
                            module_result = await self.rerank_results(user_message, search_results)
                        else:
                            module_result = self._simple_combine(search_results)
                except Exception as e:
                    self.log.error(f"Hiba a keresőmodul futtatása közben: {e}")
                    module_result = None

        current_notes, global_memories = await asyncio.gather(current_notes_task, global_memories_task)

        raw_response = await self.generate_final_response(
            user_message, module_result, conv_id, 
            notes=current_notes, memories=global_memories
        )

        # Post-processing: Notepad mentés és Task szűrés
        asyncio.create_task(self._async_post_process(raw_response, conv_id, is_meta))

        clean_response = re.sub(r'<(notepad|task|logic)>.*?(</\1>|$)', '', raw_response, flags=re.DOTALL | re.IGNORECASE).strip()

        self.log.info(f"Kész. Idő: {time.time() - start_time:.2f}s")
        return clean_response

    async def _async_post_process(self, raw_response, conv_id, is_meta):
        block_pattern = r'<(notepad|task|logic)>(.*?)(?=<(notepad|task|logic)>|$)'
        internal_blocks = re.findall(block_pattern, raw_response, flags=re.DOTALL | re.IGNORECASE)
        
        extracted_data = {}
        for tag, content, _ in internal_blocks:
            clean_content = re.sub(r'</.*?>', '', content).strip()
            extracted_data[tag.lower()] = clean_content

        # 1. Notepad mentése
        if "notepad" in extracted_data and not is_meta:
            try:
                self.db.add_short_term_note(conv_id, self.model_name, "Self-Notepad", extracted_data["notepad"], importance=0.7)
                self.router_log.info(f"[{self.model_name}] Scribe: Jegyzet rögzítve.")
            except Exception as e:
                self.log.error(f"Scribe mentési hiba: {e}")

        # 2. Feladat (Task) szűrése és mentése
        if "task" in extracted_data:
            task_raw = extracted_data["task"]
            # LUSTASÁG ELLENI SZŰRŐ: Ha sablonszöveg maradt benne
            if "Description" in task_raw or len(task_raw) < 10:
                self.router_log.warning(f"[*] Task eldobva: Kópé lusta volt (ID: {conv_id})")
                return

            try:
                parts = [p.strip() for p in task_raw.split("|")]
                description = parts[0] if len(parts) > 0 else "Névtelen feladat"
                
                try:
                    priority = int(parts[1]) if len(parts) > 1 else 1
                except:
                    priority = 1
                
                scheduled_for = parts[2] if len(parts) > 2 else (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

                query = """
                    INSERT INTO task_scheduler (chat_id, task_description, priority, status, scheduled_for)
                    VALUES (?, ?, ?, 'pending', ?)
                """
                self.db._execute(query, (conv_id, description, priority, scheduled_for), commit=True)
                self.router_log.info(f"[*] FELADAT RÖGZÍTVE: {description} (Prio: {priority})")
            except Exception as e:
                self.log.error(f"Task ütemezési hiba: {e}")

    async def generate_final_response(self, user_message: str, module_result: dict, conv_id: str, 
                                    notes=None, memories=None):
        cleaned_context = ""
        if module_result and module_result.get('context'):
            cleaned_context = await self.small_provider.generate_response(
                f"INPUT DATA:\n{module_result['context']}", 
                system_prompt=self.state_manager.get_rag_preprocessor_prompt(), 
                temp=0.1
            )

        full_system_prompt = self.state_manager.assemble_kope_system_prompt(
            model_name=self.model_name, 
            cleaned_context=cleaned_context
        )
        
        extras = []
        if memories: extras.append(f"Global Knowledge (Library): {memories}")
        if notes: 
            try:
                formatted_list = []
                for n in notes[::-1]:
                    val = n[1] if isinstance(n, (tuple, list)) and len(n) > 1 else str(n)
                    formatted_list.append(f"- {val}")
                extras.append(f"Your Previous Internal Thoughts ({self.model_name}):\n" + "\n".join(formatted_list))
            except Exception as e:
                self.log.error(f"Memory formatting error: {e}")
        
        if extras:
            full_system_prompt += "\n\n### SOULCORE INTERNAL ACCESS (Session: " + conv_id + "):\n" + "\n".join(extras)

        # Szigorúbb instrukciók Kópénak
        full_system_prompt += (
            "\n\n### OUTPUT FORMAT RULES:\n"
            "1. Respond in HUNGARIAN.\n"
            "2. Add a <notepad> section in ENGLISH at the end for reflections.\n"
            "3. IF a task is needed: Add a <task> block. NEVER use the word 'Description'. "
            "SUMMARIZE the actual task. Format: <task>Task summary | Priority(1-5) | YYYY-MM-DD HH:MM</task>"
        )

        return await self.provider.generate_response(
            user_message, system_prompt=full_system_prompt, temp=0.8
        )

    def _simple_combine(self, results):
        ctx = ""
        for r in results[:3]:
            ctx += f"[{r.get('title', 'Web')}]: {r.get('content', '')}\n"
        return {"context": ctx}

    async def rerank_results(self, query: str, search_results: list):
        rag_cfg = self.state_manager.config.get("rag", {})
        passed = [f"Source: {res.get('title')}\n{res.get('content')}" 
                  for res in search_results 
                  if self.reranker.get_local_score(query, f"{res.get('title')} {res.get('content')}") >= rag_cfg.get("threshold", 0.15)]
        return {"context": "\n\n".join(passed)} if passed else None