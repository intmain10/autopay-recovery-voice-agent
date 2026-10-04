# AutoPay Recovery Voice Agent

## 🎥 Demo

**Demo video:** _link coming soon_

End-to-end calls across English and Hindi, with the live dashboard updating as the agent verifies the
customer, explains the failed AutoPay and sends Razorpay payment / AutoPay setup links.

An outbound AI voice agent that calls customers whose **Razorpay AutoPay** (UPI AutoPay, card
mandate or NACH e-mandate) debit failed. It verifies who it's talking to, explains the failure,
and gets the payment back on track: an instant Razorpay Payment Link, a scheduled AutoPay retry,
a fresh mandate, or an installment plan. It escalates disputes to a human and respects do-not-call.

- **Voice stack:** Vapi (telephony + Deepgram `en-IN` speech-to-text + GPT-4o + Azure `en-IN` voice)
- **Backend:** FastAPI webhook running all business logic, SQLite state, live dashboard
- **Payments:** real Razorpay **test-mode** Payment Links API when keys are set, mock otherwise
- **Data:** 10 fictional customers in [`data/customers.json`](data/customers.json), each a different scenario
- **Safety:** every call goes to `TEST_PHONE_NUMBER` (your phone). Record numbers are never dialled.

```
 place_call.py ──POST /call──▶  Vapi  ◀──── voice ────▶  your phone (role-playing the customer)
                                 │
                     tool-calls / end-of-call webhooks
                                 ▼
                    FastAPI  app/server.py ──▶ tools.py ──▶ policy.py (rules)
                         │                         └──▶ razorpay_client.py ──▶ Razorpay test API
                         └── SQLite (customers, calls, audit log) ──▶ dashboard at  /
```

## The 10 scenarios

| ID | Customer | Failure | What the agent should do |
|---|---|---|---|
| C001 | Priya | UPI, insufficient balance | Wants "retry now": explain the RBI 24h rule, send a payment link |
| C002 | Rahul | Card expired | Stop the customer reading out card details; send link + AutoPay setup link |
| C003 | Ananya | e-mandate, ₹4,647 quarterly | Waive the late fee (eligible), 3-part installment plan |
| C004 | Arjun | UPI, insufficient balance | Asks for end of month: cap at 7 days, schedule retry on the 7th |
| C005 | Fatima | Bank declined | Disputes a double charge: escalate to a human, no pressure |
| C006 | Vikram | — | Brother answers: wrong party, disclose **nothing** |
| C007 | Sneha | Mandate paused | Wrong PIN code twice: lock and reveal nothing |
| C008 | Karthik | Mandate revoked | Can't retry: send link to set up AutoPay again + payment link |
| C009 | Meera | UPI, ₹100 late fee | 4+ year customer: waive the fee, link for ₹999 |
| C010 | Rohan | UPI | "Stop calling me": record do-not-call, end politely |

`place_call.py` prints the role-play script before each call so you know what to say.

## Setup (about 15 minutes)

