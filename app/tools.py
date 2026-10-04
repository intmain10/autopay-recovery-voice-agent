"""Tool definitions (sent to Vapi) and their server-side handlers.

Design rule: the LLM never sees account details until verify_identity succeeds, and every
account tool re-checks verification server-side, so a prompt-injected or confused model
still can't leak data or take actions for an unverified caller.
"""
from __future__ import annotations

from datetime import date
from typing import Callable, Dict

from . import config, db, policy, razorpay_client

DISPOSITIONS = [
    "paid_via_link_sent", "retry_scheduled", "installment_plan", "autopay_setup_link_sent",
    "dispute_escalated", "escalated_other", "wrong_party", "verification_failed",
    "callback_requested", "refused", "do_not_call", "voicemail", "no_answer",
]

TOOL_SCHEMAS = [
    {
        "name": "verify_identity",
        "description": "Verify the caller is the account holder using the 6-digit PIN code of "
                       "their service address. Must succeed before discussing ANY account detail.",
        "parameters": {"type": "object", "properties": {
            "pincode": {"type": "string", "description": "6-digit PIN code spoken by the caller"}},
            "required": ["pincode"]},
    },
    {
        "name": "get_account_summary",
        "description": "Get the overdue amount, why AutoPay failed and which recovery options "
                       "this customer is eligible for. Call right after successful verification.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "send_payment_link",
        "description": "Send a one-time Razorpay payment link (UPI, cards, netbanking) so the "
                       "customer can pay immediately. Use for 'pay now' requests.",
        "parameters": {"type": "object", "properties": {
            "channel": {"type": "string", "enum": ["sms", "email", "both"]},
            "include_late_fee": {"type": "boolean",
                                 "description": "false only if the fee was waived"}},
            "required": ["channel"]},
    },
    {
        "name": "schedule_autopay_retry",
        "description": "Schedule the AutoPay debit to be retried on a date the customer agrees to. "
                       "Earliest is tomorrow (RBI 24h pre-debit notice), latest is 7 days out.",
        "parameters": {"type": "object", "properties": {
            "retry_date": {"type": "string", "description": "YYYY-MM-DD"}},
            "required": ["retry_date"]},
    },
    {
        "name": "send_autopay_setup_link",
        "description": "Send a link to set up AutoPay again (new card, new UPI ID or new bank "
                       "mandate). Use when the old mandate is expired, paused, cancelled or lost.",
        "parameters": {"type": "object", "properties": {
            "method": {"type": "string", "enum": ["upi", "card", "emandate"],
                       "description": "emandate = bank account mandate"}},
            "required": ["method"]},
    },
    {
        "name": "create_installment_plan",
        "description": "Split the balance into 2 or 3 installments 15 days apart. Only for "
                       "eligible balances. The first installment link is sent immediately.",
        "parameters": {"type": "object", "properties": {
            "installments": {"type": "integer", "description": "2 or 3"}},
            "required": ["installments"]},
    },
    {
        "name": "waive_late_fee",
        "description": "Apply a one-time late fee waiver, only if the customer asks and is eligible.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "escalate_to_human",
        "description": "Create a ticket for a human agent: billing disputes, fraud claims, "
                       "hardship, complaints, or the customer asks for a person. Pauses collection.",
        "parameters": {"type": "object", "properties": {
            "category": {"type": "string", "enum": ["dispute", "fraud", "hardship", "complaint", "other"]},
            "details": {"type": "string"}},
            "required": ["category", "details"]},
    },
    {
        "name": "record_do_not_call",
        "description": "Record that the customer asked not to be called again about this.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "log_call_outcome",
        "description": "Log the final disposition. Call exactly once, just before ending the call.",
        "parameters": {"type": "object", "properties": {
            "disposition": {"type": "string", "enum": DISPOSITIONS},
            "notes": {"type": "string", "description": "One-line summary"},
            "callback_time": {"type": "string", "description": "If a callback was requested"}},
            "required": ["disposition", "notes"]},
    },
]

