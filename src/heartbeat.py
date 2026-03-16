import asyncio
import logging
import os
import sys
import time
from datetime import datetime
from typing import Dict

class Heartbeat:
    def __init__(self, orchestrator):
        self.core = orchestrator
        self.logger = logging.getLogger("SoulCore.Heartbeat")
        self.is_active = False
        
        # Időzítések és határértékek
        self.polling_interval = 15     # 15 másodpercenkénti ellenőrzés
        self.reflection_counter = 0
        self.reflection_limit = 20      # ~5 percenként kognitív reflexió
        self.error_threshold = 3        # Ennyi hiba után jön a hard-reset
        self.consecutive_errors = 0
        
        # Hardver küszöbök
        self.vram_warning_pct = 88.0    
        self.vram_critical_pct = 94.0   
        self.ram_threshold_pct = 95.0   

    async def start(self):
        if not self.is_active:
            self.is_active = True
            self.logger.info("💓 SoulCore Heartbeat (Kognitív Őrszem) élesítve.")
            asyncio.create_task(self._loop())

    async def stop(self):
        self.logger.info("🛑 Heartbeat leállítása...")
        self.is_active = False

    async def _loop(self):
        while self.is_active:
            try:
                # 1. RENDSZER-EGÉSZSÉG (Slotok válaszkészsége)
                await self._check_system_health()
                
                # 2. HARDVER MONITORING - Itt történt a hiba korábban
                await self._monitor_resources()

                # 3. ÖNREFLEXIÓ
                self.reflection_counter += 1
                if self.reflection_counter >= self.reflection_limit:
                    asyncio.create_task(self._run_reflection())
                    self.reflection_counter = 0
                
                # Siker esetén nullázunk
                self.consecutive_errors = 0

            except Exception as e:
                self.consecutive_errors += 1
                # Részletesebb logolás, hogy lássuk, pontosan mi hiányzik
                self.logger.error(f"⚠️ Heartbeat anomália ({self.consecutive_errors}/{self.error_threshold}): {str(e)}")
                
                if self.consecutive_errors >= self.error_threshold:
                    await self._trigger_self_restart(f"Kritikus hurok hiba: {str(e)}")

            await asyncio.sleep(self.polling_interval)

    async def _check_system_health(self):
        """Ellenőrzi a slotokat és megpróbálja újraéleszteni a leállt modulokat."""
        for name, slot in self.core.slots.items():
            try:
                # Biztonságos státusz lekérés
                status = slot.status() if hasattr(slot, 'status') else {"loaded": False}
                if not status.get("loaded", False):
                    self.logger.warning(f"🚨 Slot elakadás: {name}. Újratöltés...")
                    slot.load()
            except Exception as e:
                if name == "king":
                    await self._trigger_self_restart(f"Sovereign slot hiba: {e}")
                else:
                    self.logger.error(f"Hiba a(z) {name} slotnál: {e}")

    async def _monitor_resources(self):
        """
        Biztonságos erőforrás figyelés. 
        Kezeli, ha a core.monitor még a régi, vagy ha az orchestratoron keresztül hívjuk.
        """
        stats_packet = {}
        
        # Megpróbáljuk az új metódust az orchestratoron (core) keresztül
        if hasattr(self.core, 'get_hardware_stats'):
            stats_packet = self.core.get_hardware_stats()
        # Ha nincs, de a monitor objektum elérhető és azon van az új metódus
        elif hasattr(self.core, 'monitor') and hasattr(self.core.monitor, 'get_hardware_stats'):
            stats_packet = self.core.monitor.get_hardware_stats()
        # VÉGSZÜKSÉG: Ha valamiért mégis a régi nevet keresné a rendszer
        elif hasattr(self.core, 'monitor') and hasattr(self.core.monitor, 'get_gpu_stats'):
            stats_packet = self.core.monitor.get_gpu_stats()
        else:
            raise AttributeError("A Monitor nem érhető el vagy hiányzik a telemetriai metódus!")

        # Ha a stats_packet egy lista (közvetlen monitor hívás), alakítsuk át vagy kezeljük
        hw_list = stats_packet.get("hardware", []) if isinstance(stats_packet, dict) else stats_packet
        
        if not isinstance(hw_list, list): return

        for device in hw_list:
            dev_type = device.get("type")
            usage = device.get("vram_usage_pct", 0)
            
            if dev_type == "gpu":
                if usage > self.vram_critical_pct:
                    self.logger.critical(f"❗ VRAM KRITIKUS: {usage}%! Slot ürítés...")
                    await self._free_up_auxiliary_slots()
                elif usage > self.vram_warning_pct:
                    self.logger.warning(f"⚠️ VRAM Magas: {usage}%")
            
            elif dev_type == "system":
                if usage > self.ram_threshold_pct:
                    self.logger.warning(f"❗ RENDSZER RAM KRITIKUS: {usage}%")

    async def _free_up_auxiliary_slots(self):
        """Kritikus helyzetben leüríti a segéd-slotokat."""
        for name in ["translator", "scribe"]:
            if name in self.core.slots:
                slot = self.core.slots[name]
                if getattr(slot, 'is_loaded', False):
                    self.logger.info(f"♻️ {name} slot leürítése memóriamentéshez.")
                    if hasattr(slot, 'unload'):
                        slot.unload()

    async def _run_reflection(self):
        """Belső kognitív csekk a King slot segítségével."""
        # Csak akkor fut, ha a King él és nem foglalt
        if "king" in self.core.slots and getattr(self.core.slots["king"], 'is_loaded', False):
            try:
                prompt = (
                    "<|im_start|>system\nYou are SoulCore Internal Sentry. "
                    "Analyze system state. Reply 'YES' or 'NO' only.<|im_end|>\n"
                    "<|im_start|>user\nShould we initiate proactive communication?<|im_end|>\n"
                    "<|im_start|>assistant\n"
                )
                
                # Biztonságos futtatás threadben, hogy ne blokkolja a heartbeat-et
                decision = await self.core._run_in_thread("king", "generate", prompt, {"max_tokens": 5, "temperature": 0.0})
                
                if decision and "YES" in decision.upper():
                    self.logger.info("🎯 Proaktív gondolat észlelve.")
                    if hasattr(self.core, 'process_proactive_thought'):
                        asyncio.create_task(self.core.process_proactive_thought())
            except Exception as e:
                self.logger.error(f"Reflexiós hiba: {e}")

    async def _trigger_self_restart(self, reason):
        """Autonóm újraindítás."""
        self.logger.critical(f"🔥 AUTONÓM ÚJRAINDÍTÁS: {reason}")
        
        if hasattr(self.core, 'db'):
            try:
                self.core.db.save_message("system", "system_event", f"Restart: {reason}")
                self.core.db.save_config("last_shutdown_reason", reason)
            except: pass
        
        await asyncio.sleep(2)
        os.execv(sys.executable, [sys.executable] + sys.argv)