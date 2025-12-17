payload = await request.json()

# Support BOTH:
# 1) direct calls (curl) where payload IS the args
# 2) Vapi tool-calls wrapper where args live inside message.toolCallList[0].arguments
tool_call_id = None
args = payload

if isinstance(payload, dict) and "message" in payload:
    msg = payload.get("message") or {}
    tool_calls = msg.get("toolCallList") or []
    if tool_calls and isinstance(tool_calls, list):
        tool_call_id = tool_calls[0].get("id")
        args = tool_calls[0].get("arguments") or {}

# Forward to n8n
url = f"{N8N_BASE_URL}{path}"
t0 = time.time()

try:
    async with httpx.AsyncClient(timeout=25.0) as client:
        r = await client.post(url, json=args)
except Exception as e:
    raise HTTPException(status_code=502, detail=f"n8n request failed: {str(e)}")

latency_ms = int((time.time() - t0) * 1000)
result_data = _safe_json(r)

# If this came from Vapi, respond in Vapi's required format
if tool_call_id:
    if r.status_code >= 400:
        return {
            "results": [
                {
                    "toolCallId": tool_call_id,
                    "result": {"ok": False, "n8n_status": r.status_code, "n8n_body": result_data}
                }
            ]
        }
    return {
        "results": [
            {
                "toolCallId": tool_call_id,
                "result": result_data
            }
        ]
    }

# Otherwise (curl/manual), keep your existing style
if r.status_code >= 400:
    return JSONResponse(
        status_code=502,
        content={"ok": False, "tool": tool_name, "tenant": x_tenant_id, "n8n_status": r.status_code, "latency_ms": latency_ms, "n8n_body": result_data},
    )

return {"ok": True, "tool": tool_name, "tenant": x_tenant_id, "latency_ms": latency_ms, "data": result_data}