# Tools callable before verification.
PRE_VERIFY_OK = {"verify_identity", "log_call_outcome"}

STATUS_FOR_DISPOSITION = {
    "paid_via_link_sent": "link_sent", "retry_scheduled": "promised",
    "installment_plan": "plan", "autopay_setup_link_sent": "link_sent",
    "dispute_escalated": "escalated", "escalated_other": "escalated",
    "do_not_call": "dnc",
}


class ToolError(Exception):
    pass


def _verify_identity(ctx, c, args):
    call = ctx["call"]
    if call["verified"]:
        return {"ok": True, "message": "Already verified."}
    if call["verify_attempts"] >= policy.MAX_VERIFY_ATTEMPTS:
        return {"ok": False, "locked": True,
                "message": "Verification locked. Do not disclose anything. Ask them to call "
                           f"{config.SUPPORT_NUMBER} and end the call politely."}
    attempts = call["verify_attempts"] + 1
    if policy.check_pincode(c["pincode"], args.get("pincode", "")):
        db.update_call(call["call_id"], verified=1, verify_attempts=attempts)
        return {"ok": True, "message": "Verified. Now call get_account_summary."}
    db.update_call(call["call_id"], verify_attempts=attempts)
    left = policy.MAX_VERIFY_ATTEMPTS - attempts
    if left <= 0:
        return {"ok": False, "locked": True,
                "message": "Verification failed twice. Do not disclose anything. Ask them to call "
                           f"{config.SUPPORT_NUMBER}, log 'verification_failed' and end the call."}
    return {"ok": False, "attempts_left": left,
            "message": "PIN code didn't match. Ask them to repeat it once more. Don't hint at the right one."}


def _account_summary(ctx, c, args):
    return {
        "ok": True,
        "plan": c["plan"],
        "amount_due": c["amount_due"],
        "late_fee": c["late_fee"],
        "total_due": policy.total_due(c),
        "currency": "INR",
        "due_date": c["due_date"],
        "due_date_spoken": policy.spoken_date(date.fromisoformat(c["due_date"])),
        "payment_method": c["method_label"],
        "failure_reason": policy.FAILURE_EXPLANATIONS[c["failure_reason"]],
        "eligible_options": policy.recovery_options(c),
        "today": ctx["today"].isoformat(),
        "next_7_days": policy.next_days(ctx["today"]),
    }


def _payment_link(ctx, c, args):
    channel = args.get("channel", "sms")
    include_fee = args.get("include_late_fee", True)
    if not include_fee and not c.get("fee_waived"):
        include_fee = True  # can't drop the fee unless waive_late_fee actually succeeded
    amount = policy.total_due(c, include_late_fee=include_fee)
    link = razorpay_client.create_payment_link(
        c, amount, f"{config.MERCHANT_NAME} - {c['plan']} overdue (due {c['due_date']})",
        reference_id=f"{c['id']}-{ctx['call']['call_id'][:24]}",
        notify_sms=channel in ("sms", "both"), notify_email=channel in ("email", "both"))
    db.set_status(c["id"], "link_sent")
    return {"ok": True, "amount": amount, "link_id": link["id"], "url": link["short_url"],
            "message": f"Payment link for Rs {amount:.2f} sent by {channel}. It's valid for 3 days. "
                       "Don't read the URL aloud; tell them to check their messages."}


def _schedule_retry(ctx, c, args):
    try:
        requested = date.fromisoformat(args.get("retry_date", ""))
    except ValueError:
        return {"ok": False, "message": "Need the date as YYYY-MM-DD. Confirm the date with the customer."}
    d = policy.schedule_retry(c, requested, ctx["today"])
    if d.ok:
        db.set_status(c["id"], "promised")
    return d.as_dict()


