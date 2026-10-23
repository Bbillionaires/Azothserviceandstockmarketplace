"""Match the payment provider's balance activity against our records.

Charges ↔ paid orders (amount and processing fee), refunds ↔ recorded refunds
(per payment), transfers ↔ sent payouts. Activity from the last few minutes is
skipped on the "missing locally" side because its webhook may still be in
flight.
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, OrderStatus, Payout, PayoutStatus, Refund
from app.services.payments import PaymentProvider, PaymentProviderError

GRACE_SECONDS = 600


def compare(db: Session, provider: PaymentProvider, since: datetime, until: datetime | None = None) -> list[dict]:
    until = until or datetime.now(UTC)
    s, u = int(since.timestamp()), int(until.timestamp())
    try:
        activity = provider.balance_activity(s - 86_400, u + 1)
    except PaymentProviderError as exc:
        return [{"check": "provider_matches", "error": f"could not read provider activity: {exc}"}]
    findings: list[dict] = []
    settled_before = int(time.time()) - GRACE_SECONDS

    charges = {a.payment_id: a for a in activity if a.type == "charge" and a.payment_id}
    provider_refunds: dict[str, int] = defaultdict(int)
    for a in activity:
        if a.type == "refund" and a.payment_id:
            provider_refunds[a.payment_id] += a.amount_cents
    transfers = {a.transfer_id: a for a in activity if a.type == "transfer" and a.transfer_id}

    orders = db.scalars(select(Order).where(Order.provider == provider.name, Order.paid_at.is_not(None),
                                            Order.status != OrderStatus.pending)).all()
    by_payment = {o.provider_payment_id: o for o in orders if o.provider_payment_id}
    for o in orders:
        paid = o.paid_at.replace(tzinfo=UTC) if o.paid_at.tzinfo is None else o.paid_at
        if not since <= paid < until:
            continue
        a = charges.get(o.provider_payment_id)
        if not a:
            findings.append({"check": "provider_matches", "issue": "charge_missing_at_provider", "order": str(o.id)})
            continue
        if a.amount_cents != o.total_cents:
            findings.append({"check": "provider_matches", "issue": "charge_amount_mismatch", "order": str(o.id),
                             "provider": a.amount_cents, "local": o.total_cents})
        if a.fee_cents != o.processing_fee_cents:
            findings.append({"check": "provider_matches", "issue": "fee_mismatch", "order": str(o.id),
                             "provider": a.fee_cents, "local": o.processing_fee_cents})
    for pid, a in charges.items():
        if s <= a.created < min(u, settled_before) and pid not in by_payment:
            findings.append({"check": "provider_matches", "issue": "charge_missing_locally", "payment": pid,
                             "amount": a.amount_cents})

    local_refunds: dict[str, int] = defaultdict(int)
    for r in db.scalars(select(Refund)):
        order = db.get(Order, r.order_id)
        if order and order.provider == provider.name and order.provider_payment_id:
            local_refunds[order.provider_payment_id] += r.amount_cents
    for pid in set(provider_refunds) | {p for p, v in local_refunds.items() if v and p in charges}:
        if provider_refunds.get(pid, 0) != local_refunds.get(pid, 0):
            findings.append({"check": "provider_matches", "issue": "refund_total_mismatch", "payment": pid,
                             "provider": provider_refunds.get(pid, 0), "local": local_refunds.get(pid, 0)})

    payouts = db.scalars(select(Payout).where(Payout.status.in_([PayoutStatus.sent, PayoutStatus.reversed]),
                                              Payout.provider_transfer_id.is_not(None))).all()
    known = {p.provider_transfer_id for p in payouts}
    for p in payouts:
        sent = p.sent_at.replace(tzinfo=UTC) if p.sent_at and p.sent_at.tzinfo is None else p.sent_at
        if sent and since <= sent < until:
            a = transfers.get(p.provider_transfer_id)
            if not a:
                findings.append({"check": "provider_matches", "issue": "transfer_missing_at_provider",
                                 "payout": str(p.id)})
            elif a.amount_cents != p.amount_cents:
                findings.append({"check": "provider_matches", "issue": "transfer_amount_mismatch",
                                 "payout": str(p.id), "provider": a.amount_cents, "local": p.amount_cents})
    for tid, a in transfers.items():
        if s <= a.created < min(u, settled_before) and tid not in known:
            findings.append({"check": "provider_matches", "issue": "transfer_missing_locally", "transfer": tid,
                             "amount": a.amount_cents})
    return findings
