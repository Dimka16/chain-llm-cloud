import os
import time
import json
import pathlib
import socket
import asyncio
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
MODEL = os.getenv("OLLAMA_MODEL", "phi3")
MIN_PROCESS_SECONDS = float(os.getenv("MIN_PROCESS_SECONDS", "5"))

app = FastAPI(title="Service B - Ollama API")

LOG_PATH = os.getenv("LOG_PATH", "/logs/requests.jsonl")

def log_event(obj: dict):
    obj["ts"] = datetime.utcnow().isoformat() + "Z"
    pathlib.Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

class InvokeReq(BaseModel):
    prompt: str

@app.get("/health")
def health():
    return {"ok": True, "service": "b", "host": socket.gethostname()}

@app.post("/invoke")
async def invoke(req: InvokeReq):
    if not req.prompt or len(req.prompt) < 1000:
        raise HTTPException(status_code=400, detail="prompt must be at least 1000 characters")

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            short_prompt = req.prompt[:1200]
            r = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": MODEL, "prompt": short_prompt, "stream": False, "options": {"num_predict": 40, "num_ctx": 1024, "temperature": 0.2,}, },
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log_event({"service":"b","status":502,"error":str(e)})
        raise HTTPException(status_code=502, detail=f"ollama error: {e}")

    elapsed = time.perf_counter() - t0
    if elapsed < MIN_PROCESS_SECONDS:
        await asyncio.sleep(MIN_PROCESS_SECONDS - elapsed)

    total = time.perf_counter() - t0
    log_event({
    "service": "b",
    "status": 200,
    "model": MODEL,
    "prompt_len": len(req.prompt),
    "ollama_seconds": elapsed,
    "total_seconds": total,
    })

    return {
        "service": "b",
        "model": MODEL,
        "llm_text": data.get("response", ""),
        "timing": {
            "ollama_seconds": elapsed,
            "total_seconds": total,
        },
        "host": socket.gethostname(),
    }
