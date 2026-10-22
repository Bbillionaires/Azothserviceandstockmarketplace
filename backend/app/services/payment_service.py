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
from sqlalchemy import select
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
    for ln, tax, fee in zip(order.lines, prorate(order.tax_cents, weights), prorate(order.processing_fee_cents, weights),
                            strict=True):
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
    """Reverse unpaid earnings; claw back paid ones with a negative earning."""
    now = utcnow()
    for e in rows:
        if e.status is EarningStatus.reversed or e.amount_cents <= 0:
            continue
        already_clawed = db.scalar(select(Earning.id).where(Earning.reverses_earning_id == e.id))
        if e.status in (EarningStatus.pending, EarningStatus.available):
            e.status = EarningStatus.reversed
        elif e.status is EarningStatus.paid and not already_clawed:
            db.add(Earning(payee_user_id=e.payee_user_id, kind=e.kind, order_line_id=e.order_line_id,
                           milestone_id=e.milestone_id, amount_cents=-e.amount_cents, currency=e.currency,
                           status=EarningStatus.available, available_at=now, journal_id=journal_id,
                           reverses_earning_id=e.id))


def _reverse_earnings(db: Session, ln: OrderLine, journal_id: uuid.UUID) -> None:
    reverse_earning_rows(db, list(db.scalars(select(Earning).where(Earning.order_line_id == ln.id))), journal_id)


def _update_order_status(order: Order) -> None:
    statuses = {ln.status for ln in order.lines}
    if statuses == {OrderLineStatus.refunded}:
        order.status = OrderStatus.refunded
    elif OrderLineStatus.disputed in statuses:
        order.status = OrderStatus.disputed
    elif OrderLineStatus.refunded in statuses:
        order.status = OrderStatus.partially_refunded
    else:
        order.status = OrderStatus.paid


def refund_line(db: Session, provider: PaymentProvider | None, ln: OrderLine, reason: RefundReason, note: str,
                actor_id: uuid.UUID | None, provider_refund_id: str | None = None) -> Refund:
    """Refund one fulfilled line in full. ``provider=None`` records a refund
    that already happened at the provider (e.g. issued in the Stripe dashboard)."""
    if ln.status is not OrderLineStatus.fulfilled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only fulfilled lines can be refunded")
    order = ln.order
    amount = ln.unit_price_cents + ln.tax_cents
    if provider is not None:
        provider_refund_id = provider.refund(payment_id=order.provider_payment_id, amount_cents=amount,
                                             idempotency_key=f"refund:{ln.id}",
                                             metadata={"order_id": str(order.id), "line_id": str(ln.id)})
    entries = _mirror(_line_credits(db, ln)) + [ledger.cr(f"clearing:{order.provider}", amount, f"refund line {ln.id}")]
    journal = ledger.post(db, JournalKind.refund, f"refund:{ln.id}", "order_line", ln.id, f"Refund {ln.id}",
                          ln.currency, entries, created_by=actor_id)
    _reverse_earnings(db, ln, journal.id)
    grant = db.get(RightsGrant, ln.rights_grant_id)
    grant.status, grant.revoked_at, grant.revocation_reason = GrantStatus.refunded, utcnow(), f"Refunded: {reason.value}"
    ln.status = OrderLineStatus.refunded
    _update_order_status(order)
    refund = Refund(order_id=order.id, order_line_id=ln.id, amount_cents=amount, currency=ln.currency, reason=reason,
                    note=note, provider_refund_id=provider_refund_id, journal_id=journal.id, initiated_by=actor_id)
    db.add(refund)
    audit.record(db, "order.refunded", actor_id, "order_line", ln.id, amount=amount, reason=reason.value)
    db.flush()
    return refund


