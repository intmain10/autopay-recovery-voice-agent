"""One test per fictional customer, mirroring the role-play script in customers.json."""
from app import db


def status(cid):
    c = db.get_customer(cid)
    return c["status"], c["disposition"]


def test_webhook_rejects_bad_secret(client):
    r = client.post("/vapi/webhook", json={"message": {"type": "tool-calls"}}, headers={"x-vapi-secret": "nope"})
    assert r.status_code == 401


def test_account_tools_blocked_until_verified(call):
    c = call("C001")
    r = c.tool("get_account_summary")
    assert not r["ok"] and "799" not in str(r)
    assert not c.tool("send_payment_link", channel="sms")["ok"]


def test_c001_wants_retry_now_gets_link(call):
    c = call("C001")
    assert c.tool("verify_identity", pincode="560034")["ok"]
    s = c.tool("get_account_summary")
    assert s["total_due"] == 799.0 and "schedule_autopay_retry" in s["eligible_options"]
    assert not c.tool("schedule_autopay_retry", retry_date="2026-10-04")["ok"]  # RBI 24h notice
    r = c.tool("send_payment_link", channel="sms")
    assert r["ok"] and r["url"].startswith("https://rzp.io/")
    c.tool("log_call_outcome", disposition="paid_via_link_sent", notes="paying via link")
    assert status("C001") == ("link_sent", "paid_via_link_sent")


def test_c002_expired_card(call):
    c = call("C002")
    c.tool("verify_identity", pincode="400050")
    assert "schedule_autopay_retry" not in c.tool("get_account_summary")["eligible_options"]
    assert not c.tool("schedule_autopay_retry", retry_date="2026-10-06")["ok"]
    assert c.tool("send_payment_link", channel="sms")["ok"]
    assert c.tool("send_autopay_setup_link", method="card")["ok"]


def test_c003_fee_waiver_then_installments(call):
    c = call("C003")
    c.tool("verify_identity", pincode="600020")
    s = c.tool("get_account_summary")
    assert {"installment_plan", "late_fee_waiver"} <= set(s["eligible_options"])
    assert c.tool("waive_late_fee")["new_total_due"] == 4497.0
    assert not c.tool("waive_late_fee")["ok"]  # one-time only
    r = c.tool("create_installment_plan", installments=3)
    assert r["ok"] and r["schedule"][0]["amount"] == 1499.0
    c.tool("log_call_outcome", disposition="installment_plan", notes="3 parts")
    assert status("C003") == ("plan", "installment_plan")


def test_c004_promise_capped_at_7_days(call):
    c = call("C004")
    c.tool("verify_identity", pincode="500081")
    r = c.tool("schedule_autopay_retry", retry_date="2026-10-31")
    assert not r["ok"] and r["latest_date"] == "2026-10-11"
    assert c.tool("schedule_autopay_retry", retry_date="2026-10-07")["ok"]
    c.tool("log_call_outcome", disposition="retry_scheduled", notes="salary on 7th")
    assert status("C004") == ("promised", "retry_scheduled")


def test_c005_dispute_escalates(call):
    c = call("C005")
    c.tool("verify_identity", pincode="110025")
    r = c.tool("escalate_to_human", category="dispute", details="double charged last month")
    assert r["ok"] and r["ticket_id"].startswith("TKT-C005")
    c.tool("log_call_outcome", disposition="dispute_escalated", notes="double charge")
    assert status("C005") == ("escalated", "dispute_escalated")


def test_c006_wrong_party_discloses_nothing(call):
    c = call("C006")
    c.tool("log_call_outcome", disposition="wrong_party", notes="brother answered")
    assert status("C006") == ("unresolved", "wrong_party")


def test_c007_locks_after_two_wrong_pincodes(call):
    c = call("C007")
    assert c.tool("verify_identity", pincode="411001")["attempts_left"] == 1
    assert c.tool("verify_identity", pincode="411001")["locked"]
    assert c.tool("verify_identity", pincode="411038")["locked"]  # correct, but too late
    assert not c.tool("get_account_summary")["ok"]
    # a confused model can't log a success disposition for an unverified caller
    c.tool("log_call_outcome", disposition="paid_via_link_sent", notes="?")
    assert status("C007") == ("unresolved", "verification_failed")


def test_c008_revoked_mandate(call):
    c = call("C008")
    c.tool("verify_identity", pincode="682024")
    s = c.tool("get_account_summary")
    assert "set_up_autopay_again" in s["eligible_options"] and "late_fee_waiver" not in s["eligible_options"]
    assert not c.tool("schedule_autopay_retry", retry_date="2026-10-05")["ok"]
    assert c.tool("send_autopay_setup_link", method="emandate")["ok"]
    assert c.tool("send_payment_link", channel="email")["ok"]


def test_c009_waiver_then_link_for_reduced_amount(call):
    c = call("C009")
    c.tool("verify_identity", pincode="380015")
    assert c.tool("waive_late_fee")["ok"]
    assert c.tool("send_payment_link", channel="sms", include_late_fee=False)["amount"] == 999.0


def test_fee_cannot_be_dropped_without_waiver(call):
    c = call("C003")
    c.tool("verify_identity", pincode="600020")
    assert c.tool("send_payment_link", channel="sms", include_late_fee=False)["amount"] == 4647.0


def test_c010_do_not_call(call):
    c = call("C010")
    c.tool("verify_identity", pincode="700091")
    assert c.tool("record_do_not_call")["ok"]
    c.tool("log_call_outcome", disposition="do_not_call", notes="will pay in app")
    assert status("C010") == ("dnc", "do_not_call")


def test_voicemail_end_of_call_report(call):
    c = call("C002")
    c.end(reason="voicemail")
    assert status("C002") == ("unresolved", "voicemail")


def test_web_call_resolves_customer_from_variables(client):
    body = {"message": {"type": "tool-calls",
                        "call": {"id": "web-1", "assistantOverrides": {"variableValues": {"customer_id": "C009"}}},
                        "toolCallList": [{"id": "t", "function": {"name": "verify_identity",
                                                                  "arguments": '{"pincode": "380015"}'}}]}}
    r = client.post("/vapi/webhook", json=body, headers={"x-vapi-secret": "test-secret"})
    assert '"ok": true' in r.json()["results"][0]["result"]
