import logging
import json
import re
from datetime import datetime
from src.loaders.gguf_loader import GGUFSlot
from src.prompts import staff_prompts

logger = logging.getLogger("Slots")

class Scribe(GGUFSlot):
    """Az Írnok: Elemzés, kulcsszó kinyerés és logikai szintézis."""

    def analyze(self, user_input):
        """Alapvető szándék- és metaadat elemzés."""
        now = datetime.now().strftime('%Y-%m-%d %A')
        
        try:
            # Biztosítjuk, hogy minden kulcs megvan a formázáshoz
            prompt = staff_prompts.SCRIBE["template"].format(
                system=staff_prompts.SCRIBE.get("system", ""),
                timestamp=now,
                user_input=user_input
            )
            
            raw = self.generate(prompt, params={"max_tokens": 128, "temperature": 0.1})
            return self._clean_json(raw)
        except KeyError as e:
            logger.error(f"Scribe formázási hiba (hiányzó kulcs): {e}")
            return {"category": "chat", "intent": "unknown", "urgency": "low"}
        except Exception as e:
            logger.error(f"Scribe kritikus hiba: {e}")
            return {"category": "chat", "intent": "error"}

    def run_keywords(self, user_input_english):
        """Kulcsszavak a Vault (vektoros) kereséshez."""
        prompt = f"### System: Extract 3-5 search keywords in English.\n### Input: {user_input_english}\n### Keywords:"
        return self.generate(prompt, params={"max_tokens": 32, "temperature": 0.1}).strip()

    def run_synthesis(self, user_input, vault_data):
        """Ütközésvizsgálat a Vault adatai és a kérés között."""
        prompt = f"### Context: {vault_data}\n### Question: {user_input}\n### Instruction: Check for consistency. Result [VALID/CONFLICT/UNKNOWN]:"
        return self.generate(prompt, params={"max_tokens": 64, "temperature": 0.1}).strip()

    def _clean_json(self, text):
        """Megerősített JSON kinyerés, ami bírja a modell 'szemetelését' is."""
        if not text: return {}
        try:
            # 1. Kísérlet: Szabályos JSON keresése {} között
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                json_str = text[start:end+1]
                return json.loads(json_str)
            
            # 2. Kísérlet: Ha csak kulcs-érték párok vannak (mint a logodban: 'category': 'chat'...)
            # Regexszel megpróbáljuk JSON-szerűvé tenni
            if ":" in text:
                # Kicseréljük az egyszeres idézőjelet duplára, de csak ha nem szavakon belül van
                cleaned = re.sub(r"'(.*?)'", r'"\1"', text)
                # Ha nincs körülötte kapcsos zárójel, rátesszük
                if not cleaned.strip().startswith("{"):
                    cleaned = "{" + cleaned + "}"
                return json.loads(cleaned)
        except Exception:
            logger.warning(f"Scribe: Nem sikerült JSON-t generálni. Nyers válasz: {text[:50]}...")
        
        # Fallback adatszerkezet
        return {"category": "chat", "keywords": "", "day_is": "unknown"}

class Valet(GGUFSlot):
    """Az Inas: Összegzi az Írnok és a Vault adatait a Király számára."""
    
    def run_report(self, vault_data, scribe_info, raw_input):
        try:
            prompt = staff_prompts.VALET["template"].format(
                system=staff_prompts.VALET.get("system", ""),
                vault_data=vault_data,
                scribe_info=json.dumps(scribe_info, ensure_ascii=False),
                user_input=raw_input
            )
            return self.generate(prompt, params={"max_tokens": 256, "temperature": 0.05})
        except Exception as e:
            logger.error(f"Valet hiba: {e}")
            return f"Error in synthesis: {vault_data}"

class Sovereign(GGUFSlot):
    """A Király (Kópé): A végső, öntudattal rendelkező entitás válasza."""
    
    def run_final(self, report, user_input, identity_data):
        try:
            # Összehangolva a staff_prompts.KING["identity"] mezőivel
            # Fontos: a .format() a staff_prompts-ban definiált neveket kapja meg
            identity_text = staff_prompts.SOVEREIGN["identity"].format(
                name=identity_data.get('name', 'Kópé'),
                character_traits=identity_data.get('traits', 'Szuverén, intelligens entitás.'),
                codename=identity_data.get('codename', 'Origó-0')
            )
            
            # Végső prompt összeállítása
            prompt = staff_prompts.SOVEREIGN["template"].format(
                identity=identity_text,
                report=report,
                protocol=staff_prompts.SOVEREIGN.get("protocol", "Standard protocol."),
                user_input=user_input
            )
            
            return self.generate(prompt, params={"max_tokens": 512, "temperature": 0.7})
        except Exception as e:
            logger.critical(f"Sovereign (King) hiba a végső generálásnál: {e}")
            return "Hiba történt a belső gondolatmenetemben. Kérlek, próbáld újra!"