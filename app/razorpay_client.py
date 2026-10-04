"""Thin Razorpay wrapper. Uses the real test-mode API when keys are set, otherwise a mock.

Real endpoint used: POST https://api.razorpay.com/v1/payment_links
"""
from __future__ import annotations

import secrets
import time

import httpx

from . import config


def is_live() -> bool:
    return bool(config.RAZORPAY_KEY_ID and config.RAZORPAY_KEY_SECRET)


def create_payment_link(customer: dict, amount_inr: float, description: str,
                        reference_id: str, notify_sms: bool, notify_email: bool) -> dict:
    if not is_live():
        token = secrets.token_urlsafe(6)
        return {"id": f"plink_mock_{token}", "short_url": f"https://rzp.io/mock/{token}",
                "amount": amount_inr, "mock": True}

    payload = {
        "amount": int(round(amount_inr * 100)),  # paise
        "currency": "INR",
        "description": description[:2048],
        "reference_id": reference_id[:40],
        "expire_by": int(time.time()) + 3 * 24 * 3600,
        "customer": {"name": customer["name"], "email": customer["email"],
                     "contact": config.TEST_PHONE_NUMBER or None},
        "notify": {"sms": notify_sms, "email": notify_email},
        "reminder_enable": True,
        "notes": {"customer_id": customer["id"], "source": "autopay-voice-agent"},
    }
    resp = httpx.post("https://api.razorpay.com/v1/payment_links", json=payload,
                      auth=(config.RAZORPAY_KEY_ID, config.RAZORPAY_KEY_SECRET), timeout=15)
    resp.raise_for_status()
    body = resp.json()
    return {"id": body["id"], "short_url": body["short_url"], "amount": amount_inr, "mock": False}


def create_mandate_link(customer: dict, method: str) -> dict:
    """AutoPay re-registration link.

    Mocked: Razorpay's registration-link API (/v1/subscription_registration/auth_links)
    needs recurring payments enabled on the merchant account, which test accounts
    don't have by default. See README > Limitations.
    """
    token = secrets.token_urlsafe(6)
    return {"id": f"inv_mock_{token}", "short_url": f"https://rzp.io/mock/autopay-{token}",
            "method": method, "mock": True}
