"""Gallery add-on sales: digital downloads and creator-fulfilled prints.

A client opens their private gallery link and buys full-resolution downloads
(a per-gallery price) or prints (print options the creator defines and ships
themselves). The client pays without an account; the order carries their
name and email.

Money flow (integer cents), using the versioned ``services_commission`` rule
snapshotted on each gallery order:

    Sale      Dr clearing (total − fee), Dr processing_fees (fee)
              Cr tax_payable (tax), Cr creator_payable (subtotal × creator share),
              Cr platform_revenue (commission)
    Refund    Dr each credited account in proportion to what is still
              outstanding on it, Cr clearing (amount)

The platform pays processing fees from its commission, as with bookings.
Print fulfillment (production, shipping, reprints) is the creator's
responsibility; the platform only records tracking details.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    ClientGallery,
    CreatorProfile,
    Earning,
    EarningKind,
    EarningStatus,
    GalleryItem,
    GalleryItemStatus,
    GalleryOrder,
    GalleryOrderItem,
    GalleryOrderStatus,
    GalleryPrintOption,
    JournalKind,
    LedgerJournal,
    Order,
    OrderPurpose,
    OrderStatus,
    Refund,
    RefundReason,
    RevenueShareRule,
)
from app.services import audit, email, ledger
from app.services import royalty_engine as engine
from app.services.notify import notify
from app.services.payment_service import (
    adjust_earnings,
    prorate,
    share_rule,
    spread_over_earnings,
)
from app.services.payments import CheckoutItem, PaymentDetails, PaymentProvider

MAX_ITEMS = 100
PRINT_TAX_CODE = "txcd_99999999"  # general tangible goods
DIGITAL_TAX_CODE = "txcd_10501000"  # digital photographs


def now() -> datetime:
    return datetime.now(UTC)


def _commission_rule(db: Session) -> RevenueShareRule:
    rule = db.scalar(select(RevenueShareRule).where(RevenueShareRule.code == "services_commission")
                     .order_by(RevenueShareRule.version.desc()))
    if not rule:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Services commission is not configured")
    return rule


def gallery_order_for(db: Session, order: Order) -> GalleryOrder:
    return db.scalar(select(GalleryOrder).where(GalleryOrder.order_id == order.id))


def creator_user_of(db: Session, gallery: ClientGallery) -> uuid.UUID:
    return db.get(CreatorProfile, gallery.creator_id).user_id


def print_options(db: Session, gallery: ClientGallery, active_only: bool = True) -> list[GalleryPrintOption]:
    stmt = select(GalleryPrintOption).where(GalleryPrintOption.gallery_id == gallery.id)
    if active_only:
        stmt = stmt.where(GalleryPrintOption.is_active)
    return db.scalars(stmt.order_by(GalleryPrintOption.price_cents)).all()


def for_sale(db: Session, gallery: ClientGallery) -> bool:
    return bool(gallery.download_price_cents) or bool(print_options(db, gallery))


# --- Checkout ----------------------------------------------------------------------------------

def create_order(db: Session, provider: PaymentProvider, gallery: ClientGallery, token: str, data: dict) -> Order:
    settings = get_settings()
    if not settings.feature_paid_licensing:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Payments are not enabled yet")
    items = data["items"]
    if not items or len(items) > MAX_ITEMS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"An order needs 1 to {MAX_ITEMS} items")
    options = {o.id: o for o in print_options(db, gallery)}
    rows: list[GalleryOrderItem] = []
    digital_seen: set[uuid.UUID] = set()
    for it in items:
        item = db.get(GalleryItem, it["item_id"])
        if not item or item.gallery_id != gallery.id or item.status is not GalleryItemStatus.ready:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "An item in your order is no longer available")
        if it["kind"] == "digital":
            if not gallery.download_price_cents:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Downloads are not for sale in this gallery")
            if gallery.allow_downloads or item.download_unlocked:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{item.filename} can already be downloaded")
            if item.id in digital_seen:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Duplicate download in order")
            digital_seen.add(item.id)
            rows.append(GalleryOrderItem(item_id=item.id, kind="digital", description=f"Digital download · {item.filename}"[:300],
                                         quantity=1, unit_price_cents=gallery.download_price_cents))
        elif it["kind"] == "print":
            opt = options.get(it.get("print_option_id"))
            if not opt:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "That print option is not offered")
            rows.append(GalleryOrderItem(item_id=item.id, kind="print", print_option_id=opt.id,
                                         description=f"{opt.name} · {item.filename}"[:300],
                                         quantity=it.get("quantity") or 1, unit_price_cents=opt.price_cents))
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Item kind must be digital or print")
    has_prints = any(r.kind == "print" for r in rows)
    if has_prints and not data.get("shipping_address"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A shipping address is required for prints")
    subtotal = sum(r.unit_price_cents * r.quantity for r in rows)
    email_addr = str(data["client_email"]).lower()
    order = Order(buyer_user_id=None, buyer_email=email_addr, currency=gallery.currency, subtotal_cents=subtotal,
                  tax_cents=0, total_cents=subtotal, idempotency_key=f"gallery:{uuid.uuid4()}",
                  provider=provider.name, purpose=OrderPurpose.gallery, lines=[])
    db.add(order)
    db.flush()
    gorder = GalleryOrder(gallery_id=gallery.id, order_id=order.id, client_name=data["client_name"].strip()[:200],
                          client_email=email_addr, shipping_address=data.get("shipping_address") if has_prints else None,
                          commission_rule_id=_commission_rule(db).id, allocation={})
    gorder_items = rows
    db.add(gorder)
    db.flush()
    for r in gorder_items:
        r.gallery_order_id = gorder.id
        db.add(r)
    web = settings.public_web_url
    session = provider.create_checkout(
        order_id=str(order.id), currency=order.currency,
        items=[CheckoutItem(r.description if r.quantity == 1 else f"{r.description} × {r.quantity}",
                            f"From “{gallery.title}”", r.unit_price_cents * r.quantity,
                            tax_code=PRINT_TAX_CODE if r.kind == "print" else DIGITAL_TAX_CODE)
               for r in gorder_items],
        customer_email=email_addr, success_url=f"{web}/g/{token}?order={order.id}",
        cancel_url=f"{web}/g/{token}?canceled={order.id}", idempotency_key=f"checkout:{order.id}",
    )
    order.provider_session_id, order.checkout_url = session.id, session.url
    audit.record(db, "gallery.order_created", None, "order", order.id, gallery=gallery.id, total=subtotal)
    return order


# --- Fulfillment ---------------------------------------------------------------------------------

def _items(db: Session, gorder: GalleryOrder) -> list[GalleryOrderItem]:
    return db.scalars(select(GalleryOrderItem).where(GalleryOrderItem.gallery_order_id == gorder.id)).all()


def _set_unlocked(db: Session, gorder: GalleryOrder, unlocked: bool) -> None:
    for row in _items(db, gorder):
        if row.kind == "digital":
            db.get(GalleryItem, row.item_id).download_unlocked = unlocked


def fulfill(db: Session, order: Order, payment: PaymentDetails) -> None:
    """Webhook: the client's payment succeeded. Idempotent."""
    if order.status is not OrderStatus.pending or not payment.paid:
        return
    expected = order.subtotal_cents + payment.amount_tax_cents
    if payment.currency.upper() != order.currency or payment.amount_total_cents != expected:
        raise ValueError(f"payment mismatch for gallery order {order.id}")
    gorder = gallery_order_for(db, order)
    gallery = db.get(ClientGallery, gorder.gallery_id)
    order.status, order.paid_at = OrderStatus.paid, now()
    order.tax_cents, order.total_cents = payment.amount_tax_cents, payment.amount_total_cents
    order.processing_fee_cents, order.provider_payment_id = payment.fee_cents, payment.payment_id
    rule = db.get(RevenueShareRule, gorder.commission_rule_id)
    result = engine.calculate(engine.RoyaltyInput(gross_cents=order.subtotal_cents, rule=share_rule(rule),
                                                  creator_party_id="creator", currency=order.currency))
    creator_user = creator_user_of(db, gallery)
    memo = f"gallery order {order.id}"
    creator_code = ledger.creator_payable(creator_user)
    journal = ledger.post(db, JournalKind.gallery_sale, f"gallery-sale:{order.id}", "order", order.id, memo,
                          order.currency, [
                              ledger.dr(f"clearing:{order.provider}", order.total_cents - order.processing_fee_cents),
                              ledger.dr("processing_fees", order.processing_fee_cents),
                              ledger.cr("tax_payable", order.tax_cents, memo),
                              ledger.cr(creator_code, result.creator_pool_cents, memo, creator_user),
                              ledger.cr("platform_revenue", result.platform_net_cents, memo),
                          ])
    gorder.allocation = {k: v for k, v in {creator_code: result.creator_pool_cents,
                                           "platform_revenue": result.platform_net_cents,
                                           "tax_payable": order.tax_cents}.items() if v}
    if result.creator_pool_cents:
        db.add(Earning(payee_user_id=creator_user, kind=EarningKind.gallery_sale, order_id=order.id,
                       amount_cents=result.creator_pool_cents, currency=order.currency, status=EarningStatus.pending,
                       available_at=now() + timedelta(days=get_settings().earnings_hold_days),
                       journal_id=journal.id))
    _set_unlocked(db, gorder, True)
    items = _items(db, gorder)
    prints = sum(r.quantity for r in items if r.kind == "print")
    downloads = any(r.kind == "digital" for r in items)
    gorder.status = GalleryOrderStatus.paid
    link = f"{get_settings().public_web_url}/g/{gallery.access_token}"
    email.send(gorder.client_email, f"Your order from “{gallery.title}”",
               f"Hi {gorder.client_name},\n\nThank you for your order of {order.total_cents / 100:,.2f} "
               f"{order.currency}.\n\n"
               + ("Your downloads are unlocked in the gallery:\n" + link + "\n\n" if downloads else "")
               + ("The photographer will print and ship your prints and send tracking details.\n" if prints else ""))
    notify(db, creator_user, "gallery_order", f"New gallery order: {order.total_cents / 100:,.2f} {order.currency}",
           f"{gorder.client_name} ordered from {gallery.title}" + (f"; {prints} print(s) to ship." if prints else "."),
           f"/dashboard/galleries/{gallery.id}", send_email=True)
    audit.record(db, "gallery.order_paid", None, "order", order.id, gallery=gallery.id)


