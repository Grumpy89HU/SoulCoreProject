import psutil
import logging
import os
import time
from datetime import datetime
from typing import List, Dict, Union, Any

# --- OKOS IMPORT A PY3.12 KOMPATIBILITÁSHOZ ---
try:
    # Először a modernebb nvidia-ml-py csomagot próbáljuk
    from pynvml import nvml as pynvml
except ImportError:
    try:
        # Ha az nincs, akkor a sima pynvml-t
        import pynvml
    except ImportError:
        pynvml = None

class SoulCoreMonitor:
    def __init__(self, log_path: str = 'vault/logs/system.log'):
        # Log könyvtár biztosítása
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self.start_time = time.time()
        self._initial_error = None
        self.has_gpu = False
        self.device_count = 0
        
        # NVML inicializálása
        if pynvml:
            try:
                pynvml.nvmlInit()
                self.has_gpu = True
                self.device_count = pynvml.nvmlDeviceGetCount()
            except Exception as e:
                self.has_gpu = False
                self._initial_error = str(e)
        else:
            self._initial_error = "NVML nincs telepítve (nvidia-ml-py hiányzik)."

        # Logging beállítása
        self.logger = logging.getLogger("SoulCore.Monitor")
        if not self.logger.handlers:
            handler = logging.FileHandler(log_path, encoding='utf-8')
            formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

        # Kezdeti állapot jelzése a logban és konzolon
        if self.has_gpu:
            self.log_event("Monitor", f"GPU Siker: {self.device_count} eszköz detektálva.", level="info")
        else:
            self.log_event("Monitor", f"GPU nem észlelhető: {self._initial_error}", level="warning")

    def get_hardware_stats(self) -> List[Dict[str, Any]]:
        """Összetett telemetria: GPU-k és a Rendszer RAM egyértelműen elkülönítve."""
        stats = []

        # 1. VALÓDI GPU-K LEKÉRDEZÉSE
        if self.has_gpu and pynvml:
            try:
                for i in range(self.device_count):
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                    mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    name = pynvml.nvmlDeviceGetName(handle)
                    
                    if isinstance(name, bytes):
                        name = name.decode('utf-8')

                    stats.append({
                        "type": "gpu",
                        "index": i,
                        "name": f"GPU_{i}: {name}", # Kényszerített név a GUI-nak
                        "load_pct": util.gpu,
                        "temp": temp,
                        "vram_used_mb": mem.used // 1024**2,
                        "vram_total_mb": mem.total // 1024**2,
                        "vram_usage_pct": round((mem.used / mem.total) * 100, 1)
                    })
            except Exception as e:
                self.log_event("Monitor", f"GPU lekérdezési hiba: {e}", level="error")

        # 2. RENDSZER RAM (Egyértelmű névvel, hogy ne GPU_2 legyen)
        try:
            ram = psutil.virtual_memory()
            stats.append({
                "type": "system",
                "index": 99, # Magas index, hogy a sor végére kerüljön
                "name": "SYSTEM RAM (DDR)", 
                "load_pct": psutil.cpu_percent(), 
                "temp": 0,
                "vram_used_mb": ram.used // 1024**2,
                "vram_total_mb": ram.total // 1024**2,
                "vram_usage_pct": ram.percent
            })
        except Exception as e:
            self.log_event("Monitor", f"Rendszer stat hiba: {e}", level="error")

        return stats

    def log_event(self, module: str, message: str, level: str = "info"):
        """Egységes naplózás konzolra és fájlba."""
        full_msg = f"[{module.upper()}] {message}"
        lvl = level.lower()
        icons = {"info": "📡", "warning": "⚠️", "error": "❌", "critical": "🔥"}
        icon = icons.get(lvl, "📝")

        if lvl == "info": self.logger.info(full_msg)
        elif lvl == "warning": self.logger.warning(full_msg)
        elif lvl == "error": self.logger.error(full_msg)
        elif lvl == "critical": self.logger.critical(full_msg)

        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {icon} {full_msg}")

    def check_vram_safety(self, threshold_pct: float = 90.0) -> bool:
        """VRAM vészfék."""
        if not self.has_gpu: return True
        stats = self.get_hardware_stats()
        for s in stats:
            if s["type"] == "gpu" and s["vram_usage_pct"] > threshold_pct:
                self.log_event("Safety", f"VRAM kritikus szint: {s['vram_usage_pct']}%", level="critical")
                return False
        return True

    def __del__(self):
        if hasattr(self, 'has_gpu') and self.has_gpu and pynvml:
            try:
                pynvml.nvmlShutdown()
            except:
                pass