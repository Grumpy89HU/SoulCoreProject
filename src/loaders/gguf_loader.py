import os
from huggingface_hub import hf_hub_download
from llama_cpp import Llama
from src.base_slot import BaseSlot

class GGUFSlot(BaseSlot):
    def __init__(self, slot_name, config):
        super().__init__(slot_name, config)
        self.model_dir = config.get("model_path", "./models")
        self.repo_id = config.get("repo_id")
        self.filename = config.get("filename")
        # Biztosítjuk a tiszta elérési utat
        if self.filename:
            self.full_path = os.path.join(self.model_dir, self.filename)
        else:
            self.full_path = None

    def _ensure_model_exists(self):
        """Csak akkor reklamál vagy tölt le, ha nincs meg a fájl."""
        if not self.filename:
            raise ValueError(f"Slot {self.name}: Nincs megadva 'filename' a konfigurációban!")
        
        # Ha a fájl létezik, minden rendben, mehetünk tovább
        if os.path.exists(self.full_path):
            return

        # Ha nem létezik, megpróbáljuk letölteni, de ehhez kell a repo_id
        if not self.repo_id:
            raise FileNotFoundError(
                f"Slot {self.name}: A fájl ({self.full_path}) nem található, "
                "és nincs 'repo_id' a letöltéshez!"
            )
        
        self.logger.info(f"Modell letöltése: {self.repo_id}...")
        os.makedirs(self.model_dir, exist_ok=True)
        hf_hub_download(
            repo_id=self.repo_id,
            filename=self.filename,
            local_dir=self.model_dir,
            local_dir_use_symlinks=False
        )

    def load(self):
        try:
            self._ensure_model_exists()
            self.logger.info(f"GGUF modell ébresztése: {self.filename}")

            # A némítást az Orchestrator végzi kívülről!
            self.model = Llama(
                model_path=self.full_path,
                n_gpu_layers=-1, 
                n_ctx=self.config.get("n_ctx", 2048), # MOST MÁR A TOKEN LIMITET HASZNÁLJUK!
                verbose=False
            )
            
            self.is_loaded = True
            self.logger.info(f"Slot {self.name} készen áll.")
        except Exception as e:
            self.logger.error(f"Sikertelen betöltés: {e}")
            self.is_loaded = False
            raise

    def unload(self):
        if hasattr(self, 'model') and self.model:
            self.model.close()
            del self.model
        self.is_loaded = False
        self.logger.info(f"Slot {self.name} VRAM felszabadítva.")

    def generate(self, prompt, params=None):
        if not self.is_loaded: 
            return "Hiba: Modell nincs betöltve."
        
        params = params or {}
        output = self.model(
            prompt,
            max_tokens=params.get("max_tokens", 512),
            temperature=self.config.get("temperature", 0.7),
            stop=["<|eot_id|>", "<|im_end|>", "User:", "Kópé:"]
        )
        return output["choices"][0]["text"].strip()