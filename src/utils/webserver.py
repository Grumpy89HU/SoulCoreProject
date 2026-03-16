import os
import logging
import psutil
import time
import uuid
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger("soulcore.web")
_internal_core = None 

def integrate_web_interface(app: FastAPI):
    # 1. Statikus fájlok kiszolgálása
    if os.path.exists("web"):
        app.mount("/gui_static", StaticFiles(directory="web"), name="gui_static")

    def check_core():
        """Belső ellenőrzés, hogy a Kernel fut-e."""
        global _internal_core
        if _internal_core is None:
            logger.error("SoulCore Kernel hivatkozás hiányzik (None)")
            raise HTTPException(status_code=503, detail="SoulCore Kernel Offline")
        return _internal_core

    # --- AUTHENTICATION ---
    
    @app.get("/login", response_class=HTMLResponse)
    async def login_page():
        path = "web/login.html"
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f: return f.read()
        return "<h2>SoulCore Login GUI missing</h2>"

    @app.post("/login")
    async def login(request: Request):
        try:
            data = await request.json()
            username = data.get("username")
            password = data.get("password")
            
            core = check_core()
            
            if hasattr(core.db, 'verify_user') and core.db.verify_user(username, password):
                request.session["user"] = username
                logger.info(f"Sikeres belépés: {username}")
                return {"status": "success", "user": username}
            
            raise HTTPException(status_code=401, detail="Hibás hitelesítés")
        except Exception as e:
            logger.error(f"Login hiba: {e}")
            raise HTTPException(status_code=401, detail="Belépési hiba")

    @app.get("/logout")
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse(url="/login")

    # --- API & CONTROL ---

    @app.get("/", response_class=HTMLResponse)
    async def root(request: Request):
        if "user" not in request.session: 
            return RedirectResponse(url="/login")
        path = "web/index.html"
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f: return f.read()
        return "Main GUI missing."

    @app.get("/chats/list")
    async def list_chats(request: Request):
        if "user" not in request.session: raise HTTPException(status_code=403)
        core = check_core()
        return core.db.get_all_chat_sessions(user_id=request.session["user"])

    @app.get("/chats/history/{chat_id}")
    async def get_history(chat_id: str, request: Request):
        if "user" not in request.session: raise HTTPException(status_code=403)
        core = check_core()
        return core.db.get_chat_history(chat_id)

    @app.post("/process")
    async def process(request: Request):
        if "user" not in request.session: raise HTTPException(status_code=403)
        
        core = check_core()
        data = await request.json()
        
        c_id = data.get("chat_id")
        if not c_id or c_id == "null":
            c_id = f"chat_{str(uuid.uuid4())[:8]}"
        
        result = await core.process_pipeline(
            user_query=data.get("query"),
            chat_id=c_id,
            user_id=request.session.get("user")
        )
        return JSONResponse(content=result)

    @app.get("/status")
    async def get_status(request: Request):
        """A GUI fejlécének állapota."""
        if "user" not in request.session: return {"status": "unauthorized"}
        
        if _internal_core is None:
            return {"hardware": [], "kernel": {"uptime": 0, "status": "initializing"}}

        core = _internal_core
        
        # JAVÍTÁS: A core.last_hw_stats-ot használjuk, amit a main.py heartbeat-je frissít
        hw_stats = getattr(core, 'last_hw_stats', [])
        
        # Ha a heartbeat még nem futott le, vagy üres, adjunk egy alap CPU infót
        if not hw_stats:
            hw_stats = [{
                "type": "system",
                "name": "System CPU (Initializing...)", 
                "load_pct": psutil.cpu_percent(), 
                "temp": 0,
                "vram_used_mb": 0,
                "vram_total_mb": 0,
                "vram_usage_pct": 0
            }]

        return {
            "hardware": hw_stats,
            "kernel": {
                "uptime": round(time.time() - getattr(core, 'start_time', time.time()), 1),
                "active_slots": sum(1 for s in core.slots.values() if getattr(s, 'is_loaded', False)),
                "user": request.session.get("user"),
                "identity": getattr(core, 'identity', 'SoulCore')
            }
        }

    return app

def set_core_reference(instance):
    global _internal_core
    _internal_core = instance
    logger.info("Kernel hivatkozás csatolva a Webserverhez.")