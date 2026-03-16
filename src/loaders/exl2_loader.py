import os
import logging
from huggingface_hub import snapshot_download
from exllamav2 import (
    ExLlamaV2,
    ExLlamaV2Config,
    ExLlamaV2Cache,
    ExLlamaV2Tokenizer,
)
from exllamav2.generator import ExLlamaV2BaseGenerator
from src.base_slot import BaseSlot

class EXL2Slot(BaseSlot):
    def __init__(self, slot_name, config):
        # Az ősosztály (BaseSlot) inicializálása beállítja a self.logger-t és self.name-et
        super().__init__(slot_name, config)
        
        # Elérési utak meghatározása
        self.model_path = config.get("model_path")
        self.repo_id = config.get("repo_id")
        
        # ExLlamaV2 specifikus objektumok
        self.model = None
        self.tokenizer = None
        self.cache = None
        self.generator = None

    def _ensure_model_exists(self):
        """Ellenőrzi a modellt a lemezen, ha hiányzik, letölti a HuggingFace-ről."""
        # Ellenőrizzük, hogy a mappa létezik-e és van-e benne konfigurációs fájl
        config_file = os.path.join(self.model_path, "config.json")
        
        if not os.path.exists(config_file):
            if not self.repo_id:
                raise ValueError(f"[{self.name}] A modell hiányzik ({self.model_path}), és nincs repo_id megadva!")
            
            self.logger.info(f"Modell nem található. Letöltés indítása: {self.repo_id} -> {self.model_path}")
            
            # Mappa létrehozása
            os.makedirs(self.model_path, exist_ok=True)
            
            # Letöltés (folytatható, symlinkek nélkül a könnyebb kezelhetőségért)
            snapshot_download(
                repo_id=self.repo_id,
                local_dir=self.model_path,
                local_dir_use_symlinks=False,
                resume_download=True
            )
            self.logger.info("Letöltés sikeresen befejeződött.")
        else:
            self.logger.info(f"Modell megtalálva a helyi tárolóban: {self.model_path}")

    def load(self):
        """A modell tényleges betöltése a GPU memóriába."""
        try:
            # 1. Ellenőrzés / Letöltés
            self._ensure_model_exists()

            # 2. ExLlamaV2 Konfiguráció
            exl2_config = ExLlamaV2Config()
            exl2_config.model_dir = self.model_path
            exl2_config.prepare()

            # 3. VRAM Allokáció (MB -> GB konverzió)
            gpu_id = self.config.get('gpu_id', 0)
            max_vram = float(self.config.get('max_vram_mb', 4096)) / 1024.0
            
            # Dinamikus split lista (max 2 GPU-ig, ahogy a tervedben szerepelt)
            allocation = [0.0] * 2
            if gpu_id < len(allocation):
                allocation[gpu_id] = max_vram
            
            # 4. Modell betöltése
            self.model = ExLlamaV2(exl2_config)
            self.logger.info(f"Modell betöltése a GPU:{gpu_id} eszközre ({max_vram} GB limit)...")
            self.model.load(allocation)

            # 5. Kiegészítők inicializálása
            self.tokenizer = ExLlamaV2Tokenizer(exl2_config)
            self.cache = ExLlamaV2Cache(self.model, lazy=True)
            self.generator = ExLlamaV2BaseGenerator(self.model, self.cache, self.tokenizer)

            self.is_loaded = True
            self.logger.info(f"Slot '{self.name}' sikeresen aktiválva.")
            
        except Exception as e:
            self.logger.error(f"Hiba a betöltés során: {str(e)}")
            self.is_loaded = False
            raise e

    def unload(self):
        """VRAM felszabadítása."""
        if self.model:
            self.model.unload()
            self.model = None
            self.cache = None
            self.generator = None
            self.tokenizer = None
            self.is_loaded = False
            self.logger.info(f"Slot '{self.name}' eltávolítva a VRAM-ból.")

    def generate(self, prompt, params=None):
        """Szöveggenerálás az EXL2 motorral."""
        if not self.is_loaded:
            return "Hiba: A modell nincs betöltve."

        max_new_tokens = params.get('max_tokens', 200) if params else 200
        
        # Egyszerű generálás (a prompt levágásával a válaszról)
        output = self.generator.generate_simple(prompt, max_new_tokens=max_new_tokens)
        return output.replace(prompt, "").strip()