def dispute_order(db: Session, order: Order, dispute_id: str, dispute_fee: int) -> None:
    """A chargeback pulls the money back: reverse every fulfilled line and suspend its license."""
    if order.purpose is OrderPurpose.milestone:
        from app.services.production_service import chargeback_milestone

        chargeback_milestone(db, order, dispute_id)
    for ln in order.lines:
        if ln.status is not OrderLineStatus.fulfilled:
            continue
        amount = ln.unit_price_cents + ln.tax_cents
        entries = _mirror(_line_credits(db, ln)) + [ledger.cr(f"clearing:{order.provider}", amount, f"dispute {dispute_id}")]
        journal = ledger.post(db, JournalKind.dispute, f"dispute:{dispute_id}:{ln.id}", "order_line", ln.id,
                              f"Chargeback {dispute_id}", ln.currency, entries)
        _reverse_earnings(db, ln, journal.id)
        grant = db.get(RightsGrant, ln.rights_grant_id)
        grant.status, grant.revoked_at, grant.revocation_reason = GrantStatus.revoked, utcnow(), "Payment disputed"
        ln.status = OrderLineStatus.disputed
    if dispute_fee:
        ledger.post(db, JournalKind.dispute, f"dispute-fee:{dispute_id}", "order", order.id, f"Dispute fee {dispute_id}",
                    order.currency, [ledger.dr("refund_losses", dispute_fee, dispute_id),
                                     ledger.cr(f"clearing:{order.provider}", dispute_fee, dispute_id)])
    _update_order_status(order)
    audit.record(db, "order.disputed", None, "order", order.id, dispute=dispute_id)


def reinstate_dispute(db: Session, order: Order, dispute_id: str) -> None:
    """Dispute won: the funds come back, so restore the allocation and licenses."""
    if order.purpose is OrderPurpose.milestone:
        raise ValueError(f"dispute {dispute_id} won on milestone order {order.id}: "
                         "re-fund the milestone manually with finance review")
    settings = get_settings()
    for ln in order.lines:
        if ln.status is not OrderLineStatus.disputed:
            continue
        amount = ln.unit_price_cents + ln.tax_cents
        entries = [ledger.dr(f"clearing:{order.provider}", amount, f"dispute won {dispute_id}"), *_line_credits(db, ln)]
        journal = ledger.post(db, JournalKind.dispute_reinstated, f"dispute-won:{dispute_id}:{ln.id}", "order_line",
                              ln.id, f"Dispute won {dispute_id}", ln.currency, entries)
        alloc = db.scalar(select(RoyaltyAllocation).where(RoyaltyAllocation.order_line_id == ln.id))
        creator = db.get(CreatorProfile, ln.creator_id)
        available_at = utcnow() + timedelta(days=settings.earnings_hold_days)
        for payee, kind, amount in ((creator.user_id, EarningKind.stock_license, alloc.creator_pool_cents),
                                    (order.affiliate_user_id, EarningKind.affiliate_commission, alloc.affiliate_cents)):
            if amount:
                db.add(Earning(payee_user_id=payee, kind=kind, order_line_id=ln.id, amount_cents=amount,
                               currency=ln.currency, status=EarningStatus.pending, available_at=available_at,
                               journal_id=journal.id))
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

                        fund_from_payment(db, order, details)
                        outcome = "milestone_funded"
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
    """A refund created outside the platform (e.g. Stripe dashboard).

    Full refunds are recorded line by line. Partial refunds cannot be mapped to
    a royalty reversal automatically and are flagged for finance review."""
    order = _order_for(db, charge)
    if not order:
        return "ignored"
    if order.purpose is OrderPurpose.milestone:
        recorded = sum(r.amount_cents for r in db.scalars(select(Refund).where(Refund.order_id == order.id)))
        if int(charge.get("amount_refunded", 0)) <= recorded:
            return "already_recorded"
        raise ValueError(f"provider-side refund on milestone order {order.id} needs manual review")
    open_lines = [ln for ln in order.lines if ln.status is OrderLineStatus.fulfilled]
    recorded = sum(r.amount_cents for r in db.scalars(select(Refund).where(Refund.order_id == order.id)))
    refunded = int(charge.get("amount_refunded", 0))
    if refunded <= recorded:
        return "already_recorded"
    if refunded >= int(charge.get("amount", 0)) and open_lines:
        for ln in open_lines:
            refund_line(db, None, ln, RefundReason.other, "Refund issued at the payment provider", None,
                        provider_refund_id=None)
        return "refunded"
    raise ValueError(f"partial provider-side refund of {refunded} on order {order.id} needs manual review")


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
