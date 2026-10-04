from datetime import date, datetime, time

from app import policy

TODAY = date(2026, 10, 4)


def cust(**kw):
    base = dict(amount_due=799.0, late_fee=0.0, failure_reason="insufficient_balance",
                tenure_months=10, prior_fee_waivers=0)
    base.update(kw)
    return base


def test_retry_needs_24h_pre_debit_notice():
    assert not policy.schedule_retry(cust(), TODAY, TODAY).ok
    assert policy.schedule_retry(cust(), date(2026, 10, 5), TODAY).ok


def test_retry_capped_at_7_days():
    assert policy.schedule_retry(cust(), date(2026, 10, 11), TODAY).ok
    assert not policy.schedule_retry(cust(), date(2026, 10, 12), TODAY).ok


def test_no_retry_on_dead_mandate():
    for r in ("card_expired", "mandate_revoked", "card_reported_lost"):
        assert not policy.schedule_retry(cust(failure_reason=r), date(2026, 10, 6), TODAY).ok


def test_installments_split_exactly():
    d = policy.installment_plan(cust(amount_due=4497.0, late_fee=150.0), 3, TODAY)
    assert d.ok and round(sum(p["amount"] for p in d.data["schedule"]), 2) == 4647.0
    assert [p["due"] for p in d.data["schedule"]] == ["2026-10-04", "2026-10-19", "2026-11-03"]
    assert not policy.installment_plan(cust(), 2, TODAY).ok


def test_fee_waiver_rules():
    assert policy.fee_waiver(cust(late_fee=100, tenure_months=52)).ok
    assert not policy.fee_waiver(cust(late_fee=100, tenure_months=12)).ok
    assert not policy.fee_waiver(cust(late_fee=100, tenure_months=52, prior_fee_waivers=1)).ok
    assert not policy.fee_waiver(cust(tenure_months=52)).ok


def test_calling_window():
    d = date(2026, 10, 4)
    assert policy.within_call_window(datetime.combine(d, time(8, 0)))
    assert not policy.within_call_window(datetime.combine(d, time(7, 59)))
    assert not policy.within_call_window(datetime.combine(d, time(19, 0)))


def test_pincode_tolerates_spoken_formatting():
    assert policy.check_pincode("560034", "5 6 0 0 3 4")
    assert not policy.check_pincode("560034", "560043")
