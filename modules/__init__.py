import os
import importlib.util
from core.logger import get_logger

log = get_logger("modules")

def load_modules():
    modules = {}
    modules_dir = os.path.dirname(__file__)

    for filename in os.listdir(modules_dir):
        if filename.endswith(".py") and filename != "__init__.py":
            module_name = filename[:-3]
            file_path = os.path.join(modules_dir, filename)
            
            try:
                # Dinamikus importálás
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                
                # Ellenőrizzük a belépési pontot (execute vagy run)
                executor = None
                if hasattr(mod, "execute"):
                    executor = mod.execute
                elif hasattr(mod, "run"):
                    executor = mod.run
                
                if executor:
                    modules[module_name] = {
                        "execute": executor,
                        "description": getattr(mod, "description", "Nincs leírás")
                    }
                    log.info(f"Modul sikeresen betöltve: {module_name}")
                else:
                    log.warning(f"Modul kihagyva (nincs execute/run): {module_name}")
                    
            except Exception as e:
                log.error(f"Hiba a(z) {module_name} modul betöltésekor: {e}")

    return modules