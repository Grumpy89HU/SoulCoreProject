import uvicorn
import os, sys, signal, time, traceback, json, asyncio, hashlib
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from core.kernel import Kernel
from core.logger import get_logger
from core.heartbeat import Heartbeat
from core.ollama_core import discover_models_loop 
from contextlib import asynccontextmanager

log = get_logger("api")

# --- STARTUP & SHUTDOWN (LIFESPAN) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
    log.info("SoulCore API indul... Háttérfolyamatok aktiválása.")
    
    # Ollama felfedező hurok
    discovery_task = asyncio.create_task(discover_models_loop())
    
    # --- SZÍVVERÉS AKTIVÁLÁSA ---
    # Átadjuk a kernel adatbázis-kezelőjét a heartbeatnek
    heartbeat = Heartbeat(kernel.db)
    heartbeat_task = asyncio.create_task(heartbeat.start())
    
    log.info("Ollama Discovery és Heartbeat folyamatok aktívak.")
    
    yield  # Itt fut az API

    # SHUTDOWN
    log.info("Leállás... Háttérfolyamatok lezárása.")
    discovery_task.cancel()
    heartbeat.stop()
    
    try:
        await asyncio.gather(discovery_task, return_exceptions=True)
    except asyncio.CancelledError:
        pass

# A FastAPI példányosítása a Lifespan handler-rel
app = FastAPI(title="LÉLEK CORE API", lifespan=lifespan)

# A Kernelt globálisan példányosítjuk
kernel = Kernel("config")

app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_methods=["*"], 
    allow_headers=["*"]
)

# --- SEGÉDFÜGGVÉNYEK ---

async def stream_generator(user_query: str, conv_id: str):
    """Válaszok streamelése stabil session azonosítóval."""
    full_response = await kernel.process_message(user_query, conv_id=conv_id)
    chunk = {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "lelek-core-v1",
        "choices": [{"index": 0, "delta": {"content": full_response}, "finish_reason": None}]
    }
    yield f"data: {json.dumps(chunk)}\n\n"
    yield "data: [DONE]\n\n"

# --- ALAPVETŐ ÚTVONALAK ---

@app.get("/")
async def root():
    return {"status": "online", "model": "lelek-core-v1", "identity": "Origó"}

@app.get("/v1/models")
async def list_models():
    log.info("Modell lista lekérve.")
    return {
        "object": "list",
        "data": [
            {
                "id": "lelek-core-v1",
                "object": "model",
                "created": int(time.time()),
                "owned_by": "origo"
            }
        ]
    }

# --- CHAT COMPLETIONS ---

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
        
        # --- INTELLIGENS ID KINYERÉS ÉS HASHING ---
        # Megpróbáljuk kinyerni az ID-t a JSON-ból
        raw_id = (
            body.get("chat_id") or 
            body.get("conversation_id") or 
            body.get("id") or
            (body.get("metadata", {}) if isinstance(body.get("metadata"), dict) else {}).get("chat_id")
        )
        
        messages = body.get("messages", [])
        
        # Ha nincs ID, az első üzenet tartalmából generálunk egy egyedi, stabil ujjlenyomatot
        if (not raw_id or raw_id == "default_session") and messages:
            seed = messages[0].get("content", "empty_seed")
            conv_id = f"soul-{hashlib.md5(seed.encode()).hexdigest()[:12]}"
        else:
            conv_id = raw_id if raw_id else "default_session"
        # ------------------------------------------

        stream_requested = body.get("stream", False)
        
        # Utolsó felhasználói üzenet kinyerése
        user_query = ""
        for msg in reversed(messages):
            if msg["role"] == "user":
                user_query = msg["content"]
                break

        log.info(f"Kérés: {user_query[:50]}... | ID: {conv_id} | Stream: {stream_requested}")

        if stream_requested:
            return StreamingResponse(stream_generator(user_query, conv_id), media_type="text/event-stream")

        # Nem streamelt válasz
        response_text = await kernel.process_message(user_query, conv_id=conv_id)
        
        return {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "lelek-core-v1",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": response_text}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 0}
        }
    except Exception as e:
        log.error(f"API HIBA: {traceback.format_exc()}")
        return JSONResponse(status_code=500, content={"error": {"message": str(e)}})

# --- RENDSZER VEZÉRLÉS ---

@app.post("/system/reload")
async def reload_config():
    kernel.state_manager.load_config()
    kernel.state_manager.cached_prompts.clear()
    log.info("Konfiguráció sikeresen újratöltve.")
    return {"status": "success"}

@app.post("/system/restart")
async def restart_system():
    log.info("Rendszer újraindítása...")
    os.execv(sys.executable, [sys.executable] + sys.argv)

@app.post("/system/stop")
async def stop_system():
    log.info("Leállítás kérése...")
    os.kill(os.getpid(), signal.SIGINT)
    return {"status": "stopping"}

if __name__ == "__main__":
    api_cfg = kernel.state_manager.config.get("api", {"host": "0.0.0.0", "port": 8000})
    uvicorn.run(app, host=api_cfg["host"], port=api_cfg["port"])