"""Creator and affiliate earnings, statements, payout onboarding, referrals."""

import csv
import io
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.deps import current_user, verified_user
from app.models import (
    Earning,
    EarningStatus,
    LicenseType,
    MediaAsset,
    Milestone,
    Order,
    OrderLine,
    OrderStatus,
    Payout,
    PayoutAccount,
    Referral,
    ReferralCode,
    ReferralStatus,
    RevenueShareRule,
    RoyaltyAllocation,
    User,
)
from app.schemas.commerce import EarningOut, EarningsSummary, OnboardIn, PayoutOut
from app.schemas.common import Page
from app.services import audit
from app.services.payment_service import apply_account_state
from app.services.payments import PaymentProviderError, get_provider
from app.services.payout_service import balances_for
from app.services.referral_service import get_or_create_code

router = APIRouter(tags=["earnings"])


def _account_out(acct: PayoutAccount | None) -> dict | None:
    if not acct:
        return None
    return {"status": acct.status.value, "payouts_enabled": acct.payouts_enabled,
            "details_submitted": acct.details_submitted, "requirements_due": acct.requirements_due,
            "country": acct.country}


@router.get("/earnings/summary", response_model=EarningsSummary)
def summary(currency: str = Query("USD", min_length=3, max_length=3), user: User = Depends(current_user),
            db: Session = Depends(get_db)):
    settings = get_settings()
    b = balances_for(db, user.id, currency.upper())
    next_release = db.scalar(select(func.min(Earning.available_at)).where(
        Earning.payee_user_id == user.id, Earning.status == EarningStatus.pending))
    acct = db.scalar(select(PayoutAccount).where(PayoutAccount.user_id == user.id))
    return EarningsSummary(currency=currency.upper(), pending_cents=b["pending"], available_cents=b["available"],
                           paid_cents=b["paid"], lifetime_cents=b["lifetime"], by_kind=b["by_kind"],
                           next_release_at=next_release, hold_days=settings.earnings_hold_days,
                           min_payout_cents=settings.min_payout_cents, payout_account=_account_out(acct))


def _earning_rows(db: Session, user: User, month: str | None, page: int, page_size: int):
    stmt = select(Earning).where(Earning.payee_user_id == user.id)
    if month:
        try:
            start = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "month must be YYYY-MM") from None
        end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
        stmt = stmt.where(Earning.created_at >= start, Earning.created_at < end)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Earning.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    out = []
    for e in rows:
        if e.order_line_id:
            line = db.get(OrderLine, e.order_line_id)
            asset = db.get(MediaAsset, line.asset_id)
            alloc = db.scalar(select(RoyaltyAllocation).where(RoyaltyAllocation.order_line_id == line.id))
            title, license_name, gross = (asset.title if asset else "",
                                          db.get(LicenseType, line.license_type_id).name, line.unit_price_cents)
            rule, explanation = (f"{alloc.rule_code} v{alloc.rule_version}" if alloc else ""), (alloc.explanation
                                                                                            if alloc else [])
        else:
            m = db.get(Milestone, e.milestone_id)
            project = m.project
            rule_row = db.get(RevenueShareRule, project.commission_rule_id)
            title, license_name, gross = f"{project.title}: {m.title}", "Custom production", m.released_cents
            rule = f"{rule_row.code} v{rule_row.version}"
            explanation = [f"Milestone released: {m.released_cents / 100:,.2f} {e.currency}",
                           f"Creator share ({rule_row.creator_bps / 100:g}%): {abs(e.amount_cents) / 100:,.2f}",
                           f"Rule: {rule}"]
        out.append({
            "id": e.id, "kind": e.kind.value, "status": e.status.value, "amount_cents": e.amount_cents,
            "currency": e.currency, "available_at": e.available_at, "created_at": e.created_at,
            "asset_title": title, "license_name": license_name, "gross_cents": gross, "rule": rule,
            "explanation": explanation, "is_clawback": e.amount_cents < 0,
        })
    return out, total