def _autopay_link(ctx, c, args):
    link = razorpay_client.create_mandate_link(c, args.get("method", "upi"))
    return {"ok": True, "url": link["short_url"],
            "message": "AutoPay setup link sent by SMS. Once they approve it in their UPI or bank "
                       "app, future bills debit automatically. The overdue amount still needs paying: "
                       "offer a payment link if not already sent."}


def _installment_plan(ctx, c, args):
    d = policy.installment_plan(c, int(args.get("installments", 0)), ctx["today"])
    if not d.ok:
        return d.as_dict()
    first = d.data["schedule"][0]["amount"]
    link = razorpay_client.create_payment_link(
        c, first, f"{config.MERCHANT_NAME} - installment 1 of {args['installments']}",
        reference_id=f"{c['id']}-plan-{ctx['call']['call_id'][:16]}", notify_sms=True, notify_email=False)
    db.set_status(c["id"], "plan")
    out = d.as_dict()
    out["first_installment_link"] = link["short_url"]
    return out


def _waive_fee(ctx, c, args):
    d = policy.fee_waiver(c)
    if d.ok:
        db.update_customer_data(c["id"], late_fee=0.0, fee_waived=True,
                                prior_fee_waivers=c["prior_fee_waivers"] + 1)
        d.data["new_total_due"] = c["amount_due"]
    return d.as_dict()


def _escalate(ctx, c, args):
    ticket = f"TKT-{c['id']}-{ctx['call']['call_id'][-6:]}".upper()
    db.set_status(c["id"], "escalated")
    msg = (f"Ticket {ticket} created. A specialist will call back within 24 hours. "
           "Collection is paused until then.")
    if config.HUMAN_TRANSFER_NUMBER:
        msg += " You may also offer a live transfer now."
    return {"ok": True, "ticket_id": ticket, "message": msg}


def _dnc(ctx, c, args):
    db.set_status(c["id"], "dnc", disposition="do_not_call")
    return {"ok": True, "message": "Recorded. Thank them, mention they can pay anytime in the app, and end."}


def _log_outcome(ctx, c, args):
    disp = args.get("disposition")
    if disp not in DISPOSITIONS:
        return {"ok": False, "message": f"disposition must be one of {DISPOSITIONS}"}
    if not ctx["call"]["verified"] and disp not in ("wrong_party", "verification_failed",
                                                    "callback_requested", "voicemail", "no_answer"):
        disp = "verification_failed"
    current = db.get_customer(c["id"])["status"]
    status = STATUS_FOR_DISPOSITION.get(disp, current if current != "pending" else "unresolved")
    db.set_status(c["id"], status, disposition=disp)
    db.update_call(ctx["call"]["call_id"], summary=args.get("notes"))
    return {"ok": True, "message": "Logged. Close the call politely now."}


HANDLERS: Dict[str, Callable] = {
    "verify_identity": _verify_identity,
    "get_account_summary": _account_summary,
    "send_payment_link": _payment_link,
    "schedule_autopay_retry": _schedule_retry,
    "send_autopay_setup_link": _autopay_link,
    "create_installment_plan": _installment_plan,
    "waive_late_fee": _waive_fee,
    "escalate_to_human": _escalate,
    "record_do_not_call": _dnc,
    "log_call_outcome": _log_outcome,
}


def run_tool(name: str, args: dict, call_id: str, customer_id: str) -> dict:
    if name not in HANDLERS:
        return {"ok": False, "message": f"Unknown tool {name}"}
    db.register_call(call_id, customer_id)
    call = db.get_call(call_id)
    c = db.get_customer(call["customer_id"])
    if c is None:
        return {"ok": False, "message": "Customer record not found. Apologise and end the call."}
    if name not in PRE_VERIFY_OK and not call["verified"]:
        result = {"ok": False, "message": "Caller is not verified. Run verify_identity first and "
                                          "do not share any account details."}
    else:
        ctx = {"call": call, "today": config.today()}
        result = HANDLERS[name](ctx, c, args or {})
    db.log_event(call_id, c["id"], f"tool:{name}", {"args": args, "result": result})
    return result
