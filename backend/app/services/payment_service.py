"""Orders, fulfillment, refunds, disputes and provider events.

Money flow for one paid order (all integer cents):

    total = subtotal + tax                     (what the buyer paid)
    fee   = provider processing fee            (kept by the provider)

    Sale journal
      Dr clearing:<provider>       total - fee
      Dr processing_fees           fee
      Cr tax_payable               tax
      per line, from the royalty engine:
        Cr creator_payable:<user>    creator pool
        Cr affiliate_payable:<user>  affiliate commission (from the platform share)
        Cr platform_revenue          platform net
        Cr fee_recovery              the line's fee, when the rule deducts fees from net revenue

The credits per line add up to the line's gross (net + deducted fee), so the
journal always balances. A refund posts the exact mirror of a line's credits
against clearing; the provider keeps its original fee, which the platform
absorbs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AgreementStatus,
    ContributorAgreement,
    CreatorProfile,
    Earning,
    EarningKind,
    EarningStatus,
    FinancialEvent,
    GrantSource,
    GrantStatus,
    JournalKind,
    LedgerJournal,
    LicenseType,
    MediaAsset,
    MediaStatus,
    Order,
    OrderLine,
    OrderLineStatus,
    OrderPurpose,
    OrderStatus,
    PayoutAccount,
    PayoutAccountStatus,
    PriceListing,
    Referral,
    ReferralStatus,
    Refund,
    RefundReason,
    RevenueModel,
    RevenueShareRule,
    RightsGrant,
    RoyaltyAllocation,
    User,
)
from app.services import audit, ledger
from app.services import royalty_engine as engine
from app.services.licensing_service import issue_grant, rights_available
from app.services.payments import CheckoutItem, PaymentDetails, PaymentProvider, ProviderEvent

log = logging.getLogger("payments")

MAX_LINES = 20


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def prorate(total: int, weights: list[int]) -> list[int]:
    """Split ``total`` in proportion to ``weights`` (largest remainder; exact sum)."""
    if total == 0 or not weights:
        return [0] * len(weights)
    denom = sum(weights)
    exact = [total * w for w in weights]
    parts = [e // denom for e in exact]
    order = sorted(range(len(weights)), key=lambda i: (-(exact[i] % denom), i))
    for i in order[: total - sum(parts)]:
        parts[i] += 1
    return parts


def share_rule(rule: RevenueShareRule) -> engine.ShareRule:
    return engine.ShareRule(rule.code, rule.version, engine.Model(rule.revenue_model.value), rule.creator_bps,
                            rule.initial_exclusive_creator_bps, rule.affiliate_bps_of_platform,
                            tuple(rule.net_revenue_deductions))


# --- Referrals -------------------------------------------------------------------------

def active_affiliate(db: Session, buyer: User) -> uuid.UUID | None:
    ref = db.scalar(select(Referral).where(Referral.referred_user_id == buyer.id))
    if not ref or ref.status is not ReferralStatus.active or aware(ref.attributed_until) < utcnow():
        return None
    referrer = db.get(User, ref.referrer_user_id)
    if not referrer or referrer.status.value != "active" or referrer.id == buyer.id:
        return None
    return referrer.id


# --- Orders -------------------------------------------------------------------------------

def create_order(db: Session, provider: PaymentProvider, buyer: User, items: list[dict], idempotency_key: str) -> Order:
    settings = get_settings()
    if not settings.feature_paid_licensing:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Paid licensing is not available yet")
    existing = db.scalar(select(Order).where(Order.buyer_user_id == buyer.id, Order.idempotency_key == idempotency_key))
    if existing:
        return existing
    if not items or len(items) > MAX_LINES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"An order needs 1 to {MAX_LINES} items")

    lines: list[OrderLine] = []
    seen: set = set()
    for pos, item in enumerate(items):
        listing = db.get(PriceListing, item["price_listing_id"])
        if not listing or not listing.is_active or listing.price_cents <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A selected license is no longer offered")
        if listing.id in seen:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Duplicate item in order")
        seen.add(listing.id)
        lt: LicenseType = listing.license_type
        if lt.is_free or lt.is_exclusive or lt.code == "negotiated":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "That license cannot be purchased at checkout")
        asset = db.get(MediaAsset, listing.asset_id)
        if not asset or asset.status is not MediaStatus.approved:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A selected media item is no longer available")
        creator = db.get(CreatorProfile, asset.creator_id)
        if creator.user_id == buyer.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot license your own media")
        agreement = db.get(ContributorAgreement, asset.contributor_agreement_id) if asset.contributor_agreement_id else None
        if (not agreement or agreement.status is not AgreementStatus.active
                or agreement.template.revenue_model is not RevenueModel.nonexclusive):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This media is not currently offered for paid licensing")
        if not rights_available(db, asset.id, lt):
            raise HTTPException(status.HTTP_409_CONFLICT, "These rights are no longer available for this media")
        if lines and listing.currency != lines[0].currency:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "All items in one order must use the same currency")
        lines.append(OrderLine(
            position=pos, asset_id=asset.id, creator_id=creator.id, price_listing_id=listing.id,
            license_type_id=lt.id, contributor_agreement_id=agreement.id,
            revenue_share_rule_id=agreement.template.revenue_share_rule_id, size_tier=listing.size_tier,
            licensee_name=(item.get("licensee_name") or buyer.display_name).strip()[:200],
            description=f"{lt.name} license · {asset.title}"[:300], unit_price_cents=listing.price_cents,
            currency=listing.currency,
        ))

    subtotal = sum(ln.unit_price_cents for ln in lines)
    order = Order(buyer_user_id=buyer.id, currency=lines[0].currency, subtotal_cents=subtotal, tax_cents=0,
                  total_cents=subtotal, idempotency_key=idempotency_key, provider=provider.name,
                  affiliate_user_id=active_affiliate(db, buyer), lines=lines)
    db.add(order)
    db.flush()
    web = settings.public_web_url
    session = provider.create_checkout(
        order_id=str(order.id), currency=order.currency,
        items=[CheckoutItem(ln.description, f"Licensed to {ln.licensee_name}", ln.unit_price_cents) for ln in lines],
        customer_email=buyer.email, success_url=f"{web}/checkout/success?order={order.id}",
        cancel_url=f"{web}/cart?canceled={order.id}", idempotency_key=f"checkout:{order.id}",
    )
    order.provider_session_id, order.checkout_url = session.id, session.url
    audit.record(db, "order.created", buyer.id, "order", order.id, total=subtotal, currency=order.currency,
                 lines=len(lines), affiliate=order.affiliate_user_id)
    return order


# --- Fulfillment -------------------------------------------------------------------------

def fulfill_order(db: Session, order: Order, payment: PaymentDetails) -> None:
    """Record a successful payment: royalties, ledger, licenses, earnings. Idempotent."""
    if order.status is not OrderStatus.pending:
        return
    if not payment.paid:
        return
    expected_total = order.subtotal_cents + payment.amount_tax_cents
    if payment.currency.upper() != order.currency or payment.amount_total_cents != expected_total:
        raise ValueError(
            f"payment mismatch for order {order.id}: provider {payment.amount_total_cents} {payment.currency}, "
            f"expected {order.subtotal_cents} + tax {payment.amount_tax_cents} {order.currency}"
        )
    settings = get_settings()
    now = utcnow()
    order.status, order.paid_at = OrderStatus.paid, now
    order.tax_cents, order.total_cents = payment.amount_tax_cents, payment.amount_total_cents
    order.processing_fee_cents, order.provider_payment_id = payment.fee_cents, payment.payment_id

    weights = [ln.unit_price_cents for ln in order.lines]
    line_tax = payment.line_tax_cents
    if not line_tax or len(line_tax) != len(order.lines) or sum(line_tax) != order.tax_cents:
        line_tax = prorate(order.tax_cents, weights)  # provider gave only an order total
    for ln, tax, fee in zip(order.lines, line_tax, prorate(order.processing_fee_cents, weights), strict=True):
        ln.tax_cents, ln.processing_fee_cents = tax, fee

    entries = [
        ledger.dr(f"clearing:{order.provider}", order.total_cents - order.processing_fee_cents, f"order {order.id}"),
        ledger.dr("processing_fees", order.processing_fee_cents, f"order {order.id}"),
        ledger.cr("tax_payable", order.tax_cents, f"order {order.id}"),
    ]
    pending_earnings: list[tuple[uuid.UUID, EarningKind, OrderLine, int]] = []
    buyer = db.get(User, order.buyer_user_id)
    for ln in order.lines:
        rule = db.get(RevenueShareRule, ln.revenue_share_rule_id)
        creator = db.get(CreatorProfile, ln.creator_id)
        result = engine.calculate(engine.RoyaltyInput(
            gross_cents=ln.unit_price_cents, rule=share_rule(rule), creator_party_id=str(creator.user_id),
            currency=ln.currency, deductions={"payment_processing_fees": ln.processing_fee_cents},
            affiliate_party_id=str(order.affiliate_user_id) if order.affiliate_user_id else None,
        ))
        db.add(RoyaltyAllocation(
            order_line_id=ln.id, rule_code=rule.code, rule_version=rule.version, gross_cents=result.gross_cents,
            deductions=result.deductions_applied, net_cents=result.net_cents, creator_bps=result.creator_bps_applied,
            creator_pool_cents=result.creator_pool_cents, platform_share_cents=result.platform_share_cents,
            affiliate_cents=result.affiliate_cents, platform_net_cents=result.platform_net_cents,
            allocations=[a.__dict__ for a in result.allocations], explanation=result.explain(), currency=ln.currency,
        ))
        memo = f"line {ln.id}"
        entries.append(ledger.cr(ledger.creator_payable(creator.user_id), result.creator_pool_cents, memo, creator.user_id))
        if result.affiliate_cents:
            entries.append(ledger.cr(ledger.affiliate_payable(order.affiliate_user_id), result.affiliate_cents, memo,
                                     order.affiliate_user_id))
            pending_earnings.append((order.affiliate_user_id, EarningKind.affiliate_commission, ln, result.affiliate_cents))
        entries.append(ledger.cr("platform_revenue", result.platform_net_cents, memo))
        entries.append(ledger.cr("fee_recovery", result.deductions_applied.get("payment_processing_fees", 0), memo))
        if result.creator_pool_cents:
            pending_earnings.append((creator.user_id, EarningKind.stock_license, ln, result.creator_pool_cents))

        asset = db.get(MediaAsset, ln.asset_id)
        lt = db.get(LicenseType, ln.license_type_id)
        grant, _ = issue_grant(db, user=buyer, asset=asset, license_type=lt, size_tier=ln.size_tier,
                               licensee_name=ln.licensee_name, source=GrantSource.purchase,
                               price_cents=ln.unit_price_cents, currency=ln.currency)
        ln.rights_grant_id, ln.status = grant.id, OrderLineStatus.fulfilled

    journal = ledger.post(db, JournalKind.sale, f"sale:{order.id}", "order", order.id, f"Sale {order.id}",
                          order.currency, entries)
    available_at = now + timedelta(days=settings.earnings_hold_days)
    for payee, kind, ln, amount in pending_earnings:
        db.add(Earning(payee_user_id=payee, kind=kind, order_line_id=ln.id, amount_cents=amount, currency=ln.currency,
                       status=EarningStatus.pending, available_at=available_at, journal_id=journal.id))
    audit.record(db, "order.paid", order.buyer_user_id, "order", order.id, total=order.total_cents,
                 fee=order.processing_fee_cents, tax=order.tax_cents)
    db.flush()


# --- Refunds and disputes -------------------------------------------------------------------

def _line_credits(db: Session, ln: OrderLine) -> list[ledger.Line]:
    """The exact credits a line received in its sale journal (from the allocation)."""
    alloc = db.scalar(select(RoyaltyAllocation).where(RoyaltyAllocation.order_line_id == ln.id))
    order = ln.order
    creator = db.get(CreatorProfile, ln.creator_id)
    memo = f"line {ln.id}"
    credits = [ledger.cr(ledger.creator_payable(creator.user_id), alloc.creator_pool_cents, memo, creator.user_id)]
    if alloc.affiliate_cents:
        credits.append(ledger.cr(ledger.affiliate_payable(order.affiliate_user_id), alloc.affiliate_cents, memo,
                                 order.affiliate_user_id))
    credits += [
        ledger.cr("platform_revenue", alloc.platform_net_cents, memo),
        ledger.cr("fee_recovery", alloc.deductions.get("payment_processing_fees", 0), memo),
        ledger.cr("tax_payable", ln.tax_cents, memo),
    ]
    return credits


def _mirror(lines: list[ledger.Line]) -> list[ledger.Line]:
    return [ledger.Line(x.account_code, debit=x.credit, credit=x.debit, memo=x.memo, owner_user_id=x.owner_user_id)
            for x in lines]


def reverse_earning_rows(db: Session, rows: list[Earning], journal_id: uuid.UUID) -> None:
    """Reverse earnings in full: unpaid ones are cancelled, paid ones clawed back."""
    adjust_earnings(db, {e.id: e.amount_cents + _adjusted(db, e) for e in rows if e.amount_cents > 0}, journal_id)


def _adjusted(db: Session, e: Earning) -> int:
    """Sum of negative adjustments already made against an earning."""
    return db.scalar(select(func.coalesce(func.sum(Earning.amount_cents), 0)).where(
        Earning.reverses_earning_id == e.id)) or 0


def adjust_earnings(db: Session, amounts: dict[uuid.UUID, int], journal_id: uuid.UUID) -> None:
    """Record negative adjustments against earnings (refunds, chargebacks).

    The original earning is never edited. An adjustment against an unpaid
    earning keeps its status and release date, so both release together; an
    adjustment against a paid earning is available immediately and nets
    against the payee's next payout (a clawback)."""
    now = utcnow()
    for earning_id, amount in amounts.items():
        if amount <= 0:
            continue
        e = db.get(Earning, earning_id)
        unpaid = e.status in (EarningStatus.pending, EarningStatus.available)
        db.add(Earning(payee_user_id=e.payee_user_id, kind=e.kind, order_line_id=e.order_line_id,
                       milestone_id=e.milestone_id, amount_cents=-amount, currency=e.currency,
                       status=e.status if unpaid else EarningStatus.available,
                       available_at=e.available_at if unpaid else now, journal_id=journal_id,
                       reverses_earning_id=e.id))


