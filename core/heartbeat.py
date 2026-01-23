import time
import asyncio
import sqlite3
import os
from datetime import datetime
from core.ollama_core import ollama_generate
from core.logger import get_logger

log = get_logger("heartbeat")

class Heartbeat:
    def __init__(self, db_manager, kernel=None):
        self.db = db_manager
        self.kernel = kernel
        self.sentry_model = "gemma3:270m"
        self.scribe_model = "gemma3:1b"
        self.king_model = "gemma3:12B"
        self.is_active = False
        self.protocol = "SOUL-LINK-v1"
        self.webui_db_path = "/var/lib/docker/volumes/open-webui/_data/webui.db" 

    async def start(self):
        if not self.is_active:
            self.is_active = True
            log.info(f"[*] {self.protocol} Heartbeat initiated.")
            await self._loop()

    async def _loop(self):
        log.info(f"[*] {self.protocol} Ciklus elindítva (10s polling).")
        counter = 0
        while self.is_active:
            try:
                # 1. Feladatok ellenőrzése - MINDEN körben lefut (10s)
                await self._process_scheduled_tasks()
                
                # 2. Önreflexió - Csak minden 30. ciklusban (~5 perc)
                counter += 1
                if counter >= 30:
                    # Háttérben indítjuk, hogy ne blokkolja a fő ciklust
                    asyncio.create_task(self._run_reflection())
                    counter = 0
                    
            except Exception as e:
                log.error(f"Heartbeat Loop Error: {e}")
            
            await asyncio.sleep(10)

    async def _run_reflection(self):
        """Önálló folyamat az önreflexióhoz."""
        try:
            if await self._sentry_decision():
                await self._scribe_sync()
        except Exception as e:
            log.error(f"Reflection Error: {e}")

    async def _process_scheduled_tasks(self):
        task = self.db.get_next_pending_task() 
        if not task:
            return

        task_id, chat_id, description, priority = task
        log.info(f"[*] ÉBRESZTŐ! Feladat észlelve: {description} (Chat: {chat_id})")
        
        self.db.update_task_status(task_id, "running")

        try:
            prompt = (
                f"SYSTEM ALERT: Scheduled task execution for Chat: {chat_id}.\n"
                f"TASK TO PERFORM: {description}.\n"
                "You MUST respond to the user now. Be concise and relevant. "
                "Start your message with [NOTIFY_USER]."
            )
            
            target = self.king_model if priority >= 3 else self.scribe_model
            response = await ollama_generate(target, prompt)

            if "[NOTIFY_USER]" in response:
                clean_msg = response.replace("[NOTIFY_USER]", "").strip()
                await self.send_proactive_message(chat_id, clean_msg)
            else:
                await self.send_proactive_message(chat_id, response.strip())

            self.db.add_detailed_log(target, "TASK-EXEC", response, priority, vram=0.0)
            self.db.update_task_status(task_id, "completed")
            log.info(f"[*] Feladat (ID: {task_id}) elvégezve.")
            
        except Exception as e:
            log.error(f"Hiba a feladat végrehajtása közben (ID: {task_id}): {e}")
            self.db.update_task_status(task_id, "failed")

    async def send_proactive_message(self, chat_id, content):
        import json
        import uuid
        import time

        # --- ID TRANSZFORMÁCIÓ ---
        # Ha 'soul-' kezdetű, akkor megkeressük a valódi UUID-t
        real_id = chat_id
        if chat_id.startswith("soul-"):
            # Példa: beégetjük a teszteléshez a legfontosabb csatornát
            if "b3d84c40ec63" in chat_id:
                real_id = "78bb800a-ea2c-4860-84ca-b4bfcc8636a3" # 'Kópé ad feladatot' UUID-ja
            elif "f59bbf65d755" in chat_id:
                real_id = "a5566f4f-b511-4502-8e87-6a9258eb69d6" # 'Kópé emlékei' UUID-ja
        
        log.info(f"[*] Mapping ID: {chat_id} -> {real_id}")

        try:
            conn = sqlite3.connect(self.webui_db_path)
            cursor = conn.cursor()
            
            # Keressük a valódi chatet
            cursor.execute("SELECT chat, user_id FROM chat WHERE id = ?", (real_id,))
            row = cursor.fetchone()
            
            if not row:
                log.error(f"[-] MÉG MINDIG NEM TALÁLHATÓ: {real_id}")
                return

            chat_data = json.loads(row[0]) if row[0] else {"messages": []}
            u_id = row[1]
            now_ts = int(time.time())

            # Üzenet összeállítása
            new_msg = {
                "id": str(uuid.uuid4()),
                "role": "assistant",
                "content": content,
                "timestamp": now_ts,
                "model": self.king_model
            }

            if "messages" not in chat_data: chat_data["messages"] = []
            chat_data["messages"].append(new_msg)

            # Mentés mindkét helyre
            cursor.execute("UPDATE chat SET chat = ?, updated_at = ? WHERE id = ?", 
                         (json.dumps(chat_data), now_ts, real_id))
            
            cursor.execute("""
                INSERT INTO message (id, user_id, channel_id, content, data, created_at, updated_at) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (new_msg["id"], u_id, real_id, content, json.dumps({"role": "assistant"}), now_ts*1000, now_ts*1000))
            
            conn.commit()
            conn.close()
            log.info(f"[*] SIKER! Kópé beszélt a(z) '{real_id}' chatben.")
            
        except Exception as e:
            log.error(f"Mapping/Injection Error: {e}")

    async def _sentry_decision(self) -> bool:
        # Az időalapú szűrést kivettem, a counter már kezeli
        prompt = "INTERNAL_SCAN: Urgent update needed? [Y/N]"
        response = await ollama_generate(self.sentry_model, prompt)
        return "Y" in response.upper()

    async def _scribe_sync(self):
        prompt = (f"ACTIVATE PROTOCOL: {self.protocol}. Reflection. State? "
                  "Output: RAW_SHORTHAND | PRIORITY(0-5)")
        response = await ollama_generate(self.scribe_model, prompt)
        
        priority = 1
        if "|" in response:
            try: priority = int(response.split("|")[-1].strip())
            except: pass

        self.db.add_detailed_log(
            model=self.scribe_model, 
            protocol=self.protocol, 
            content=response, 
            priority=priority,
            vram=0.0
        )
        log.info(f"[*] Internal sync saved to DB (Priority: {priority})")

    def stop(self):
        self.is_active = False