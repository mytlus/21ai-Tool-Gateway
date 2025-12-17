import os
import time
import uuid
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="21ai Control Plane", version="1.0.0")

# --- CORS (lock down later) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WORKER_BASE_URL = os.getenv("WORKER_BASE_URL", "").rstrip("/")  # e.g. https://glistening-truth-production.up.railway.app
REQUEST_TIMEOUT_S = float(os.getenv("REQUEST_TIMEOUT_S", "30"))

# -------------------- Models --------------------
class StartAgentRequest(BaseModel):
    agentId: str = Field(..., description="Unique agent template/instance id")
    roomName: Optional[str] = Field(None, description="If omitted, we generate one")
    agentConfig: Dict[str, Any] = Field(default_factory=dict)

class StopAgentRequest(BaseModel):
    agentId: str
    roomName: Optional[str] = None

# -------------------- Routes --------------------
@app.get("/health")
async def health():
    return {"ok": True, "service": "control-plane", "ts": int(time.time())}

@app.post("/agent/start")
async def agent_start(req: StartAgentRequest):
    if not WORKER_BASE_URL:
        raise HTTPException(status_code=500, detail="WORKER_BASE_URL is not set")

    room_name = req.roomName or f"agent_{req.agentId}_{int(time.time() * 1000)}"
    payload = {
        "agentId": req.agentId,
        "roomName": room_name,
        "agentConfig": req.agentConfig,
        # Add anything else your worker expects here (livekitUrl, apiKey/secret, etc.)
    }

    url = f"{WORKER_BASE_URL}/agent/start"
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
            r = await client.post(url, json=payload)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail={"worker_error": r.text})
        return {"ok": True, "roomName": room_name, "worker": r.json() if r.headers.get("content-type","").startswith("application/json") else r.text}
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Worker request failed: {str(e)}")

@app.post("/agent/stop")
async def agent_stop(req: StopAgentRequest):
    if not WORKER_BASE_URL:
        raise HTTPException(status_code=500, detail="WORKER_BASE_URL is not set")

    payload = {"agentId": req.agentId}
    if req.roomName:
        payload["roomName"] = req.roomName

    url = f"{WORKER_BASE_URL}/agent/stop"
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
            r = await client.post(url, json=payload)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail={"worker_error": r.text})
        return {"ok": True, "worker": r.json() if r.headers.get("content-type","").startswith("application/json") else r.text}
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Worker request failed: {str(e)}")

# If you *really* need raw request.json(), it must be inside a function like this:
@app.post("/debug/echo")
async def echo(request: Request):
    payload = await request.json()
    return {"ok": True, "payload": payload}
