import os
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DEMO_TODAY"] = "2026-10-04"
os.environ["VAPI_WEBHOOK_SECRET"] = "test-secret"
os.environ["RAZORPAY_KEY_ID"] = ""
os.environ["RAZORPAY_KEY_SECRET"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.server import app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    db.reset_and_seed()


@pytest.fixture
def client():
    return TestClient(app)


class Call:
    """Drives one simulated Vapi call through the real webhook."""
    n = 0

    def __init__(self, client, customer_id):
        Call.n += 1
        self.client, self.customer_id = client, customer_id
        self.id = f"call-{customer_id}-{Call.n}"
        db.register_call(self.id, customer_id)

    def tool(self, name, **args):
        body = {"message": {"type": "tool-calls", "call": {"id": self.id},
                            "toolCallList": [{"id": "tc1", "type": "function",
                                              "function": {"name": name, "arguments": args}}]}}
        r = self.client.post("/vapi/webhook", json=body, headers={"x-vapi-secret": "test-secret"})
        assert r.status_code == 200
        import json
        return json.loads(r.json()["results"][0]["result"])

    def end(self, reason="customer-ended-call"):
        body = {"message": {"type": "end-of-call-report", "call": {"id": self.id}, "endedReason": reason,
                            "analysis": {"summary": "test", "structuredData": {}}}}
        self.client.post("/vapi/webhook", json=body, headers={"x-vapi-secret": "test-secret"})


@pytest.fixture
def call(client):
    return lambda cid: Call(client, cid)
