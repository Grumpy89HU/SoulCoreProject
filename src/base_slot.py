import logging
import time

class BaseSlot:
    def __init__(self, slot_name, config):
        self.name = slot_name
        self.config = config
        self.is_loaded = False
        self.model = None
        self.logger = logging.getLogger(f"Slot-{slot_name}")
        
        # Új: Teljesítmény és kontextus követés
        self.last_used = None
        self.context_window = config.get("context_window", 4096) # Alapértelmezett, ha nincs megadva
        self.usage_count = 0

    def load(self):
        """Modell betöltése a memóriába (implementálandó)"""
        raise NotImplementedError

    def unload(self):
        """Memória felszabadítása"""
        self.logger.info(f"Unloading model from {self.name}...")
        self.model = None
        self.is_loaded = False

    def generate(self, prompt, params=None):
        """Válasz generálása (implementálandó)"""
        raise NotImplementedError

    def safe_generate(self, prompt, params=None):
        """Hibakezelő réteg: ha a generálás elszáll, ne vigye a rendszert."""
        try:
            self.last_used = time.time()
            self.usage_count += 1
            return self.generate(prompt, params)
        except Exception as e:
            self.logger.error(f"Generálási hiba a {self.name} slotban: {e}")
            return None

    def status(self):
        return {
            "name": self.name,
            "role": self.config.get("role"),
            "engine": self.config.get("engine"),
            "is_loaded": self.is_loaded,
            "last_used": self.last_used,
            "usage_count": self.usage_count,
            "vram_allocation": self.config.get("gpu_split", "N/A") # Fontos a 2x5060 Ti miatt
        }