def _update_order_status(order: Order) -> None:
    statuses = {ln.status for ln in order.lines}
    if statuses == {OrderLineStatus.refunded}:
        order.status = OrderStatus.refunded
    elif OrderLineStatus.disputed in statuses:
        order.status = OrderStatus.disputed
    elif OrderLineStatus.refunded in statuses or any(ln.refunded_cents for ln in order.lines):
        order.status = OrderStatus.partially_refunded
    else:
        order.status = OrderStatus.paid


def _line_reversed_so_far(db: Session, ln: OrderLine) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in db.scalars(select(Refund).where(Refund.order_line_id == ln.id)):
        for code, amount in (r.allocation or {}).items():
            out[code] = out.get(code, 0) + amount
    return out


def _reverse_line(db: Session, ln: OrderLine, amount: int, kind: JournalKind, key: str, memo: str,
                  actor_id=None) -> tuple[uuid.UUID, dict[str, int]]:
    """Post a journal returning ``amount`` (price + tax) of a line to clearing.

    Each credited account is reversed in proportion to what is still
    outstanding on it; the last refund therefore reverses exactly the
    remainder. Earnings get matching negative adjustments."""
    credits = _line_credits(db, ln)
    already = _line_reversed_so_far(db, ln)
    codes = [c.account_code for c in credits]
    remaining = [c.credit - already.get(c.account_code, 0) for c in credits]
    if amount > sum(remaining):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Refund exceeds the amount still refundable on this line")
    parts = remaining if amount == sum(remaining) else prorate(amount, remaining)
    allocation = {code: part for code, part in zip(codes, parts, strict=True) if part}
    owners = {c.account_code: c.owner_user_id for c in credits}
    entries = [ledger.dr(code, part, memo, owners[code]) for code, part in allocation.items()]
    entries.append(ledger.cr(f"clearing:{ln.order.provider}", amount, memo))
    journal = ledger.post(db, kind, key, "order_line", ln.id, memo, ln.currency, entries, created_by=actor_id)
    adjust_earnings(db, spread_over_earnings(db, list(db.scalars(
        select(Earning).where(Earning.order_line_id == ln.id))), allocation), journal.id)
    return journal.id, allocation


