import os
import time
import json
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
MODEL_A = os.getenv("OLLAMA_MODEL_A", "phi3:mini")
REMOTE_B_URL = os.getenv("REMOTE_B_URL", "http://host.docker.internal:8002/invoke")
MIN_PROCESS_SECONDS = float(os.getenv("MIN_PROCESS_SECONDS", "5"))

app = FastAPI(title="Service A - Chain Orchestrator")

LOG_PATH = os.getenv("LOG_PATH", "/logs/requests.jsonl")

def log_event(obj: dict):
    obj["ts"] = datetime.utcnow().isoformat() + "Z"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

class ChainReq(BaseModel):
    prompt: str

@app.get("/health")
def health():
    return {"ok": True, "service": "a", "remote_b": REMOTE_B_URL, "model_a": MODEL_A}

@app.post("/chain")
async def chain(req: ChainReq):
    if not req.prompt or len(req.prompt) < 1000:
        raise HTTPException(status_code=400, detail="prompt must be at least 1000 characters")

    t0 = time.perf_counter()

    # Step 1: local LLM A (keep it fast)
    t1 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            ra = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": MODEL_A,
                    "prompt": ("Summarize the user prompt in 3 bullet points.\n\n" + req.prompt)[:700],
                    "stream": False,
                    "options": {
                        "num_predict": 20,
                        "temperature": 0.2,
                    },
                },
            )
            ra.raise_for_status()
            da = ra.json()
    except Exception as e:
        log_event({
            "service": "a",
            "status": 502,
            "stage": "ollama_a",
            "remote_b_url": REMOTE_B_URL,
            "prompt_len": len(req.prompt) if req and req.prompt else None,
            "error": str(e),
        })
        raise HTTPException(status_code=502, detail=f"ollama(A) error: {e}")

    a_elapsed = time.perf_counter() - t1
    a_text = da.get("response", "")

    # Step 2: remote LLM B
    t2 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            rb = await client.post(REMOTE_B_URL, json={"prompt": req.prompt})
            rb.raise_for_status()
            db = rb.json()
    except Exception as e:
        log_event({
            "service": "a",
            "status": 502,
            "stage": "remote_b",
            "remote_b_url": REMOTE_B_URL,
            "prompt_len": len(req.prompt) if req and req.prompt else None,
            "error": str(e),
        })
        raise HTTPException(status_code=502, detail=f"remote(B) error: {e}")

    b_elapsed = time.perf_counter() - t2

    #elapsed = time.perf_counter() - t0
    #if elapsed < MIN_PROCESS_SECONDS:
    #    time.sleep(MIN_PROCESS_SECONDS - elapsed)

    total = time.perf_counter() - t0

    log_event({
    "service": "a",
    "status": 200,
    "prompt_len": len(req.prompt),
    "remote_b_url": REMOTE_B_URL,
    "a_local_seconds": a_elapsed,
    "b_remote_seconds": b_elapsed,
    "end_to_end_seconds": total,
    })

    return {
        "service": "a",
        "model_a": MODEL_A,
        "remote_b_url": REMOTE_B_URL,
        "a_summary": a_text,
        "b_result": db,
        "timing": {
            "a_local_seconds": a_elapsed,
            "b_remote_seconds": b_elapsed,
            "end_to_end_seconds": total,
        },
    }
