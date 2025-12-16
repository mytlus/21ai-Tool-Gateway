import os
import time
import json
import httpx
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse

APP_ENV = os.getenv("APP_ENV", "production")
TOOL_GATEWAY_SECRET = os.getenv("TOOL_GATEWAY_SECRET", "")

# Base URL for your n8n instance (no trailing slash)
N8N_BASE_URL = os.getenv("N8N_BASE_URL", "").rstrip("/")

# Simple mapping (v1) – later we move this to Supabase
# Format:
#  TOOL_MAP_JSON = {"tenant_123": {"calendar_slots": "/webhook/xxx", "calendar_set_appointment": "/webhook/yyy"}}
TOOL_MAP_JSON = os.getenv("TOOL_MAP_JSON", "{}")

app = FastAPI(title="21ai Tool Gateway", version="1.0.0")


@app.get("/health")
def health():
    return {"ok": True, "env": APP_ENV, "ts": int(time.time())}


def _load_map() -> dict:
    try:
        return json.loads(TOOL_MAP_JSON) if TOOL_MAP_JSON else {}
    except Exception:
        return {}


def _auth(authorization: str | None):
    if not TOOL_GATEWAY_SECRET:
        # If you forgot to set it, fail closed.
        raise HTTPException(status_code=500, detail="TOOL_GATEWAY_SECRET not set")

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = authorization.split(" ", 1)[1].strip()
    if token != TOOL_GATEWAY_SECRET:
        raise HTTPException(status_code=403, detail="Invalid token")


@app.post("/v1/tools/{tool_name}")
async def tool_proxy(
    tool_name: str,
    request: Request,
    authorization: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None),
):
    """
    Vapi (or any client) calls:
      POST /v1/tools/calendar_slots
    with headers:
      Authorization: Bearer <TOOL_GATEWAY_SECRET>
      X-Tenant-Id: <tenant_key>
    and JSON body:
      { ... tool args ... }
    """
    _auth(authorization)

    if not N8N_BASE_URL:
        raise HTTPException(status_code=500, detail="N8N_BASE_URL not set")

    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-Id")

    tool_map = _load_map()
    tenant_tools = tool_map.get(x_tenant_id)
    if not tenant_tools:
        raise HTTPException(status_code=404, detail=f"Unknown tenant: {x_tenant_id}")

    path = tenant_tools.get(tool_name)
    if not path:
        raise HTTPException(status_code=404, detail=f"Unknown tool for tenant: {tool_name}")

    payload = await request.json()

    # Forward to n8n
    url = f"{N8N_BASE_URL}{path}"
    t0 = time.time()

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            r = await client.post(url, json=payload)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"n8n request failed: {str(e)}")

    latency_ms = int((time.time() - t0) * 1000)

    # Pass through status if n8n fails, but keep message readable for Vapi
    if r.status_code >= 400:
        return JSONResponse(
            status_code=502,
            content={
                "ok": False,
                "tool": tool_name,
                "tenant": x_tenant_id,
                "n8n_status": r.status_code,
                "latency_ms": latency_ms,
                "n8n_body": _safe_json(r),
            },
        )

    return {
        "ok": True,
        "tool": tool_name,
        "tenant": x_tenant_id,
        "latency_ms": latency_ms,
        "data": _safe_json(r),
    }


def _safe_json(resp: httpx.Response):
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text[:2000]}