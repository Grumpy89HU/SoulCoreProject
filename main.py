import uvicorn
import os, sys, signal, time, traceback, json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from core.kernel import Kernel
from core.logger import get_logger

log = get_logger("api")
app = FastAPI(title="LÉLEK CORE API")
kernel = Kernel("config")

app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_methods=["*"], 
    allow_headers=["*"]
)

# --- ALAPVETŐ ÚTVONALAK ---

@app.get("/")
async def root():
    return {"status": "online", "model": "lelek-core-v1"}

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

async def stream_generator(user_query: str):
    full_response = await kernel.process_message(user_query)
    chunk = {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "lelek-core-v1",
        "choices": [{"index": 0, "delta": {"content": full_response}, "finish_reason": None}]
    }
    yield f"data: {json.dumps(chunk)}\n\n"
    yield "data: [DONE]\n\n"

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
        messages = body.get("messages", [])
        stream_requested = body.get("stream", False)
        
        user_query = ""
        for msg in reversed(messages):
            if msg["role"] == "user":
                user_query = msg["content"]
                break

        log.info(f"Kérés: {user_query[:50]}... | Stream: {stream_requested}")

        if stream_requested:
            return StreamingResponse(stream_generator(user_query), media_type="text/event-stream")

        response_text = await kernel.process_message(user_query)
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
    os.execv(sys.executable, ['python3'] + sys.argv)

@app.post("/system/stop")
async def stop_system():
    log.info("Leállítás kérése...")
    os.kill(os.getpid(), signal.SIGINT)
    return {"status": "stopping"}

if __name__ == "__main__":
    api_cfg = kernel.state_manager.config.get("api", {"host": "0.0.0.0", "port": 8000})
    uvicorn.run(app, host=api_cfg["host"], port=api_cfg["port"])