```bash
cd autopay-voice-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

1. **Vapi:** create an account at dashboard.vapi.ai, copy your private API key, and buy or import a
   phone number (a free Vapi number works for US calls; for Indian numbers, import a Twilio or
   Vonage number). Put `VAPI_API_KEY`, `VAPI_PHONE_NUMBER_ID` and your own `TEST_PHONE_NUMBER` in `.env`.
2. **Razorpay (optional):** in the Razorpay dashboard switch to **Test Mode** → Account & Settings → API Keys.
   Put `rzp_test_...` keys in `.env`. With keys set, the agent creates real test Payment Links
   (they appear under Payment Links in the dashboard, and Razorpay sends the SMS/email).
3. **Run the server and expose it:**
   ```bash
   python -m scripts.seed
   uvicorn app.server:app --port 8000
   # in another terminal
   ngrok http 8000          # or: cloudflared tunnel --url http://localhost:8000
   ```
   Put the https URL in `PUBLIC_SERVER_URL`.
4. **Create the assistant:** `python -m scripts.setup_assistant`, then copy the printed ID into
   `VAPI_ASSISTANT_ID`. Re-run it after any prompt change; it updates the same assistant.

## Demo

```bash
open http://localhost:8000          # live dashboard: statuses + every tool call
python -m scripts.place_call C001   # one scenario
python -m scripts.place_call --all  # all 10, one after another
python -m scripts.report            # final outcome table
```

Calls are blocked outside **08:00–19:00 IST** (RBI Fair Practices Code for recovery calls). Add
`--ignore-hours` for a demo call to your own phone. Recordings, transcripts and Vapi's
structured analysis of each call are stored in the `calls` table and on the Vapi dashboard.

**Languages and voices.** Each call can run in English or Hindi, with a choice of voice:

| Language | Voices | Speech-to-text |
|---|---|---|
| English (Indian) | Naina, Aarti HD (female), Rohan (male) | Deepgram nova-2 `en-IN` |
| Hindi | Kavita, Diya, Esha (female), Amrit (male) — Cartesia native Hindi | Deepgram nova-3 `multi` (handles Hinglish) |

Pick them in the call console, or from the command line with
`python -m scripts.place_call C001 --lang hi --voice diya`. The agent's name, greeting, voicemail
and Hindi verb gender follow the chosen voice. Voices are defined in [`app/voices.py`](app/voices.py).

**No phone number? Call from the browser:** put your Vapi **public** key in `VAPI_PUBLIC_KEY`,
open http://localhost:8000/call, pick a customer and press *Start call*. It runs the same
assistant, tools and dashboard, using your mic and speakers instead of a phone line.

**Offline check (no keys, no phone):** `pytest -q` sends Vapi-format webhook payloads through the
real server and replays every scenario: 22 tests.

## Design decisions

- **The server enforces the rules, not the prompt.** Account tools refuse to run until
  `verify_identity` succeeds *for that call*. Verification locks after 2 failures. A model that's
  confused or manipulated still can't leak data, waive a fee it shouldn't, or log "paid" for an
  unverified caller (see `test_c007_*`).
- **Data minimisation.** The prompt only contains the customer's name. Amount, plan and failure
  reason reach the model only through `get_account_summary`, after verification.
- **No "retry now".** Under RBI's e-mandate rules, a recurring debit needs a pre-debit notice at
  least 24 hours ahead. So the agent never promises an instant retry: same-day recovery goes through
  a one-time Payment Link (UPI/cards/netbanking), and retries are scheduled 1–7 days out.
- **No card data on calls.** The agent never collects card numbers, CVV, OTP or UPI PIN. It stops
  the customer and sends a secure link instead. That keeps the voice pipeline out of PCI-DSS scope.
- **Respectful collection.** It always discloses that it's an AI and that the call is recorded. It
  never threatens (no legal, credit-score or disconnection talk). It escalates disputes and
  hardship to a human and honours do-not-call (`--all` skips DNC customers). Voicemails never
  mention money.
- **Policy lives in one place.** Thresholds (7-day promise, ₹2,000 plan minimum, 24-month waiver
  tenure, 2 verification attempts) are constants in [`app/policy.py`](app/policy.py) and unit tested.

## Limitations and what I'd do next

- **Mock pieces:** retry scheduling, the AutoPay re-registration link, tickets and the late-fee
  ledger are simulated. Razorpay's registration-link API (`/v1/subscription_registration/auth_links`)
  needs recurring payments enabled on the account. In production, retries would go through
  Razorpay Subscriptions / recurring-payment APIs, with `payment.failed` and `subscription.halted`
  webhooks *triggering* the calls instead of a manual script.
- **Payment confirmation:** the agent sends a link but doesn't confirm payment during the call.
  Next step: listen to Razorpay's `payment_link.paid` webhook so the agent can say "got it, thanks"
  live, and mark the customer recovered.
- **Language:** English (Indian accent) with light Hinglish. Full Hindi/regional support needs a
  multilingual voice and speech-to-text model; both are config changes (`VOICE_*`, transcriber).
- **Verification:** PIN code is a weak factor and fine for a demo. In production: verify via the
  registered number (caller ID match) plus an OTP sent by SMS, not spoken.
- **Single SQLite DB, no auth on the dashboard.** Fine for a demo. Use Postgres and authenticated
  admin access in production.
- **Consent and scale:** production would need a DND/NCPR scrub (TRAI), per-customer attempt
  limits, a calling queue with retry/backoff, and DLT-registered SMS templates for links.
