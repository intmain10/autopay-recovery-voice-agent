"""Webhook server Vapi calls for tool execution and call lifecycle events, plus a live dashboard."""
from __future__ import annotations

import json
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse

from . import config, db, razorpay_client
from . import voices
from .assistant import call_overrides
from .tools import run_tool

app = FastAPI(title="Autopay Recovery Voice Agent")

ENDED_REASON_DISPOSITION = {
    "voicemail": "voicemail",
    "customer-did-not-answer": "no_answer",
    "customer-busy": "no_answer",
}


def _customer_id_for(call: dict) -> Optional[str]:
    """Map a Vapi call to our customer: registered dialer mapping first, then call variables."""
    call_id = call.get("id", "")
    known = db.get_call(call_id) if call_id else None
    if known:
        return known["customer_id"]
    overrides = call.get("assistantOverrides") or {}
    return (overrides.get("variableValues") or {}).get("customer_id")


def _parse_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


@app.post("/vapi/webhook")
async def vapi_webhook(request: Request, x_vapi_secret: Optional[str] = Header(default=None)):
    if config.VAPI_WEBHOOK_SECRET and x_vapi_secret != config.VAPI_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="bad secret")

    msg = (await request.json()).get("message", {})
    kind = msg.get("type")
    call = msg.get("call") or {}
    call_id = call.get("id", "unknown-call")
    customer_id = _customer_id_for(call)

    if kind == "tool-calls":
        results = []
        for tc in msg.get("toolCallList") or []:
            fn = tc.get("function") or {}
            if not customer_id:
                result = {"ok": False, "message": "No customer linked to this call. Apologise and end."}
            else:
                result = run_tool(fn.get("name", ""), _parse_args(fn.get("arguments")), call_id, customer_id)
            results.append({"toolCallId": tc.get("id"), "result": json.dumps(result)})
        return {"results": results}

    if not customer_id:
        return {"ok": True}

    db.register_call(call_id, customer_id)

    if kind == "status-update":
        db.update_call(call_id, status=msg.get("status"))
        db.log_event(call_id, customer_id, "status", {"status": msg.get("status")})

    elif kind == "end-of-call-report":
        analysis = msg.get("analysis") or {}
        artifact = msg.get("artifact") or {}
        ended = msg.get("endedReason") or ""
        db.update_call(
            call_id, status="ended", ended_reason=ended,
            summary=(db.get_call(call_id) or {}).get("summary") or analysis.get("summary"),
            structured=json.dumps(analysis.get("structuredData") or {}),
            recording_url=artifact.get("recordingUrl") or msg.get("recordingUrl"),
            transcript=artifact.get("transcript") or msg.get("transcript"),
        )
        customer = db.get_customer(customer_id)
        if ended in ENDED_REASON_DISPOSITION and customer["status"] == "pending":
            db.set_status(customer_id, "unresolved", disposition=ENDED_REASON_DISPOSITION[ended])
        db.log_event(call_id, customer_id, "end-of-call", {"endedReason": ended,
                                                           "summary": analysis.get("summary")})

    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True, "razorpay": "test-mode" if razorpay_client.is_live() else "mock",
            "today": config.today().isoformat()}


@app.get("/api/state")
def state():
    return {"customers": db.list_customers(), "calls": db.list_calls(),
            "events": db.list_events(100), "razorpay_live": razorpay_client.is_live()}


STATIC = {"style.css": "text/css", "common.js": "text/javascript"}


@app.get("/static/{name}")
def static_file(name: str):
    if name not in STATIC:
        raise HTTPException(status_code=404)
    return FileResponse(config.ROOT / "web" / name, media_type=STATIC[name])


@app.get("/")
def dashboard():
    return FileResponse(config.ROOT / "web" / "dashboard.html")


# --- Browser calls (no phone number needed) -------------------------------------------

@app.get("/call")
def call_page():
    return FileResponse(config.ROOT / "web" / "call.html")


@app.get("/api/web-config")
def web_config():
    customers = [{"id": c["id"], "name": c["name"], "status": c["status"], "disposition": c["disposition"],
                  "persona": c["test_persona"], "pincode": c["pincode"], "plan": c["plan"],
                  "method": c["method"], "failure_reason": c["failure_reason"],
                  "total_due": c["amount_due"] + c["late_fee"]} for c in db.list_customers()]
    return {"publicKey": config.VAPI_PUBLIC_KEY, "assistantId": config.VAPI_ASSISTANT_ID,
            "merchant": config.MERCHANT_NAME, "customers": customers, **voices.catalogue()}


@app.get("/api/call-overrides/{customer_id}")
def web_call_overrides(customer_id: str, lang: str = "en", voice: str = ""):
    c = db.get_customer(customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="unknown customer")
    return call_overrides(c, lang, voice)


@app.post("/api/register-call")
async def register_web_call(request: Request):
    body = await request.json()
    if not db.get_customer(body.get("customer_id", "")):
        raise HTTPException(status_code=404, detail="unknown customer")
    db.register_call(body["call_id"], body["customer_id"])
    db.log_event(body["call_id"], body["customer_id"], "call-placed",
                 {"via": "browser", "lang": body.get("lang"), "voice": body.get("voice")})
    return {"ok": True}
