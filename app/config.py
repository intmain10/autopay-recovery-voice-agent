from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

IST = timezone(timedelta(hours=5, minutes=30))

MERCHANT_NAME = os.getenv("MERCHANT_NAME", "BrightNet Fiber")
SUPPORT_NUMBER = os.getenv("SUPPORT_NUMBER", "1800 000 0000")

DB_PATH = Path(os.getenv("DB_PATH", ROOT / "data" / "state.db"))
CUSTOMERS_PATH = ROOT / "data" / "customers.json"

# Vapi
VAPI_API_KEY = os.getenv("VAPI_API_KEY", "")
VAPI_PUBLIC_KEY = os.getenv("VAPI_PUBLIC_KEY", "")  # browser calls only; safe to expose
VAPI_PHONE_NUMBER_ID = os.getenv("VAPI_PHONE_NUMBER_ID", "")
VAPI_ASSISTANT_ID = os.getenv("VAPI_ASSISTANT_ID", "")
VAPI_WEBHOOK_SECRET = os.getenv("VAPI_WEBHOOK_SECRET", "")
PUBLIC_SERVER_URL = os.getenv("PUBLIC_SERVER_URL", "").rstrip("/")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")
HUMAN_TRANSFER_NUMBER = os.getenv("HUMAN_TRANSFER_NUMBER", "")

# The ONLY number the dialer will ever call. Must be a number you control.
TEST_PHONE_NUMBER = os.getenv("TEST_PHONE_NUMBER", "")

# Razorpay (test mode). Leave blank to use the built-in mock.
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")


def today() -> date:
    """Business date in IST. DEMO_TODAY=YYYY-MM-DD pins it for reproducible demos/tests."""
    pinned = os.getenv("DEMO_TODAY")
    if pinned:
        return date.fromisoformat(pinned)
    return datetime.now(IST).date()


def now_ist() -> datetime:
    return datetime.now(IST)
