"""Earnings release, payouts (Stripe transfers) and reconciliation.

Run daily (Railway cron: ``python -m app.cli run-finance``):

1. ``release_earnings``  pending → available once the hold period has passed.
2. ``run_payouts``       for each payee with an enabled payout account and an
                         available balance ≥ the minimum, record the payout and
                         ledger journal *first*, then call the provider with a
                         stable idempotency key. A crash between the two is
                         safe: the next run retries the same key.
3. ``cancel_stale_orders`` and ``reconcile``.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Earning,
    EarningKind,
    EarningStatus,
    FinancialEvent,
    JournalKind,
    LedgerAccount,
    LedgerJournal,
    Order,
    OrderLine,
    OrderLineStatus,
    OrderStatus,
    Payout,
    PayoutAccount,
    PayoutAccountStatus,
    PayoutStatus,
    ReconciliationRun,
    RightsGrant,
    RoyaltyAllocation,
)
from app.services import audit, ledger
from app.services.payment_service import utcnow
from app.services.payments import PaymentProvider, PaymentProviderError

log = logging.getLogger("payouts")

PAYABLE_PREFIX = {EarningKind.stock_license: "creator_payable", EarningKind.affiliate_commission: "affiliate_payable"}


def release_earnings(db: Session) -> int:
    rows = db.scalars(select(Earning).where(Earning.status == EarningStatus.pending, Earning.available_at <= utcnow())).all()
    for e in rows:
        e.status = EarningStatus.available
    db.flush()
    return len(rows)


def _send(db: Session, provider: PaymentProvider, payout: Payout, account: PayoutAccount) -> None:
    try:
        transfer_id = provider.transfer(
            amount_cents=payout.amount_cents, currency=payout.currency, destination=account.provider_account_id,
            idempotency_key=payout.idempotency_key, description=f"Marketplace earnings payout {payout.id}",
            metadata={"payout_id": str(payout.id), "user_id": str(payout.payee_user_id)},
        )
    except PaymentProviderError as exc:
        _fail(db, payout, str(exc))
        return
    payout.status, payout.provider_transfer_id, payout.sent_at = PayoutStatus.sent, transfer_id, utcnow()
    audit.record(db, "payout.sent", None, "payout", payout.id, amount=payout.amount_cents, transfer=transfer_id)


def _fail(db: Session, payout: Payout, reason: str, final_status: PayoutStatus = PayoutStatus.failed) -> None:
    """Return a payout's money to the payee's payable balance and free its earnings."""
    journal = db.get(LedgerJournal, payout.journal_id)
    ledger.post(db, JournalKind.payout_reversal, f"payout-return:{payout.id}", "payout", payout.id,
                f"Payout {payout.id} returned", payout.currency,
                [ledger.Line(e.account.code, debit=e.credit_cents, credit=e.debit_cents, memo=reason[:200],
                             owner_user_id=e.account.owner_user_id) for e in journal.entries])
    for e in db.scalars(select(Earning).where(Earning.payout_id == payout.id)):
        e.status, e.payout_id = EarningStatus.available, None
    payout.status = final_status
    payout.failure_reason = reason[:2000]
    audit.record(db, "payout.returned", None, "payout", payout.id, reason=reason[:200])


PAYOUT_LOCK_ID = 7_310_442  # arbitrary constant for the PostgreSQL advisory lock


def run_payouts(db: Session, provider: PaymentProvider) -> dict:
    """Serialized: a second concurrent run (cron + admin click) returns
    immediately instead of paying the same earnings twice."""
    if db.bind.dialect.name != "postgresql":
        return _run_payouts(db, provider)
    # The lock lives on its own connection: the session commits several times
    # and may hand back a different pooled connection after each commit.
    with db.bind.connect() as lock_conn:
        if not lock_conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": PAYOUT_LOCK_ID}):
            return {"busy": True}
        try:
            return _run_payouts(db, provider)
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": PAYOUT_LOCK_ID})
            lock_conn.commit()


def _run_payouts(db: Session, provider: PaymentProvider) -> dict:
    settings = get_settings()
    summary = {"released": release_earnings(db), "created": 0, "sent": 0, "failed": 0, "skipped": 0}

    # Retry payouts left "processing" by an earlier crash (same idempotency key).
    for payout in db.scalars(select(Payout).where(Payout.status == PayoutStatus.processing)).all():
        _send(db, provider, payout, db.get(PayoutAccount, payout.payout_account_id))

    groups: dict[tuple, list[Earning]] = defaultdict(list)
    for e in db.scalars(select(Earning).where(Earning.status == EarningStatus.available, Earning.payout_id.is_(None))):
        groups[(e.payee_user_id, e.currency)].append(e)

    for (payee, currency), rows in groups.items():
        total = sum(e.amount_cents for e in rows)
        account = db.scalar(select(PayoutAccount).where(PayoutAccount.user_id == payee))
        if total < settings.min_payout_cents or not account or account.status is not PayoutAccountStatus.enabled:
            summary["skipped"] += 1
            continue
        payout_id = uuid.uuid4()
        by_family: dict[str, int] = defaultdict(int)
        for e in rows:
            by_family[PAYABLE_PREFIX[e.kind]] += e.amount_cents
        # A family can be net negative (clawback after an earlier payout); it is
        # credited back and offset by the other family. Clearing pays the net total.
        entries = [ledger.cr(f"clearing:{provider.name}", total, f"payout {payout_id}")]
        for family, amount in by_family.items():
            if amount > 0:
                entries.append(ledger.dr(f"{family}:{payee}", amount, f"payout {payout_id}", payee))
            elif amount < 0:
                entries.append(ledger.cr(f"{family}:{payee}", -amount, f"payout {payout_id}", payee))
        journal = ledger.post(db, JournalKind.payout, f"payout:{payout_id}", "payout", payout_id,
                              f"Payout to {payee}", currency, entries)
        payout = Payout(id=payout_id, payee_user_id=payee, payout_account_id=account.id, amount_cents=total,
                        currency=currency, idempotency_key=f"payout:{payout_id}", journal_id=journal.id)
        db.add(payout)
        db.flush()
        for e in rows:
            e.status, e.payout_id = EarningStatus.paid, payout.id
        db.commit()  # record intent before calling the provider
        summary["created"] += 1
        _send(db, provider, payout, account)
        summary["sent" if payout.status is PayoutStatus.sent else "failed"] += 1
        db.commit()
    db.commit()
    return summary


def transfer_reversed(db: Session, transfer_id: str | None) -> str:
    payout = db.scalar(select(Payout).where(Payout.provider_transfer_id == transfer_id)) if transfer_id else None
    if not payout or payout.status is not PayoutStatus.sent:
        return "ignored"
    _fail(db, payout, "Transfer reversed at the payment provider", PayoutStatus.reversed)
    return "payout_reversed"


def cancel_stale_orders(db: Session, hours: int = 24) -> int:
    cutoff = utcnow() - timedelta(hours=hours)
    rows = db.scalars(select(Order).where(Order.status == OrderStatus.pending, Order.created_at < cutoff)).all()
    for o in rows:
        o.status = OrderStatus.canceled
    return len(rows)


def balances_for(db: Session, user_id, currency: str = "USD") -> dict:
    rows = db.execute(
        select(Earning.status, Earning.kind, func.coalesce(func.sum(Earning.amount_cents), 0))
        .where(Earning.payee_user_id == user_id, Earning.currency == currency)
        .group_by(Earning.status, Earning.kind)
    ).all()
    out = {"pending": 0, "available": 0, "paid": 0, "by_kind": defaultdict(int)}
    for st, kind, amount in rows:
        if st in (EarningStatus.pending, EarningStatus.available, EarningStatus.paid):
            out[st.value] += amount
            out["by_kind"][kind.value] += amount
    out["by_kind"] = dict(out["by_kind"])
    out["lifetime"] = out["pending"] + out["available"] + out["paid"]
    return out


# --- Reconciliation ----------------------------------------------------------------------

def reconcile(db: Session, triggered_by=None) -> ReconciliationRun:
    run = ReconciliationRun(status="running", triggered_by=triggered_by)
    db.add(run)
    db.flush()
    findings: list[dict] = []
    checks: dict = {}

    bad = ledger.unbalanced_journals(db)
    checks["balanced_journals"] = not bad
    findings += [{"check": "balanced_journals", "journal": k} for k in bad]

    # Payable accounts must equal the unpaid earnings sub-ledger, per payee and family.
    unpaid: dict[tuple, int] = defaultdict(int)
    for e in db.scalars(select(Earning).where(Earning.status.in_([EarningStatus.pending, EarningStatus.available]))):
        unpaid[(f"{PAYABLE_PREFIX[e.kind]}:{e.payee_user_id}", e.currency)] += e.amount_cents
    payable_ok = True
    accounts = db.scalars(select(LedgerAccount).where(
        LedgerAccount.code.like("creator_payable:%") | LedgerAccount.code.like("affiliate_payable:%")))
    seen = set()
    for acct in accounts:
        key = (acct.code, acct.currency)
        seen.add(key)
        ledger_balance = ledger.balance(db, acct.code, acct.currency)
        if ledger_balance != unpaid.get(key, 0):
            payable_ok = False
            findings.append({"check": "payables_match_earnings", "account": acct.code,
                             "ledger": ledger_balance, "earnings": unpaid.get(key, 0)})
    for key, amount in unpaid.items():
        if key not in seen and amount:
            payable_ok = False
            findings.append({"check": "payables_match_earnings", "account": key[0], "ledger": 0, "earnings": amount})
    checks["payables_match_earnings"] = payable_ok

    # Every paid order has a sale journal; fulfilled lines have a license and an allocation.
    orders_ok = True
    for order in db.scalars(select(Order).where(Order.status != OrderStatus.pending, Order.status != OrderStatus.canceled)):
        if not db.scalar(select(LedgerJournal.id).where(LedgerJournal.idempotency_key == f"sale:{order.id}")):
            orders_ok = False
            findings.append({"check": "orders_journaled", "order": str(order.id)})
        if sum(ln.unit_price_cents for ln in order.lines) != order.subtotal_cents or \
                sum(ln.tax_cents for ln in order.lines) != order.tax_cents:
            orders_ok = False
            findings.append({"check": "order_totals", "order": str(order.id)})
    for ln in db.scalars(select(OrderLine).where(OrderLine.status == OrderLineStatus.fulfilled)):
        grant = db.get(RightsGrant, ln.rights_grant_id) if ln.rights_grant_id else None
        has_alloc = db.scalar(select(RoyaltyAllocation.id).where(RoyaltyAllocation.order_line_id == ln.id))
        if not grant or grant.status.value != "active" or not has_alloc:
            orders_ok = False
            findings.append({"check": "lines_fulfilled", "line": str(ln.id)})
    checks["orders_consistent"] = orders_ok

    stuck = db.scalars(select(Payout).where(Payout.status == PayoutStatus.processing,
                                            Payout.created_at < utcnow() - timedelta(hours=1))).all()
    checks["no_stuck_payouts"] = not stuck
    findings += [{"check": "no_stuck_payouts", "payout": str(p.id)} for p in stuck]

    failed_events = db.scalars(select(FinancialEvent).where(FinancialEvent.processing_error.is_not(None))).all()
    checks["events_processed"] = not failed_events
    findings += [{"check": "events_processed", "event": e.provider_event_id, "error": e.processing_error[:200]}
                 for e in failed_events]

    checks["clearing_balance_cents"] = {
        f"{a.code} {a.currency}": ledger.balance(db, a.code, a.currency)
        for a in db.scalars(select(LedgerAccount).where(LedgerAccount.code.like("clearing:%")))
    }
    run.checks, run.findings = checks, findings
    run.status = "issues" if findings else "ok"
    run.finished_at = utcnow()
    db.flush()
    return run