PAYABLE_FAMILY = {
    EarningKind.stock_license: "creator_payable",
    EarningKind.service_milestone: "creator_payable",
    EarningKind.gallery_sale: "creator_payable",
    EarningKind.affiliate_commission: "affiliate_payable",
    EarningKind.referral_bonus: "affiliate_payable",
}


def spread_over_earnings(db: Session, rows: list[Earning], allocation: dict[str, int]) -> dict[uuid.UUID, int]:
    """Map reversed payable amounts ({account code: cents}) onto the earnings
    that still have an outstanding balance, newest first."""
    out: dict[uuid.UUID, int] = {}
    originals = sorted((e for e in rows if e.amount_cents > 0 and e.reverses_earning_id is None),
                       key=lambda e: e.created_at, reverse=True)
    for code, amount in allocation.items():
        for e in originals:
            if amount <= 0:
                break
            if f"{PAYABLE_FAMILY[e.kind]}:{e.payee_user_id}" != code:
                continue
            take = min(amount, e.amount_cents + _adjusted(db, e) - out.get(e.id, 0))
            if take > 0:
                out[e.id] = out.get(e.id, 0) + take
                amount -= take
    return out


def refund_line(db: Session, provider: PaymentProvider | None, ln: OrderLine, reason: RefundReason, note: str,
                actor_id: uuid.UUID | None, provider_refund_id: str | None = None,
                amount_cents: int | None = None) -> Refund:
    """Refund a fulfilled line, fully (default) or partially (``amount_cents``,
    price + tax). ``provider=None`` records a refund that already happened at
    the provider (e.g. issued in the Stripe dashboard). The license is revoked
    only once the line is fully refunded."""
    if ln.status is not OrderLineStatus.fulfilled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only fulfilled lines can be refunded")
    order = ln.order
    refundable = ln.unit_price_cents + ln.tax_cents - ln.refunded_cents
    amount = refundable if amount_cents is None else amount_cents
    if amount <= 0 or amount > refundable:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Refund must be between 0.01 and {refundable / 100:.2f}")
    seq = db.scalar(select(func.count(Refund.id)).where(Refund.order_line_id == ln.id)) or 0
    key = f"refund:{ln.id}" if seq == 0 else f"refund:{ln.id}:{seq}"
    if provider is not None:
        provider_refund_id = provider.refund(payment_id=order.provider_payment_id, amount_cents=amount,
                                             idempotency_key=key,
                                             metadata={"order_id": str(order.id), "line_id": str(ln.id)})
    journal_id, allocation = _reverse_line(db, ln, amount, JournalKind.refund, key, f"Refund line {ln.id}", actor_id)
    ln.refunded_cents += amount
    if ln.refunded_cents >= ln.unit_price_cents + ln.tax_cents:
        grant = db.get(RightsGrant, ln.rights_grant_id)
        grant.status, grant.revoked_at = GrantStatus.refunded, utcnow()
        grant.revocation_reason = f"Refunded: {reason.value}"
        ln.status = OrderLineStatus.refunded
    _update_order_status(order)
    refund = Refund(order_id=order.id, order_line_id=ln.id, amount_cents=amount, currency=ln.currency, reason=reason,
                    note=note, provider_refund_id=provider_refund_id, journal_id=journal_id, initiated_by=actor_id,
                    allocation=allocation)
    db.add(refund)
    audit.record(db, "order.refunded", actor_id, "order_line", ln.id, amount=amount, reason=reason.value,
                 partial=ln.status is not OrderLineStatus.refunded)
    db.flush()
    return refund


