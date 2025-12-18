import os
import json
import time
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="21ai Tool Gateway", version="1.0.0")


def _get_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def _load_tool_map() -> Dict[str, Dict[str, str]]:
    raw = _get_env("TOOL_MAP_JSON")
    try:
        return json.loads(raw)
    except Exception as e:
        raise RuntimeError(f"Invalid TOOL_MAP_JSON: {e}")


async def call_n8n(path_or_url: str, payload: Dict[str, Any]) -> Any:
    """
    Calls n8n webhook with required auth header.
    TOOL_MAP_JSON can store either:
      - full URL: https://.../webhook/xyz
      - or path: /webhook/xyz
    """
    base_url = _get_env("N8N_BASE_URL").rstrip("/")
    secret = _get_env("N8N_BOOKING_SECRET")

    if path_or_url.startswith("http"):
        url = path_or_url
    else:
        if not path_or_url.startswith("/"):
            path_or_url = "/" + path_or_url
        url = base_url + path_or_url

    headers = {
        "Content-Type": "application/json",
        "x-21ai-secret": secret,
    }

    start = time.time()
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, json=payload, headers=headers)
    latency_ms = int((time.time() - start) * 1000)

    # n8n often returns json, but keep safe fallback
    text = r.text
    try:
        data = r.json()
    except Exception:
        data = {"raw": text}

    if r.status_code >= 400:
        raise HTTPException(
            status_code=r.status_code,
            detail={
                "error": "n8n_request_failed",
                "status_code": r.status_code,
                "latency_ms": latency_ms,
                "response": data,
            },
        )

    return {
        "ok": True,
        "latency_ms": latency_ms,
        "data": data,
    }


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/tool/call")
async def tool_call(request: Request):
    """
    Expected body:
    {
      "toolset": "demo",
      "tool": "calendar_slots" | "calendar_set_appointment",
      "payload": { ... }
    }
    """
    body = await request.json()
    toolset = body.get("toolset") or "demo"
    tool = body.get("tool")
    payload = body.get("payload") or {}

    if not tool:
        raise HTTPException(status_code=400, detail="Missing 'tool'")

    tool_map = _load_tool_map()

    if toolset not in tool_map:
        raise HTTPException(status_code=400, detail=f"Unknown toolset: {toolset}")

    if tool not in tool_map[toolset]:
        raise HTTPException(status_code=400, detail=f"Unknown tool '{tool}' in toolset '{toolset}'")

    path_or_url = tool_map[toolset][tool]

    # Forward to n8n with auth header
    result = await call_n8n(path_or_url, payload)
    return JSONResponse(result)
