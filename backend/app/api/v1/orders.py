"""Checkout, orders and payment-provider webhooks."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import current_user, optional_user, verified_user
from app.core.rate_limit import limiter
from app.models import FileKind, LicenseType, MediaAsset, Milestone, Order, OrderStatus, RightsGrant, User
from app.schemas.commerce import OrderIn, OrderOut
from app.services import media_service as ms
from app.services import payment_service as ps
from app.services.payments import PaymentProviderError, ProviderEvent, get_provider

router = APIRouter(tags=["orders"])


def order_out(db: Session, order: Order) -> dict:
    lines = []
    for ln in order.lines:
        asset = db.get(MediaAsset, ln.asset_id)
        grant = db.get(RightsGrant, ln.rights_grant_id) if ln.rights_grant_id else None
        lines.append({
            "id": ln.id, "asset_id": ln.asset_id, "asset_title": asset.title if asset else "",
            "thumbnail_url": ms.public_url(asset.file(FileKind.thumbnail)) if asset else None,
            "license_name": db.get(LicenseType, ln.license_type_id).name, "size_tier": ln.size_tier,
            "licensee_name": ln.licensee_name, "unit_price_cents": ln.unit_price_cents, "tax_cents": ln.tax_cents,
            "status": ln.status.value, "certificate_number": grant.certificate_number if grant else None,
            "refunded_cents": ln.refunded_cents, "price_listing_id": ln.price_listing_id,
        })
    return {"id": order.id, "status": order.status.value, "currency": order.currency,
            "subtotal_cents": order.subtotal_cents, "tax_cents": order.tax_cents, "total_cents": order.total_cents,
            "checkout_url": order.checkout_url if order.status is OrderStatus.pending else None,
            "created_at": order.created_at, "paid_at": order.paid_at, "lines": lines,
            "purpose": order.purpose.value,
            "project_id": db.get(Milestone, order.milestone_id).project_id if order.milestone_id else None}


@router.post("/orders", response_model=OrderOut, status_code=201)
def create_order(body: OrderIn, request: Request, user: User = Depends(verified_user), db: Session = Depends(get_db)):
    limiter.check(f"order:{user.id}", 30, 3600)
    try:
        order = ps.create_order(db, get_provider(), user, [i.model_dump() for i in body.items], body.idempotency_key)
    except PaymentProviderError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Payment provider error: {exc}") from None
    db.commit()
    return order_out(db, order)


@router.get("/orders/mine", response_model=list[OrderOut])
def my_orders(user: User = Depends(current_user), db: Session = Depends(get_db)):
    orders = db.scalars(select(Order).where(Order.buyer_user_id == user.id, Order.status != OrderStatus.canceled)
                        .order_by(Order.created_at.desc()).limit(100))
    return [order_out(db, o) for o in orders]


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order or order.buyer_user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return order_out(db, order)


@router.post("/payments/webhooks/{provider_name}", include_in_schema=False)
async def webhook(provider_name: str, request: Request, db: Session = Depends(get_db)):
    provider = get_provider()
    if provider_name != provider.name:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown provider")
    payload = await request.body()
    try:
        event = provider.parse_webhook(payload, request.headers.get("stripe-signature"))
    except PaymentProviderError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    outcome = ps.handle_event(db, provider, event)
    db.commit()
    # A 500 makes the provider retry later; the stored event is re-processed then.
    return JSONResponse({"received": True, "outcome": outcome}, status_code=500 if outcome == "error" else 200)


@router.post("/payments/dev/complete/{order_id}", include_in_schema=False)
def dev_complete(order_id: uuid.UUID, request: Request, outcome: str = Query("paid", pattern="^(paid|expired)$"),
                 user: User | None = Depends(optional_user), db: Session = Depends(get_db)):
    """Development only: simulate the provider completing a checkout. Gallery
    orders are placed without an account, so they need no session."""
    provider = get_provider()
    if provider.name != "fake" or get_settings().is_production:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    order = db.get(Order, order_id)
    if not order or (order.buyer_user_id is not None and (user is None or order.buyer_user_id != user.id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    provider.remember_session(order.provider_session_id, str(order.id), order.currency, order.subtotal_cents)
    event_type = "checkout.session.completed" if outcome == "paid" else "checkout.session.expired"
    event = ProviderEvent(id=f"evt_fake_{uuid.uuid4().hex}", type=event_type, data={
        "object": "checkout.session", "id": order.provider_session_id,
        "payment_status": "paid" if outcome == "paid" else "unpaid", "metadata": {"order_id": str(order.id)},
    })
    result = ps.handle_event(db, provider, event)
    db.commit()
    return {"outcome": result}