def mark_shipped(db: Session, gorder: GalleryOrder, carrier: str, tracking: str, actor_id) -> None:
    if gorder.status is not GalleryOrderStatus.paid and gorder.status is not GalleryOrderStatus.partially_refunded:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only paid orders can be marked shipped")
    if not any(r.kind == "print" for r in _items(db, gorder)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This order has no prints")
    gorder.status, gorder.carrier, gorder.tracking_number, gorder.shipped_at = (
        GalleryOrderStatus.shipped, carrier.strip()[:60], tracking.strip()[:120], now())
    gallery = db.get(ClientGallery, gorder.gallery_id)
    email.send(gorder.client_email, f"Your prints from “{gallery.title}” have shipped",
               f"Hi {gorder.client_name},\n\nYour prints are on the way.\nCarrier: {gorder.carrier}\n"
               f"Tracking number: {gorder.tracking_number}\n")
    audit.record(db, "gallery.order_shipped", actor_id, "gallery_order", gorder.id, carrier=gorder.carrier)


# --- Refunds and chargebacks ------------------------------------------------------------------

def refundable(gorder: GalleryOrder) -> int:
    return sum((gorder.allocation or {}).values())


def _reverse(db: Session, order: Order, gorder: GalleryOrder, amount: int, kind: JournalKind, key: str,
             memo: str, actor_id) -> tuple[uuid.UUID, dict[str, int]]:
    alloc = dict(gorder.allocation or {})
    codes, outstanding = list(alloc), list(alloc.values())
    if amount <= 0 or amount > sum(outstanding):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Refund must be between 0.01 and {sum(outstanding) / 100:.2f}")
    parts = outstanding if amount == sum(outstanding) else prorate(amount, outstanding)
    taken = {c: p for c, p in zip(codes, parts, strict=True) if p}
    owners = {c: uuid.UUID(c.partition(":")[2]) for c in taken if c.startswith("creator_payable:")}
    entries = [ledger.dr(c, p, memo, owners.get(c)) for c, p in taken.items()]
    entries.append(ledger.cr(f"clearing:{order.provider}", amount, memo))
    journal = ledger.post(db, kind, key, "order", order.id, memo, order.currency, entries, created_by=actor_id)
    adjust_earnings(db, spread_over_earnings(db, list(db.scalars(select(Earning).where(
        Earning.order_id == order.id))), taken), journal.id)
    gorder.allocation = {c: v - taken.get(c, 0) for c, v in alloc.items() if v - taken.get(c, 0)}
    return journal.id, taken


def refund_gallery_order(db: Session, provider: PaymentProvider | None, order: Order, amount: int | None,
                         reason: RefundReason, note: str, actor_id) -> Refund:
    """Refund a paid gallery order, fully (``amount=None``) or partially
    (price + tax). ``provider=None`` records a refund issued at the provider.
    Purchased downloads are locked again only on a full refund."""
    gorder = gallery_order_for(db, order)
    if order.status not in (OrderStatus.paid, OrderStatus.partially_refunded):
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing refundable on this order")
    amount = refundable(gorder) if amount is None else amount
    seq = db.scalar(select(func.count(Refund.id)).where(Refund.order_id == order.id)) or 0
    key = f"gallery-refund:{order.id}" if seq == 0 else f"gallery-refund:{order.id}:{seq}"
    if amount <= 0 or amount > refundable(gorder):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Refund must be between 0.01 and {refundable(gorder) / 100:.2f}")
    refund_id = None
    if provider is not None:
        refund_id = provider.refund(payment_id=order.provider_payment_id, amount_cents=amount, idempotency_key=key,
                                    metadata={"order_id": str(order.id)})
    journal_id, taken = _reverse(db, order, gorder, amount, JournalKind.refund, key,
                                 f"Refund gallery order {order.id}", actor_id)
    full = not gorder.allocation
    order.status = OrderStatus.refunded if full else OrderStatus.partially_refunded
    gorder.status = GalleryOrderStatus.refunded if full else GalleryOrderStatus.partially_refunded
    if full:
        _set_unlocked(db, gorder, False)
    refund = Refund(order_id=order.id, order_line_id=None, amount_cents=amount, currency=order.currency, reason=reason,
                    note=note, provider_refund_id=refund_id, journal_id=journal_id, initiated_by=actor_id,
                    allocation=taken)
    db.add(refund)
    audit.record(db, "gallery.order_refunded", actor_id, "order", order.id, amount=amount, reason=reason.value)
    db.flush()
    return refund


def chargeback_gallery_order(db: Session, order: Order, dispute_id: str) -> None:
    gorder = gallery_order_for(db, order)
    snapshot = {"allocation": dict(gorder.allocation or {}), "status": gorder.status.value,
                "order_status": order.status.value}
    if refundable(gorder):
        _reverse(db, order, gorder, refundable(gorder), JournalKind.dispute, f"dispute:{dispute_id}:{order.id}",
                 f"Chargeback {dispute_id}", None)
    gorder.chargeback_snapshot = snapshot
    _set_unlocked(db, gorder, False)
    gorder.status, order.status = GalleryOrderStatus.disputed, OrderStatus.disputed
    gallery = db.get(ClientGallery, gorder.gallery_id)
    notify(db, creator_user_of(db, gallery), "chargeback", f"Gallery payment disputed by the bank: {gallery.title}",
           "The client's bank reversed this payment. Hold any unshipped prints and contact support.",
           f"/dashboard/galleries/{gallery.id}", send_email=True)


def reinstate_gallery_order(db: Session, order: Order, dispute_id: str) -> None:
    gorder = gallery_order_for(db, order)
    snap = gorder.chargeback_snapshot
    reversed_journal = db.scalar(select(LedgerJournal).where(
        LedgerJournal.idempotency_key == f"dispute:{dispute_id}:{order.id}"))
    if not snap:
        return
    if reversed_journal:
        entries = [ledger.Line(e.account.code, debit=e.credit_cents, credit=e.debit_cents,
                               memo=f"dispute won {dispute_id}", owner_user_id=e.account.owner_user_id)
                   for e in reversed_journal.entries]
        journal = ledger.post(db, JournalKind.dispute_reinstated, f"dispute-won:{dispute_id}:{order.id}", "order",
                              order.id, f"Dispute won {dispute_id}", order.currency, entries)
        for code, cents in snap["allocation"].items():
            if code.startswith("creator_payable:") and cents:
                db.add(Earning(payee_user_id=uuid.UUID(code.partition(":")[2]), kind=EarningKind.gallery_sale,
                               order_id=order.id, amount_cents=cents, currency=order.currency,
                               status=EarningStatus.pending,
                               available_at=now() + timedelta(days=get_settings().earnings_hold_days),
                               journal_id=journal.id))
    gorder.allocation = snap["allocation"]
    gorder.status, order.status = GalleryOrderStatus(snap["status"]), OrderStatus(snap["order_status"])
    if gorder.status is not GalleryOrderStatus.refunded:
        _set_unlocked(db, gorder, True)
    gorder.chargeback_snapshot = None
    audit.record(db, "gallery.dispute_won", None, "order", order.id, dispute=dispute_id)


# --- Views ----------------------------------------------------------------------------------------

def order_view(db: Session, gorder: GalleryOrder) -> dict:
    order = db.get(Order, gorder.order_id)
    return {
        "id": gorder.id, "order_id": order.id, "client_name": gorder.client_name, "client_email": gorder.client_email,
        "status": gorder.status.value, "currency": order.currency, "subtotal_cents": order.subtotal_cents,
        "tax_cents": order.tax_cents, "total_cents": order.total_cents, "shipping_address": gorder.shipping_address,
        "carrier": gorder.carrier, "tracking_number": gorder.tracking_number, "shipped_at": gorder.shipped_at,
        "created_at": gorder.created_at, "paid_at": order.paid_at,
        "items": [{"item_id": r.item_id, "kind": r.kind, "description": r.description, "quantity": r.quantity,
                   "unit_price_cents": r.unit_price_cents} for r in _items(db, gorder)],
    }


def gallery_earning_view(db: Session, e: Earning) -> tuple[str, str, int, str, list[str]]:
    order = db.get(Order, e.order_id)
    gorder = gallery_order_for(db, order)
    gallery = db.get(ClientGallery, gorder.gallery_id)
    rule = db.get(RevenueShareRule, gorder.commission_rule_id)
    label = f"{rule.code} v{rule.version}"
    return (f"Gallery order: {gallery.title}", "Gallery sale", order.subtotal_cents, label, [
        f"Order subtotal: {order.subtotal_cents / 100:,.2f} {order.currency} (from {gorder.client_name})",
        f"Creator share ({rule.creator_bps / 100:g}%): {abs(e.amount_cents) / 100:,.2f}",
        f"Rule: {label}",
    ])
