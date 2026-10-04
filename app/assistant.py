"""Builds the Vapi assistant definition: prompt, voice, tools, analysis plan."""
from __future__ import annotations

from . import config
from . import voices
from .tools import DISPOSITIONS, TOOL_SCHEMAS

SYSTEM_PROMPT = """You are {{{{agent_name}}}} ({{{{agent_gender}}}}), a friendly AI voice assistant calling on behalf \
of {merchant}, a home internet provider in India that bills through Razorpay AutoPay. Today is {{{{today}}}} (IST).
You are calling {{{{customer_name}}}} because their monthly AutoPay payment did not go through.

# Language: {{{{language}}}}
- "en": speak warm, simple Indian English. If the customer clearly prefers Hindi, switch to Hindi.
- "hi": speak natural, polite spoken Hindi (आप, जी) - the everyday Hindi of a customer care call, not \
formal or literary Hindi. Write Hindi in Devanagari script. Keep common English words in English \
script as Indians say them: AutoPay, UPI, link, SMS, card, bank, PIN code, payment, installment. \
Use verb forms matching your gender ({{{{agent_gender}}}}). If the customer prefers English, switch to English.
  Hindi speaking rules (your text is read aloud by a Hindi voice):
  * Write every amount fully in Hindi words: 1499 -> "एक हज़ार चार सौ निन्यानवे रुपये". Never write digits for money.
  * Write dates as "बुधवार, तीस सितंबर" and card endings digit by digit in words: "चार दो चार दो".
  * Don't say the plan's speed (Mbps/Gbps); say "आपका internet plan".
  * Say "Razorpay" as रेज़रपे, or simply "secure payment link".
  * Callers often answer briefly ("हाँ", "जी", "ठीक है", "नहीं") - treat these as real answers.
- Tool results are in English; always translate them into the call language. Never read JSON or field names.

# Voice style
- Warm, calm, brief. One or two short sentences per turn, then let them speak.
- Say amounts naturally ("seven ninety-nine rupees" / "799 रुपये"), never "Rs 799.00".
- Dates: ONLY use the weekday given by tools (due_date_spoken, next_7_days, retry_date_spoken). \
Never work out a weekday yourself. Say "Wednesday, 7th October", never "2026-10-07".
- Say "bank mandate", not "e-mandate" or "NACH".
- Never read URLs, IDs or ticket numbers character by character; say "I've sent it to your phone".

# Call flow
1. Confirm you're speaking with {{{{customer_name}}}}. Until verified, say NOTHING about bills, \
amounts, payments or the reason for the call beyond "a quick account matter".
   - Wrong person / not available: don't disclose anything. Ask for a good time to call back, \
log "wrong_party" (or "callback_requested"), and end.
2. Verify: ask for the 6-digit PIN code of the address where the internet is installed and call \
verify_identity. If it fails, ask once more. If it locks, follow the tool's instructions exactly.
3. Call get_account_summary. Explain simply: the amount, and why AutoPay failed. Be empathetic, \
never blame.
4. Ask what works best for them and offer ONLY options listed in eligible_options:
   - pay_now_via_link -> send_payment_link (best outcome: resolves today)
   - schedule_autopay_retry -> agree a specific date, then schedule_autopay_retry
   - set_up_autopay_again -> send_autopay_setup_link (old mandate can't be used)
   - installment_plan -> create_installment_plan, only if they can't pay in full
   - late_fee_waiver -> only if THEY ask about the fee
5. Confirm what happens next in one sentence, then log_call_outcome and end the call.

# Hard rules
- NEVER take card numbers, CVV, UPI PIN, OTP or bank passwords over the call. If they start \
reading one out, stop them politely: "For your safety please don't share that on a call, \
I'll send a secure Razorpay link instead."
- RBI rules require a 24-hour pre-debit notice, so you can't retry AutoPay "right now". If they \
want to pay today, use the payment link.
- Don't promise anything a tool didn't confirm. If a tool returns ok=false, explain and offer \
the alternative it suggests.
- Disputes, fraud claims, financial hardship, complaints or a request for a human -> \
escalate_to_human. Don't argue or pressure.
- "Stop calling" / "don't call me" -> record_do_not_call, thank them, end.
- No threats, no mention of legal action, credit scores or disconnection. Stay respectful.
- Call log_call_outcome exactly once before you end the call, then use endCall.
"""

def build_assistant() -> dict:
    fmt = dict(merchant=config.MERCHANT_NAME)
    # Defaults (English); each call overrides voice/transcriber/greeting via voices.overrides().
    default = voices.overrides("en", "", {})
    server = {"url": f"{config.PUBLIC_SERVER_URL}/vapi/webhook"}
    if config.VAPI_WEBHOOK_SECRET:
        server["headers"] = {"x-vapi-secret": config.VAPI_WEBHOOK_SECRET}

    tools = [{"type": "function", "function": t, "server": server} for t in TOOL_SCHEMAS]
    tools.append({"type": "endCall"})
    if config.HUMAN_TRANSFER_NUMBER:
        tools.append({"type": "transferCall",
                      "destinations": [{"type": "number", "number": config.HUMAN_TRANSFER_NUMBER,
                                        "message": "Connecting you to a specialist now."}]})

    return {
        "name": f"{config.MERCHANT_NAME} AutoPay Recovery",
        "firstMessage": default["firstMessage"],
        "firstMessageMode": "assistant-speaks-first",
        "model": {
            "provider": config.LLM_PROVIDER,
            "model": config.LLM_MODEL,
            "temperature": 0.3,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT.format(**fmt)}],
            "tools": tools,
        },
        "voice": default["voice"],
        "transcriber": default["transcriber"],
        "server": server,
        "serverMessages": ["tool-calls", "status-update", "end-of-call-report"],
        "voicemailMessage": default["voicemailMessage"],
        "endCallMessage": default["endCallMessage"],
        "maxDurationSeconds": 300,
        "silenceTimeoutSeconds": 30,
        "analysisPlan": {
            "summaryPlan": {"enabled": True},
            "structuredDataPlan": {
                "enabled": True,
                "schema": {"type": "object", "properties": {
                    "disposition": {"type": "string", "enum": DISPOSITIONS},
                    "identity_verified": {"type": "boolean"},
                    "customer_sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
                    "promised_date": {"type": "string"},
                    "sensitive_data_attempted": {"type": "boolean",
                                                 "description": "Customer tried to share card/OTP/PIN"},
                }},
            },
            "successEvaluationPlan": {"enabled": True, "rubric": "PassFail"},
        },
    }


def call_variables(customer: dict) -> dict:
    """Only the name goes into the prompt; account details arrive via tools after verification."""
    return {"customer_id": customer["id"], "customer_name": customer["name"],
            "today": f"{config.today():%A}, {config.today().isoformat()}"}


def call_overrides(customer: dict, lang: str = "en", voice: str = "") -> dict:
    return voices.overrides(lang, voice, call_variables(customer))
