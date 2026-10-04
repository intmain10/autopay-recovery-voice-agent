"""Print the recovery outcome for every customer."""
from app import db, policy

if __name__ == "__main__":
    customers = db.list_customers()
    print(f"{'ID':5} {'Name':16} {'Failure':22} {'Due':>8}  {'Status':11} Disposition")
    print("-" * 90)
    for c in customers:
        print(f"{c['id']:5} {c['name']:16} {c['failure_reason']:22} {policy.total_due(c):>8.0f}  "
              f"{c['status']:11} {c['disposition'] or '-'}")
    total = sum(policy.total_due(c) for c in customers)
    actioned = [c for c in customers if c["status"] in ("link_sent", "promised", "plan")]
    print("-" * 90)
    print(f"Contacted with a recovery action: {len(actioned)}/{len(customers)}  "
          f"(Rs {sum(policy.total_due(c) for c in actioned):.0f} of Rs {total:.0f} at stake)")