def dispute_order(db: Session, order: Order, dispute_id: str, dispute_fee: int) -> None:
    """A chargeback pulls the money back: reverse what remains on every
    fulfilled line and suspend its license."""
    if order.purpose is OrderPurpose.milestone:
        from app.services.production_service import chargeback_milestone

        chargeback_milestone(db, order, dispute_id)
    elif order.purpose is OrderPurpose.gallery:
        from app.services.gallery_commerce import chargeback_gallery_order

        chargeback_gallery_order(db, order, dispute_id)
    for ln in order.lines:
        if ln.status is not OrderLineStatus.fulfilled:
            continue
        outstanding = ln.unit_price_cents + ln.tax_cents - ln.refunded_cents
        _reverse_line(db, ln, outstanding, JournalKind.dispute, f"dispute:{dispute_id}:{ln.id}",
                      f"Chargeback {dispute_id}")
        grant = db.get(RightsGrant, ln.rights_grant_id)
        grant.status, grant.revoked_at, grant.revocation_reason = GrantStatus.revoked, utcnow(), "Payment disputed"
        ln.status = OrderLineStatus.disputed
    if dispute_fee:
        ledger.post(db, JournalKind.dispute, f"dispute-fee:{dispute_id}", "order", order.id, f"Dispute fee {dispute_id}",
                    order.currency, [ledger.dr("refund_losses", dispute_fee, dispute_id),
                                     ledger.cr(f"clearing:{order.provider}", dispute_fee, dispute_id)])
    if order.lines:
        _update_order_status(order)
    audit.record(db, "order.disputed", None, "order", order.id, dispute=dispute_id)


