"""Finance administration: overview, orders, refunds, payouts, reconciliation, ledger."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.orders import order_out
from app.core.database import get_db
from app.core.deps import require_roles
from app.models import (
    Earning,
    EarningKind,
    EarningStatus,
    FinancialEvent,
    LedgerAccount,
    Order,
    OrderLineStatus,
    OrderStatus,
    Payout,
    PayoutStatus,
    ReconciliationRun,
    Refund,
    RefundReason,
    RoleCode,
    User,
)
from app.schemas.commerce import RefundIn
from app.services import ledger, payout_service
from app.services import payment_service as ps
from app.services.payments import PaymentProviderError, ProviderEvent, get_provider

router = APIRouter(prefix="/admin/finance", tags=["admin-finance"])
finance = require_roles(RoleCode.finance_admin)

REVENUE_STATUSES = [OrderStatus.paid, OrderStatus.partially_refunded, OrderStatus.refunded, OrderStatus.disputed]


@router.get("/overview")
def overview(currency: str = "USD", _: User = Depends(finance), db: Session = Depends(get_db)):
    revenue_orders = (Order.status.in_(REVENUE_STATUSES), Order.currency == currency)
    gmv, orders = db.execute(
        select(func.coalesce(func.sum(Order.subtotal_cents), 0), func.count(Order.id)).where(*revenue_orders)
    ).one()
    buyer_counts = db.execute(select(Order.buyer_user_id, func.count()).where(
        Order.status.in_(REVENUE_STATUSES), Order.currency == currency).group_by(Order.buyer_user_id)).all()
    refunds = db.scalar(select(func.coalesce(func.sum(Refund.amount_cents), 0)).where(Refund.currency == currency)) or 0

    def earned(kind):
        return db.scalar(select(func.coalesce(func.sum(Earning.amount_cents), 0)).where(
            Earning.kind == kind, Earning.currency == currency, Earning.status != EarningStatus.reversed)) or 0

    pending = db.scalar(select(func.coalesce(func.sum(Earning.amount_cents), 0)).where(
        Earning.currency == currency, Earning.status.in_([EarningStatus.pending, EarningStatus.available]))) or 0
    paid_out = db.scalar(select(func.coalesce(func.sum(Payout.amount_cents), 0)).where(
        Payout.currency == currency, Payout.status == PayoutStatus.sent)) or 0
    return {
        "currency": currency,
        "gmv_cents": gmv,
        "orders": orders,
        "paying_customers": len(buyer_counts),
        "repeat_customer_rate": round(sum(1 for _, n in buyer_counts if n > 1) / len(buyer_counts), 3) if buyer_counts else 0,
        "refunds_cents": refunds,
        "platform_revenue_cents": ledger.balance(db, "platform_revenue", currency),
        "fee_recovery_cents": ledger.balance(db, "fee_recovery", currency),
        "processing_fees_cents": ledger.balance(db, "processing_fees", currency),
        "tax_payable_cents": ledger.balance(db, "tax_payable", currency),
        "creator_earnings_cents": earned(EarningKind.stock_license),
        "affiliate_commissions_cents": earned(EarningKind.affiliate_commission),
        "owed_to_payees_cents": pending,
        "paid_out_cents": paid_out,
        "failed_events": db.scalar(select(func.count(FinancialEvent.id)).where(FinancialEvent.processing_error.is_not(None))),
    }


@router.get("/orders")
def list_orders(status_filter: OrderStatus | None = Query(None, alias="status"), page: int = Query(1, ge=1),
                page_size: int = Query(50, ge=1, le=200), _: User = Depends(finance), db: Session = Depends(get_db)):
    stmt = select(Order)
    if status_filter:
        stmt = stmt.where(Order.status == status_filter)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    orders = db.scalars(stmt.order_by(Order.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for o in orders:
        buyer = db.get(User, o.buyer_user_id)
        items.append(order_out(db, o) | {"buyer_email": buyer.email, "processing_fee_cents": o.processing_fee_cents})
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/orders/{order_id}/refund")
def refund(order_id: uuid.UUID, body: RefundIn, actor: User = Depends(finance), db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    try:
        reason = RefundReason(body.reason)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown refund reason") from None
    if reason is RefundReason.chargeback:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Chargebacks are recorded from provider events")
    wanted = set(body.line_ids)
    lines = [ln for ln in order.lines if ln.status is OrderLineStatus.fulfilled and (not wanted or ln.id in wanted)]
    if not lines:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing refundable on this order")
    provider = get_provider()
    try:
        for ln in lines:
            ps.refund_line(db, provider, ln, reason, body.note, actor.id)
            db.commit()  # one line at a time: each provider refund is matched by its own journal
    except PaymentProviderError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Payment provider error: {exc}") from None
    return order_out(db, order)


@router.post("/payouts/run")
def run_payouts(_: User = Depends(finance), db: Session = Depends(get_db)):
    result = payout_service.run_payouts(db, get_provider())
    db.commit()
    return result


@router.get("/payouts")
def list_payouts(_: User = Depends(finance), db: Session = Depends(get_db)):
    rows = db.scalars(select(Payout).order_by(Payout.created_at.desc()).limit(200))
    return [{"id": p.id, "payee_user_id": p.payee_user_id, "amount_cents": p.amount_cents, "currency": p.currency,
             "status": p.status.value, "provider_transfer_id": p.provider_transfer_id,
             "failure_reason": p.failure_reason, "created_at": p.created_at} for p in rows]


@router.post("/reconciliation/run")
def run_reconciliation(actor: User = Depends(finance), db: Session = Depends(get_db)):
    run = payout_service.reconcile(db, actor.id)
    db.commit()
    return _run_out(run)


@router.get("/reconciliation")
def reconciliation_runs(_: User = Depends(finance), db: Session = Depends(get_db)):
    return [_run_out(r) for r in db.scalars(select(ReconciliationRun).order_by(ReconciliationRun.started_at.desc())
                                            .limit(20))]


def _run_out(r: ReconciliationRun) -> dict:
    return {"id": r.id, "status": r.status, "started_at": r.started_at, "finished_at": r.finished_at,
            "checks": r.checks, "findings": r.findings}


@router.get("/ledger/accounts")
def ledger_accounts(_: User = Depends(finance), db: Session = Depends(get_db)):
    return [{"code": a.code, "type": a.account_type.value, "currency": a.currency,
             "balance_cents": ledger.balance(db, a.code, a.currency)}
            for a in db.scalars(select(LedgerAccount).order_by(LedgerAccount.code))]


@router.get("/events")
def events(failed_only: bool = True, _: User = Depends(finance), db: Session = Depends(get_db)):
    stmt = select(FinancialEvent)
    if failed_only:
        stmt = stmt.where(FinancialEvent.processing_error.is_not(None))
    return [{"id": e.id, "provider_event_id": e.provider_event_id, "type": e.event_type, "received_at": e.received_at,
             "processed_at": e.processed_at, "error": e.processing_error}
            for e in db.scalars(stmt.order_by(FinancialEvent.received_at.desc()).limit(200))]


@router.post("/events/{event_id}/retry")
def retry_event(event_id: uuid.UUID, _: User = Depends(finance), db: Session = Depends(get_db)):
    record = db.get(FinancialEvent, event_id)
    if not record or record.processed_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No failed event with that id")
    outcome = ps.handle_event(db, get_provider(),
                              ProviderEvent(id=record.provider_event_id, type=record.event_type, data=record.payload))
    db.commit()
    return {"outcome": outcome}
