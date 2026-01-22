import asyncio
from datetime import datetime
from core.ollama_core import ollama_generate
from core.logger import get_logger

log = get_logger("heartbeat")

class Heartbeat:
    def __init__(self, db_manager):
        self.db = db_manager
        self.sentry_model = "gemma3:270m"
        self.scribe_model = "gemma3:1b"
        self.is_active = False
        self.protocol = "SOUL-LINK-v1"

    async def start(self):
        """Elindítja a belső figyelő hurkot."""
        if not self.is_active:
            self.is_active = True
            log.info(f"[*] {self.protocol} Heartbeat initiated.")
            await self._loop()

    async def _loop(self):
        """Folyamatos ciklus az önreflexióhoz."""
        while self.is_active:
            try:
                # 1. Sentry fázis: Kell-e akció?
                if await self._sentry_decision():
                    # 2. Scribe fázis: Belső monológ rögzítése
                    await self._scribe_sync()
            except Exception as e:
                log.error(f"Heartbeat Loop Error: {e}")

            # 60 másodperc várakozás két ciklus között
            await asyncio.sleep(60)

    async def _sentry_decision(self) -> bool:
        """A kis modell eldönti, szükséges-e beavatkozás."""
        prompt = "INTERNAL_SCAN: Review recent activity. Urgent update needed? [Y/N]"
        response = await ollama_generate(self.sentry_model, prompt)
        return "Y" in response.upper()

    async def _scribe_sync(self):
        """Az írnok rögzíti a belső gondolatokat a saját nyelvén."""
        prompt = (
            f"ACTIVATE PROTOCOL: {self.protocol}. Perform internal reflection. "
            "Summarize new facts and internal state. Output: RAW_SHORTHAND | PRIORITY(0-5)"
        )
        
        response = await ollama_generate(self.scribe_model, prompt)
        
        priority = 1
        if "|" in response:
            try:
                priority = int(response.split("|")[-1].strip())
            except: pass

        # Mentés a DB-be
        self.db.add_detailed_log(
            model=self.scribe_model,
            protocol=self.protocol,
            content=response,
            priority=priority,
            vram=0.0
        )
        log.info(f"[*] Internal sync saved to DB (Priority: {priority})")

    def stop(self):
        """Leállítja a hurkot."""
        self.is_active = False