def reinstate_dispute(db: Session, order: Order, dispute_id: str) -> None:
    """Dispute won: the funds come back, so restore exactly what the chargeback
    reversed (ledger, earnings with a fresh hold, licenses)."""
    if order.purpose is OrderPurpose.milestone:
        from app.services.production_service import reinstate_milestone

        reinstate_milestone(db, order, dispute_id)
        return
    if order.purpose is OrderPurpose.gallery:
        from app.services.gallery_commerce import reinstate_gallery_order

        reinstate_gallery_order(db, order, dispute_id)
        return
    settings = get_settings()
    for ln in order.lines:
        if ln.status is not OrderLineStatus.disputed:
            continue
        reversed_journal = db.scalar(select(LedgerJournal).where(
            LedgerJournal.idempotency_key == f"dispute:{dispute_id}:{ln.id}"))
        entries = [ledger.Line(e.account.code, debit=e.credit_cents, credit=e.debit_cents, memo=f"dispute won {dispute_id}",
                               owner_user_id=e.account.owner_user_id) for e in reversed_journal.entries]
        journal = ledger.post(db, JournalKind.dispute_reinstated, f"dispute-won:{dispute_id}:{ln.id}", "order_line",
                              ln.id, f"Dispute won {dispute_id}", ln.currency, entries)
        available_at = utcnow() + timedelta(days=settings.earnings_hold_days)
        for e in reversed_journal.entries:
            family, _, payee = e.account.code.partition(":")
            if family in ("creator_payable", "affiliate_payable") and e.debit_cents:
                kind = EarningKind.stock_license if family == "creator_payable" else EarningKind.affiliate_commission
                db.add(Earning(payee_user_id=uuid.UUID(payee), kind=kind, order_line_id=ln.id,
                               amount_cents=e.debit_cents, currency=ln.currency, status=EarningStatus.pending,
                               available_at=available_at, journal_id=journal.id))
        grant = db.get(RightsGrant, ln.rights_grant_id)
        grant.status, grant.revoked_at, grant.revocation_reason = GrantStatus.active, None, None
        ln.status = OrderLineStatus.fulfilled
    _update_order_status(order)
    audit.record(db, "order.dispute_won", None, "order", order.id, dispute=dispute_id)


