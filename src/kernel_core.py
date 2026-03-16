import asyncio
import json
import time
import logging
from typing import Dict, Any, AsyncGenerator
from src.orchestrator import Orchestrator
from src.utils.monitor import SoulCoreMonitor  # Új import a telemetriához

class SoulCoreKernel:
    def __init__(self, mode="production", db_path="vault/db/soulcore.db"):
        self.mode = mode  # "test" vagy "production"
        
        # Monitor inicializálása - Ez kezeli a GPU/CPU statokat és a logolást
        self.monitor = SoulCoreMonitor()
        # Az indítási időt a monitortól vesszük át a szinkronitás miatt
        self.start_time = self.monitor.start_time
        
        self.logger = logging.getLogger("KernelCore")
        
        # Ha production, inicializáljuk a valódi motort
        if self.mode == "production":
            self.orchestrator = Orchestrator(db_path=db_path)
            self.orchestrator.boot_slots()
        else:
            self.orchestrator = None
            
        # A monitoron keresztül is logoljuk az indulást
        self.monitor.log_event("Kernel", f"SoulCore Kernel Online (Mode: {self.mode})")

    def get_hardware_stats(self):
        """A Webserver ezen keresztül kéri le a telemetriát az index.html számára."""
        return self.monitor.get_hardware_stats()

    @property
    def uptime_raw(self):
        """Visszaadja a nyers uptime másodperceket."""
        return time.time() - self.start_time
    
    async def dispatch_scribe(self, user_input: str) -> Dict[str, Any]:
        """A Scribe elemzi a szándékot az Orchestratoron keresztül."""
        print("✍️  Scribe is analyzing intent...")
        if self.mode == "test":
            await asyncio.sleep(0.5)
            return {"intent": "chat", "language": "hu", "urgency": 1, "keywords": "Vár építés"}
        
        # Valódi hívás az Orchestrator szálkezelőjén keresztül
        return await self.orchestrator._run_in_thread("scribe", "analyze", user_input)

    async def dispatch_valet(self, intent_data: Dict) -> Dict[str, Any]:
        """A Valet előkészíti a Vault adatokat."""
        print("🧹 Valet is fetching records from Vault...")
        if self.mode == "test":
            await asyncio.sleep(0.8)
            return {"report": "A rendszerek stabilak. Grumpy a tápegységre vár."}
        
        # Az Orchestrator logikáját követve itt a Vault-ból húzunk adatot
        keywords = intent_data.get("keywords", "")
        # Ellenőrizzük, hogy a db elérhető-e
        if self.orchestrator and hasattr(self.orchestrator, 'db'):
            vault_data = self.orchestrator.db.query_vault(keywords)
        else:
            vault_data = "Vault nem érhető el."
        return {"report": vault_data}

    async def dispatch_king(self, user_input: str, chat_id="default"):
        """A Király generálása. (Streaming-ready interfész)"""
        print(f"👑 King is thinking (Mode: {self.mode})...")
        
        if self.mode == "test":
            sample_response = "A szuverenitás nem cél, hanem állapot. A tápegység megérkezése után a Vár kapui kitárulnak."
            for word in sample_response.split():
                yield word + " "
                await asyncio.sleep(0.1)
        else:
            # Valódi pipeline futtatás az Orchestratoron keresztül
            result = await self.orchestrator.process_pipeline(user_input, chat_id=chat_id)
            full_response = result.get("response", "...")
            for word in full_response.split():
                yield word + " "
                await asyncio.sleep(0.02) # Minimális késleltetés a stream élményhez

    async def main_pipeline(self, user_input: str, chat_id="default"):
        """A teljes kognitív lánc futtatása a konzolon."""
        print(f"\n--- SoulCore Pipeline Start ---")
        
        # 1-2. Scribe és Valet folyamat (Az orchestratoron belül futnak alapból)
        async for chunk in self.dispatch_king(user_input, chat_id=chat_id):
            print(chunk, end="", flush=True)
            
        print(f"\n--- End (Uptime: {round(self.uptime_raw, 2)}s) ---")

# Futtatás teszteléshez
if __name__ == "__main__":
    kernel = SoulCoreKernel(mode="test")
    asyncio.run(kernel.main_pipeline("Mikor lesz kész a Vár?"))