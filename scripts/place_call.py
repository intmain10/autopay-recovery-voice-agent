"""Place outbound recovery calls. Every call goes to TEST_PHONE_NUMBER -- never to record numbers.

  python -m scripts.place_call C001            # one customer
  python -m scripts.place_call --all           # all pending customers, one after another
  python -m scripts.place_call C003 --no-wait  # don't wait for the call to finish
  python -m scripts.place_call C001 --lang hi --voice diya   # Hindi, Diya's voice
"""
import argparse
import sys
import time

from app import config, db, policy, vapi_client
from app import voices
from app.assistant import call_overrides

TERMINAL = {"ended"}


def wait_for_end(call_id: str) -> dict:
    while True:
        c = vapi_client.get_call(call_id)
        if c.get("status") in TERMINAL:
            return c
        time.sleep(5)


def place(customer: dict, wait: bool, lang: str, voice: str) -> None:
    print(f"\n-> Calling as {customer['id']} {customer['name']}  ({customer['failure_reason']}, "
          f"Rs {customer['amount_due']:.0f})")
    lang, voice = voices.resolve(lang, voice)
    print(f"   Role-play: {customer['test_persona']}  (PIN code {customer['pincode']})")
    print(f"   Language: {voices.LANGUAGES[lang]['label']}  Voice: {voices.VOICES[voice]['label']}")
    res = vapi_client.create_call(config.VAPI_ASSISTANT_ID, config.VAPI_PHONE_NUMBER_ID,
                                  config.TEST_PHONE_NUMBER, customer["name"],
                                  call_overrides(customer, lang, voice))
    db.register_call(res["id"], customer["id"])
    db.log_event(res["id"], customer["id"], "call-placed", {"to": "TEST_PHONE_NUMBER"})
    print(f"   Vapi call id: {res['id']}")
    if wait:
        done = wait_for_end(res["id"])
        print(f"   Ended: {done.get('endedReason')}")
        summary = (done.get("analysis") or {}).get("summary")
        if summary:
            print(f"   Summary: {summary}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("customer_ids", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--lang", choices=list(voices.LANGUAGES), default="en")
    ap.add_argument("--voice", choices=list(voices.VOICES), default="",
                    help="defaults to the language's default voice")
    ap.add_argument("--ignore-hours", action="store_true",
                    help="Demo only: skip the 08:00-19:00 IST window check")
    args = ap.parse_args()

    missing = [k for k in ("VAPI_API_KEY", "VAPI_ASSISTANT_ID", "VAPI_PHONE_NUMBER_ID", "TEST_PHONE_NUMBER")
               if not getattr(config, k)]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}")
    if not args.ignore_hours and not policy.within_call_window(config.now_ist()):
        sys.exit("Outside the RBI Fair Practices calling window (08:00-19:00 IST). "
                 "Use --ignore-hours for a demo call to your own phone.")

    if args.all:
        targets = [c for c in db.list_customers() if c["status"] == "pending"]
    else:
        targets = [db.get_customer(i.upper()) for i in args.customer_ids]
        if not targets or None in targets:
            sys.exit("Pass valid customer ids (C001..C010) or --all. Did you run scripts.seed?")

    skipped = [c["id"] for c in targets if c["status"] == "dnc"]
    for c in targets:
        if c["status"] == "dnc":
            continue
        place(c, wait=not args.no_wait or len(targets) > 1, lang=args.lang, voice=args.voice)
    if skipped:
        print(f"\nSkipped (do-not-call): {', '.join(skipped)}")


if __name__ == "__main__":
    main()
