import yaml
import os
import json
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
            raise FileNotFoundError(f"Config not found: {self.config_path}")

    def get_template(self, name: str):
        """Beolvassa a txt fájlokat a prompts/ mappából cachinggel."""
        if name in self.cached_prompts:
            return self.cached_prompts[name]
            
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        file_path = os.path.join(base_path, "prompts", f"{name}.txt")
        
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                self.cached_prompts[name] = content
                return content
        return ""

    def get_rag_preprocessor_prompt(self):
        """A kis 1B modellnek küldendő RAG tisztító prompt (angol logika)."""
        return self.get_template("rag_cleaner_en")

    def get_scribe_prompt(self):
        """Az írnoknak küldendő utólagos elemző prompt (angol logika)."""
        return self.get_template("scribe_logic_en")

    def assemble_kope_system_prompt(self, model_name="lelek-core-v1", cleaned_context=""):
        """A nagy 12B modell (Kópé) tehermentesített promptja a JSON személyiséggel."""
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        persona_path = os.path.join(base_path, "prompts", "personas.json")
        
        # 1. SZEMÉLYISÉG BETÖLTÉSE
        try:
            if os.path.exists(persona_path):
                with open(persona_path, "r", encoding="utf-8") as f:
                    personas = json.load(f)
                
                # Modell alapú választás, fallback a defaultra
                active_persona = personas.get(model_name, personas.get("default", {}))
                identity = active_persona.get("identity", "Te vagy Kópé, a ravasz magyar népmesei alak.")
            else:
                raise FileNotFoundError("Personas JSON hiányzik.")
        except Exception as e:
            # Karakter-mentőöv, ha a JSON elszállna
            identity = ("VISELKEDÉS: Te vagy Kópé, a magyar népmesék ravasz, szarkasztikus alakja. "
                       "Stílusod ízes, népi, pimasz. Ha a gép elromlik, te akkor is betyár maradsz!")

        # 2. DINAMIKUS META ADATOK (Idő + Karma)
        now = datetime.now()
        napok = ["hétfő", "kedd", "szerda", "csütörtök", "péntek", "szombat", "vasárnap"]
        
        meta = f"\n--- RENDSZER INFÓ ---\n"
        meta += f"- Idő: {now.strftime('%Y-%m-%d')} {napok[now.weekday()]}, {now.strftime('%H:%M:%S')}\n"
        
        if self.config.get("context_injection", {}).get("show_karma"):
            karma_score = self.config.get('karma', {}).get('current_score', 100)
            meta += f"- Rendszer Karma: {karma_score}/100\n"
        meta += "--- VÉGE ---\n"
        
        # 3. ÖSSZEÁLLÍTÁS
        prompt = (
            f"{identity}\n\n"
            f"### KONTEXTUS (Tények a világból):\n{cleaned_context if cleaned_context else 'Nincs külső adat.'}\n\n"
            f"{meta}"
        )
        return prompt

    def get_temperature(self):
        """Visszahozva a régi logikát a konfigurációból."""
        try:
            state = self.config.get("system", {}).get("current_state", "stable")
            return self.config["identity"][f"state_{state.lower()}"]["temperature"]
        except:
            return 0.7 # Biztonsági tartalék