@router.get("/earnings", response_model=Page[EarningOut])
def list_earnings(month: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    items, total = _earning_rows(db, user, month, page, page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _cell(value) -> str:
    """Neutralize spreadsheet formula injection (titles are user-supplied)."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/earnings/statement.csv")
def statement(month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    items, _ = _earning_rows(db, user, month, 1, 100_000)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "type", "status", "media", "license", "gross", "your_amount", "currency", "rule",
                "available_on", "calculation"])
    for it in reversed(items):
        w.writerow([it["created_at"].date().isoformat(), it["kind"] + (" (clawback)" if it["is_clawback"] else ""),
                    it["status"], _cell(it["asset_title"]), _cell(it["license_name"]), f"{it['gross_cents'] / 100:.2f}",
                    f"{it['amount_cents'] / 100:.2f}", it["currency"], it["rule"],
                    it["available_at"].date().isoformat(), _cell(" | ".join(it["explanation"]))])
    w.writerow([])
    w.writerow(["total", "", "", "", "", "", f"{sum(i['amount_cents'] for i in items) / 100:.2f}"])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="statement-{month}.csv"'})


@router.get("/payouts", response_model=list[PayoutOut])
def my_payouts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Payout).where(Payout.payee_user_id == user.id).order_by(Payout.created_at.desc())
                      .limit(100)).all()


@router.get("/payouts/account")
def payout_account(user: User = Depends(current_user), db: Session = Depends(get_db)):
    acct = db.scalar(select(PayoutAccount).where(PayoutAccount.user_id == user.id))
    if acct:
        try:
            apply_account_state(acct, get_provider().account_state(acct.provider_account_id))
            db.commit()
        except PaymentProviderError:
            pass  # show the last known state
    return _account_out(acct)


@router.post("/payouts/account/onboard")
def onboard(body: OnboardIn, user: User = Depends(verified_user), db: Session = Depends(get_db)):
    """Create (once) the payee's connected account and return a hosted onboarding link."""
    provider = get_provider()
    settings = get_settings()
    acct = db.scalar(select(PayoutAccount).where(PayoutAccount.user_id == user.id))
    try:
        if not acct:
            account_id = provider.create_connected_account(email=user.email, country=body.country.upper(),
                                                           user_id=str(user.id))
            acct = PayoutAccount(user_id=user.id, provider=provider.name, provider_account_id=account_id,
                                 country=body.country.upper())
            db.add(acct)
            db.flush()
            audit.record(db, "payout.account_created", user.id, "payout_account", acct.id, provider=provider.name)
        url = provider.onboarding_link(acct.provider_account_id,
                                       refresh_url=f"{settings.public_web_url}/dashboard?tab=earnings&refresh=1",
                                       return_url=f"{settings.public_web_url}/dashboard?tab=earnings&onboarded=1")
        apply_account_state(acct, provider.account_state(acct.provider_account_id))
    except PaymentProviderError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Payment provider error: {exc}") from None
    db.commit()
    return {"url": url, "account": _account_out(acct)}


@router.post("/referrals/code")
def create_referral_code(user: User = Depends(verified_user), db: Session = Depends(get_db)):
    get_or_create_code(db, user)
    db.commit()
    return referral_stats(user, db)


@router.get("/referrals/me")
def referral_stats(user: User = Depends(current_user), db: Session = Depends(get_db)):
    code = db.scalar(select(ReferralCode).where(ReferralCode.user_id == user.id))
    referred = db.scalars(select(Referral).where(Referral.referrer_user_id == user.id)).all()
    active_ids = [r.referred_user_id for r in referred if r.status is ReferralStatus.active]
    buyers = db.scalar(select(func.count(func.distinct(Order.buyer_user_id))).where(
        Order.buyer_user_id.in_(active_ids), Order.affiliate_user_id == user.id,
        Order.status.in_([OrderStatus.paid, OrderStatus.partially_refunded]))) if active_ids else 0
    b = balances_for(db, user.id)
    return {
        "code": code.code if code else None,
        "link": f"{get_settings().public_web_url}/register?ref={code.code}" if code else None,
        "referred_accounts": len(referred),
        "rejected_referrals": sum(1 for r in referred if r.status is ReferralStatus.rejected),
        "paying_customers": buyers or 0,
        "commission_cents": b["by_kind"].get("affiliate_commission", 0),
        "terms": "Commission is a share of the platform's fee on purchases by customers you refer, for "
                 f"{get_settings().referral_attribution_days} days after they sign up. It never reduces creator "
                 "royalties and is reversed if the purchase is refunded.",
    }
