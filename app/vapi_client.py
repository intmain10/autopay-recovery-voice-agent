from __future__ import annotations

import httpx

from . import config

BASE = "https://api.vapi.ai"


def _headers() -> dict:
    if not config.VAPI_API_KEY:
        raise SystemExit("VAPI_API_KEY is not set in .env")
    return {"Authorization": f"Bearer {config.VAPI_API_KEY}"}


def _request(method: str, path: str, **kw) -> dict:
    r = httpx.request(method, BASE + path, headers=_headers(), timeout=30, **kw)
    if r.status_code >= 400:
        raise SystemExit(f"Vapi {method} {path} failed [{r.status_code}]: {r.text}")
    return r.json()


def upsert_assistant(body: dict, assistant_id: str = "") -> dict:
    if assistant_id:
        return _request("PATCH", f"/assistant/{assistant_id}", json=body)
    return _request("POST", "/assistant", json=body)


def create_call(assistant_id: str, phone_number_id: str, to_number: str, name: str,
                overrides: dict) -> dict:
    return _request("POST", "/call", json={
        "assistantId": assistant_id,
        "phoneNumberId": phone_number_id,
        "customer": {"number": to_number, "name": name},
        "assistantOverrides": overrides,
    })


def get_call(call_id: str) -> dict:
    return _request("GET", f"/call/{call_id}")
