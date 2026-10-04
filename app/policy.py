"""Pure business rules for autopay recovery. No I/O -- easy to unit test.

India-specific constraints encoded here:
- RBI e-mandate framework: recurring debits on cards / UPI AutoPay need a pre-debit
  notification at least 24h before the debit, so an agent cannot "retry right now".
  Immediate recovery happens through a one-time Razorpay Payment Link instead.
- RBI Fair Practices Code for recovery: calls only between 08:00 and 19:00 local time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional

MAX_VERIFY_ATTEMPTS = 2
MAX_PROMISE_DAYS = 7
PLAN_MIN_AMOUNT = 2000.0
PLAN_INSTALLMENT_GAP_DAYS = 15
FEE_WAIVER_MIN_TENURE = 24
CALL_WINDOW = (time(8, 0), time(19, 0))

# Failure reasons where the existing mandate can't be debited again.
DEAD_MANDATE = {"card_expired", "mandate_revoked", "card_reported_lost"}

FAILURE_EXPLANATIONS = {
    "insufficient_balance": "the bank declined the AutoPay debit due to insufficient balance",
    "card_expired": "the card on the mandate has expired",
    "bank_declined": "the issuing bank declined the debit without a specific reason",
    "mandate_paused": "the UPI AutoPay mandate was paused from the customer's UPI app",
    "mandate_revoked": "the AutoPay mandate was cancelled at the bank",
    "card_reported_lost": "the card on the mandate was reported lost",
}


@dataclass
class Decision:
    ok: bool
    message: str
    data: Optional[dict] = None

    def as_dict(self) -> dict:
        out = {"ok": self.ok, "message": self.message}
        if self.data:
            out.update(self.data)
        return out


def spoken_date(d: date) -> str:
    """'Wednesday, 7 October' -- weekday computed here so the LLM never guesses it."""
    return f"{d:%A}, {d.day} {d:%B}"


def next_days(today: date, n: int = MAX_PROMISE_DAYS) -> list:
    return [{"date": (today + timedelta(days=i)).isoformat(), "spoken": spoken_date(today + timedelta(days=i))}
            for i in range(1, n + 1)]


def within_call_window(now: datetime) -> bool:
    return CALL_WINDOW[0] <= now.time() < CALL_WINDOW[1]


def check_pincode(expected: str, given: str) -> bool:
    digits = "".join(ch for ch in str(given) if ch.isdigit())
    return digits == expected


def total_due(c: dict, include_late_fee: bool = True) -> float:
    return round(c["amount_due"] + (c["late_fee"] if include_late_fee else 0.0), 2)


def recovery_options(c: dict) -> list:
    opts = ["pay_now_via_link"]
    if c["failure_reason"] not in DEAD_MANDATE:
        opts.append("schedule_autopay_retry")
    if c["failure_reason"] in DEAD_MANDATE | {"mandate_paused"}:
        opts.append("set_up_autopay_again")
    if total_due(c) >= PLAN_MIN_AMOUNT:
        opts.append("installment_plan")
    if fee_waiver(c).ok:
        opts.append("late_fee_waiver")
    return opts


def schedule_retry(c: dict, requested: date, today: date) -> Decision:
    if c["failure_reason"] in DEAD_MANDATE:
        return Decision(False, f"Cannot retry: {FAILURE_EXPLANATIONS[c['failure_reason']]}. "
                               "Offer a payment link and AutoPay re-setup instead.")
    earliest = today + timedelta(days=1)
    latest = today + timedelta(days=MAX_PROMISE_DAYS)
    if requested < earliest:
        return Decision(False, "RBI rules need a pre-debit notice 24 hours before an AutoPay debit, "
                               f"so the earliest retry is {spoken_date(earliest)}. For paying today, "
                               "offer the payment link.", {"earliest_date": earliest.isoformat()})
    if requested > latest:
        return Decision(False, f"Policy allows retries up to {MAX_PROMISE_DAYS} days out "
                               f"(latest {spoken_date(latest)}). Offer that date or an installment plan.",
                        {"latest_date": latest.isoformat()})
    note = ""
    if c["failure_reason"] == "mandate_paused":
        note = " Remind the customer to resume the mandate in their UPI app before that date."
    return Decision(True, f"Retry scheduled for {spoken_date(requested)}. A pre-debit notification "
                          f"will be sent 24 hours before.{note}",
                    {"retry_date": requested.isoformat(), "retry_date_spoken": spoken_date(requested),
                     "amount": total_due(c)})


def installment_plan(c: dict, installments: int, today: date) -> Decision:
    amount = total_due(c)
    if amount < PLAN_MIN_AMOUNT:
        return Decision(False, f"Installment plans need a balance of at least Rs {PLAN_MIN_AMOUNT:.0f}.")
    if installments not in (2, 3):
        return Decision(False, "Plans can be 2 or 3 installments only.")
    base = round(amount / installments, 2)
    parts = [base] * (installments - 1) + [round(amount - base * (installments - 1), 2)]
    schedule = [
        {"n": i + 1, "amount": p,
         "due": (today + timedelta(days=PLAN_INSTALLMENT_GAP_DAYS * i)).isoformat(),
         "due_spoken": "today" if i == 0 else spoken_date(today + timedelta(days=PLAN_INSTALLMENT_GAP_DAYS * i))}
        for i, p in enumerate(parts)
    ]
    return Decision(True, f"{installments}-part plan created. First installment of Rs {parts[0]:.2f} "
                          "is due today via payment link.", {"schedule": schedule})


def fee_waiver(c: dict) -> Decision:
    if c["late_fee"] <= 0:
        return Decision(False, "There is no late fee on this account.")
    if c["tenure_months"] < FEE_WAIVER_MIN_TENURE:
        return Decision(False, f"Waivers need {FEE_WAIVER_MIN_TENURE}+ months of tenure.")
    if c["prior_fee_waivers"] > 0:
        return Decision(False, "A late fee waiver was already used on this account.")
    return Decision(True, f"Late fee of Rs {c['late_fee']:.2f} waived as a one-time courtesy.",
                    {"waived": c["late_fee"]})