# --- Provider events (webhooks) -------------------------------------------------------------

def _order_for(db: Session, obj: dict) -> Order | None:
    meta = obj.get("metadata") or {}
    if meta.get("order_id"):
        try:
            return db.get(Order, uuid.UUID(meta["order_id"]))
        except ValueError:
            return None
    if obj.get("object") == "checkout.session" or str(obj.get("id", "")).startswith(("cs_", "fake_cs_")):
        return db.scalar(select(Order).where(Order.provider_session_id == obj.get("id")))
    payment_id = obj.get("payment_intent")
    if isinstance(payment_id, dict):
        payment_id = payment_id.get("id")
    if payment_id:
        return db.scalar(select(Order).where(Order.provider_payment_id == payment_id))
    return None


def handle_event(db: Session, provider: PaymentProvider, event: ProviderEvent) -> str:
    """Process one provider event exactly once. Returns a short outcome string."""
    record = db.scalar(select(FinancialEvent).where(FinancialEvent.provider == provider.name,
                                                    FinancialEvent.provider_event_id == event.id))
    if record and record.processed_at is not None:
        return "duplicate"
    if not record:
        record = FinancialEvent(provider=provider.name, provider_event_id=event.id, event_type=event.type,
                                payload=event.data)
        db.add(record)
        db.flush()
    record.processing_error = None
    obj = event.data
    outcome = "ignored"
    try:
        with db.begin_nested():
            if event.type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
                order = _order_for(db, obj)
                if order and obj.get("payment_status") == "paid":
                    details = provider.payment_details(order.provider_session_id)
                    if order.purpose is OrderPurpose.milestone:
                        from app.services.production_service import fund_from_payment

                        fund_from_payment(db, order, details, provider)
                        outcome = "milestone_funded"
                    elif order.purpose is OrderPurpose.gallery:
                        from app.services.gallery_commerce import fulfill as fulfill_gallery

                        fulfill_gallery(db, order, details)
                        outcome = "gallery_paid"
                    else:
                        fulfill_order(db, order, details)
                        outcome = "fulfilled"
            elif event.type in ("checkout.session.expired", "checkout.session.async_payment_failed"):
                order = _order_for(db, obj)
                if order and order.status is OrderStatus.pending:
                    order.status = OrderStatus.canceled
                    outcome = "canceled"
            elif event.type == "charge.refunded":
                outcome = _external_refund(db, obj)
            elif event.type == "charge.dispute.created":
                order = _order_for(db, obj)
                if order:
                    fee = sum(int(t.get("fee", 0)) for t in obj.get("balance_transactions") or [])
                    dispute_order(db, order, obj["id"], fee)
                    outcome = "disputed"
            elif event.type == "charge.dispute.closed":
                order = _order_for(db, obj)
                if order and obj.get("status") == "won":
                    reinstate_dispute(db, order, obj["id"])
                    outcome = "dispute_won"
            elif event.type == "account.updated":
                outcome = sync_account(db, obj)
            elif event.type == "transfer.reversed":
                from app.services.payout_service import transfer_reversed

                outcome = transfer_reversed(db, obj.get("id"))
        record.processed_at = utcnow()
    except Exception as exc:  # noqa: BLE001 - keep the event, surface the error to finance
        log.exception("payment event %s failed", event.id)
        record.processing_error = str(exc)[:2000]
        outcome = "error"
    return outcome


