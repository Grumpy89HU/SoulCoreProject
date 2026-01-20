import yaml
import os
from datetime import datetime

class StateManager:
    def __init__(self, config_dir: str):
        self.config_dir = config_dir
        self.config_path = os.path.join(config_dir, "main_config.yaml")
        self.cached_prompts = {}
        self.config = {}
        self.load_config()

    def load_config(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f)
        else:
            raise FileNotFoundError(f"Nem található a konfiguráció: {self.config_path}")

    def get_prompt_template(self, name: str):
        """Beolvassa a sablont a prompts/ mappából."""
        if name in self.cached_prompts:
            return self.cached_prompts[name]
        
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        file_path = os.path.join(base_path, "prompts", f"{name}.txt")
        
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                self.cached_prompts[name] = content
                return content
        return "{query}" # Fallback, ha nincs sablon

    def assemble_system_prompt(self):
        state = self.config["system"]["current_state"]
        state_cfg = self.config["identity"][f"state_{state.lower()}"]
        
        # Alap személyiség betöltése
        if "prompt_file" in state_cfg:
            core_text = self.get_prompt_template(state_cfg["prompt_file"].replace(".txt", ""))
        else:
            core_text = state_cfg.get("personality", "")

        # Dinamikus adatok előkészítése
        now = datetime.now()
        napok = ["hétfő", "kedd", "szerda", "csütörtök", "péntek", "szombat", "vasárnap"]
        
        meta_info = "\n\n[FORRÁSKÓD_CONTEXT_START]\n"
        if self.config["context_injection"]["show_time"]:
            meta_info += f"- Idő: {now.strftime('%Y-%m-%d')} {napok[now.weekday()]}, {now.strftime('%H:%M:%S')}\n"
        if self.config["context_injection"]["show_karma"]:
            meta_info += f"- Karma: {self.config['karma']['current_score']}/100\n"
        meta_info += "[FORRÁSKÓD_CONTEXT_END]"

        return f"{core_text}{meta_info}"

    def get_temperature(self):
        state = self.config["system"]["current_state"]
        return self.config["identity"][f"state_{state.lower()}"]["temperature"]
