import logging
import time
import asyncio
import os
import re
import json
import contextlib
import psutil
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from src.database import SoulCoreDatabase
from src.prompts import staff_prompts
from src.utils.monitor import SoulCoreMonitor # Bekötjük a valódi monitort

class Orchestrator:
    def __init__(self, db_path="vault/db/soulcore.db"):
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger("Kernel.Orchestrator")
        self.db = SoulCoreDatabase(db_path=db_path)
        
        # Monitor inicializálása a pontos telemetriához
        self.monitor = SoulCoreMonitor()
        self.start_time = self.monitor.start_time
        
        # Identitás betöltése az adatbázisból
        self.sovereign_info = self.db.get_sovereign_identity()
        self.identity = self.sovereign_info["name"]
        
        project_cfg = self.db.get_config("project") or {}
        self.user_lang = project_cfg.get('user_lang', 'hu')
        self.internal_lang = project_cfg.get('internal_lang', 'en')
        
        self.slots = {}
        self.executor = ThreadPoolExecutor(max_workers=4)

    def boot_slots(self):
        """Slotok dinamikus betöltése az adatbázis alapján."""
        from src.slots.specialized_slots import Scribe, Valet, Sovereign
        from src.loaders.gguf_loader import GGUFSlot
        
        active_slots = self.db.get_enabled_slots()
        
        slot_class_map = {
            "scribe": Scribe,
            "valet": Valet,
            "king": Sovereign
        }

        for name, cfg in active_slots.items():
            cls = slot_class_map.get(name, GGUFSlot)
            instance = cls(name, cfg)
            self.slots[name] = instance
            try:
                # Elnémítjuk a felesleges C++ logokat a betöltéskor
                with open(os.devnull, "w") as fnull:
                    with contextlib.redirect_stderr(fnull):
                        instance.load()
                self.logger.info(f"✅ Slot aktív: {name} (Class: {cls.__name__})")
            except Exception as e:
                self.logger.error(f"❌ Hiba a {name} betöltésekor: {e}")

    def get_hardware_stats(self):
        """
        Bővített telemetria: Most már a GPU adatokat is tartalmazza 
        a korábbi csak CPU/RAM helyett.
        """
        hw_data = self.monitor.get_hardware_stats()
        return {
            "hardware": hw_data,
            "uptime": round(time.time() - self.start_time, 2),
            "slots": {name: slot.status() for name, slot in self.slots.items()}
        }

    async def _run_in_thread(self, slot_name, method_name, *args, **kwargs):
        """Biztonságos futtatás külön szálon a blokkolás elkerülésére."""
        if slot_name not in self.slots or not self.slots[slot_name].is_loaded:
            self.logger.warning(f"Slot {slot_name} nem elérhető!")
            return None
        
        slot_instance = self.slots[slot_name]
        method = getattr(slot_instance, method_name)
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, lambda: method(*args, **kwargs))

    async def _translate(self, text, to_lang="en"):
        if "translator" not in self.slots or not text: return text
        
        prompt = (f"<|start_header_id|>system<|end_header_id|>\n\nTranslate to {to_lang}. "
                  f"Provide ONLY the translated text, no chatter.<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n{text}<|eot_id|>"
                  f"<|start_header_id|>assistant<|end_header_id|>\n\n")
        
        res = await self._run_in_thread("translator", "generate", prompt, {"max_tokens": 512, "temperature": 0.1})
        return res.strip() if res else text

    def _parse_tags(self, text):
        """Kinyeri a tag-eket a Sovereign válaszából."""
        tags = ["note", "message", "translate"]
        extracted_map = {tag: None for tag in tags}
        
        if not text:
            return {**extracted_map, "clean_text": ""}

        for tag in tags:
            pattern = rf"<{tag}>(.*?)(?:</{tag}>|$)"
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                extracted_map[tag] = match.group(1).strip()
        
        # Tiszta szöveg kinyerése
        if extracted_map["message"]:
            extracted_map["clean_text"] = extracted_map["message"]
        elif extracted_map["translate"]:
            extracted_map["clean_text"] = extracted_map["translate"]
        else:
            temp = re.sub(r'<[^>]+>.*?</[^>]+>', '', text, flags=re.DOTALL)
            extracted_map["clean_text"] = re.sub(r'<[^>]+>', '', temp).strip()
            
        return extracted_map

    async def process_pipeline(self, user_query, chat_id="default_chat", user_id="Grumpy"):
        start_process = time.time()
        self.logger.info(f"--- Pipeline Start: {user_query[:50]}... ---")
        
        # Üzenet mentése a DB-be
        self.db.save_message(chat_id, "user", user_query)
        
        # 1. SCRIBE - Elemzés
        scribe_info = {}
        if "scribe" in self.slots:
            scribe_info = await self._run_in_thread("scribe", "analyze", user_query)
        self.logger.info(f"Scribe Info: {scribe_info}")

        # 2. VALET - RAG és Helyzetjelentés
        keywords = scribe_info.get("keywords", user_query) if isinstance(scribe_info, dict) else user_query
        vault_data = self.db.query_vault(keywords, user_id=user_id)
        
        situational_report = ""
        if "valet" in self.slots:
            situational_report = await self._run_in_thread(
                "valet", "run_report", 
                vault_data=vault_data, 
                scribe_info=scribe_info, 
                raw_input=user_query
            )
        self.logger.info(f"Valet Report Kész.")

        # 3. ELŐKÉSZÍTÉS A KIRÁLYNAK (Belső nyelv használata)
        english_query = await self._translate(user_query, to_lang=self.internal_lang)
        
        # 4. KING - Szuverén döntéshozatal
        raw_king_response = ""
        if "king" in self.slots:
            raw_king_response = await self._run_in_thread(
                "king", "run_final",
                report=situational_report,
                user_input=english_query,
                identity_data=self.sovereign_info
            )
        
        # Tag parszolás
        parsed_king = self._parse_tags(raw_king_response)
        self.logger.info(f"King Note: {parsed_king.get('note', 'Nincs megjegyzés')}")

        # 5. SCRIBE - Mentés (Trigger alapú memória)
        if parsed_king.get("note") and "trigger_scribe" in parsed_king["note"].lower():
            self.logger.info("🎯 Scribe Trigger aktív - Mentés folyamatban...")
            # Biztonságosabb szintézis futtatás
            scribe_data = await self._run_in_thread("scribe", "run_synthesis", english_query, situational_report)
            if isinstance(scribe_data, dict) and "new_facts" in scribe_data:
                for fact in scribe_data.get("new_facts", []):
                    self.db.save_to_long_memory(fact, metadata="auto-extracted")

        # 6. VÉGSŐ VÁLASZ
        if parsed_king.get("translate"):
            final_response = await self._translate(parsed_king["translate"], to_lang=self.user_lang)
        else:
            final_response = parsed_king.get("clean_text") or "..."

        # Mentés és Debug adatok eltárolása
        self.db.save_message(chat_id, "assistant", final_response, 
                               debug={"note": parsed_king.get("note"), "report": situational_report})
        
        self.logger.info(f"--- Pipeline End ({round(time.time() - start_process, 2)}s) ---")

        return {
            "identity": self.identity,
            "response": final_response,
            "chat_id": chat_id,
            "metadata": {"time": round(time.time() - start_process, 3)}
        }

    def shutdown(self):
        self.logger.info("SoulCore rendszerek leállítása...")
        # Leállás előtt egy utolsó hardver státusz logolás (elhagyható, ha zavar)
        self.monitor.log_event("Orchestrator", "Rendszer leállítása kezdeményezve.")
        for slot in self.slots.values():
            if hasattr(slot, 'unload'): slot.unload()
        self.db.close()
        self.executor.shutdown(wait=False)