def _external_refund(db: Session, charge: dict) -> str:
    """A refund created outside the platform (e.g. in the Stripe dashboard).

    The newly refunded amount (provider total minus what we already recorded)
    is spread across the order's refundable lines in proportion to what each
    can still refund, so partial refunds are booked automatically."""
    order = _order_for(db, charge)
    if not order:
        return "ignored"
    recorded = sum(r.amount_cents for r in db.scalars(select(Refund).where(Refund.order_id == order.id)))
    delta = int(charge.get("amount_refunded", 0)) - recorded
    if delta <= 0:
        return "already_recorded"
    if order.purpose is OrderPurpose.milestone:
        from app.services.production_service import external_milestone_refund

        external_milestone_refund(db, order, delta)
        return "refunded"
    if order.purpose is OrderPurpose.gallery:
        from app.services.gallery_commerce import refund_gallery_order

        refund_gallery_order(db, None, order, delta, RefundReason.other, "Refund issued at the payment provider", None)
        return "refunded"
    lines = [ln for ln in order.lines if ln.status is OrderLineStatus.fulfilled]
    capacity = [ln.unit_price_cents + ln.tax_cents - ln.refunded_cents for ln in lines]
    if delta > sum(capacity):
        raise ValueError(f"provider refunded {delta} on order {order.id}, more than is refundable")
    for ln, part in zip(lines, prorate(delta, capacity), strict=True):
        if part:
            refund_line(db, None, ln, RefundReason.other, "Refund issued at the payment provider", None,
                        amount_cents=part)
    return "refunded"


def sync_account(db: Session, acct: dict) -> str:
    from app.services.payments.stripe_provider import StripeProvider

    row = db.scalar(select(PayoutAccount).where(PayoutAccount.provider_account_id == acct.get("id")))
    if not row:
        return "ignored"
    apply_account_state(row, StripeProvider.state_from_account(acct))
    return "account_updated"


def apply_account_state(row: PayoutAccount, state) -> None:
    row.details_submitted, row.payouts_enabled = state.details_submitted, state.payouts_enabled
    row.country, row.requirements_due = state.country or row.country, state.requirements_due
    if state.payouts_enabled:
        row.status = PayoutAccountStatus.enabled
    elif state.details_submitted:
        row.status = PayoutAccountStatus.restricted
    else:
        row.status = PayoutAccountStatus.onboarding
