"""Basic referral program: one code per user, direct attribution only.

Commission rate comes from the revenue-share rule (``affiliate_bps_of_platform``)
and is always paid from the platform share. There are no multi-level
commissions. Fraud controls:

* self-referral is impossible (the code owner cannot be the new account);
* referrers must be active, email-verified accounts;
* more than ``MAX_PER_IP`` sign-ups from the same IP for one referrer within
  24 hours are recorded but rejected for commission;
* commissions sit in the same hold period as creator earnings and are clawed
  back automatically on refund or chargeback.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Referral, ReferralCode, ReferralStatus, RoleCode, User, UserStatus
from app.services import audit

CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
MAX_PER_IP = 3


def get_or_create_code(db: Session, user: User) -> ReferralCode:
    from app.api.v1.auth import grant_role

    code = db.scalar(select(ReferralCode).where(ReferralCode.user_id == user.id))
    if code:
        return code
    while True:
        candidate = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        if not db.scalar(select(ReferralCode.id).where(ReferralCode.code == candidate)):
            break
    code = ReferralCode(user_id=user.id, code=candidate)
    db.add(code)
    grant_role(db, user, RoleCode.affiliate)
    audit.record(db, "referral.code_created", user.id, "referral_code", None, code=candidate)
    db.flush()
    return code


def attribute_signup(db: Session, new_user: User, code: str | None, ip: str | None) -> Referral | None:
    if not code:
        return None
    rc = db.scalar(select(ReferralCode).where(ReferralCode.code == code.strip().lower()))
    if not rc or rc.user_id == new_user.id:
        return None
    referrer = db.get(User, rc.user_id)
    if not referrer or referrer.status is not UserStatus.active or not referrer.email_verified_at:
        return None
    flags: list[str] = []
    if ip:
        recent = db.scalar(select(func.count(Referral.id)).where(
            Referral.referrer_user_id == referrer.id, Referral.signup_ip == ip,
            Referral.created_at > datetime.now(UTC) - timedelta(hours=24)))
        if recent >= MAX_PER_IP:
            flags.append("ip_velocity")
    ref = Referral(
        referrer_user_id=referrer.id, referred_user_id=new_user.id, code=rc.code,
        status=ReferralStatus.rejected if flags else ReferralStatus.active, fraud_flags=flags, signup_ip=ip,
        attributed_until=datetime.now(UTC) + timedelta(days=get_settings().referral_attribution_days),
    )
    db.add(ref)
    audit.record(db, "referral.attributed", new_user.id, "user", new_user.id, referrer=referrer.id, flags=flags)
    return ref


CREATOR_EARNING_KINDS = ("stock_license", "service_milestone", "gallery_sale")


def maybe_pay_creator_bonus(db: Session, earning) -> bool:
    """Pay the referrer's one-time creator-recruitment bonus.

    Called when an earning clears its hold. Qualifies once per referral: the
    payee was referred (active, within the attribution window, not flagged)
    and this is a positive creator earning. Funded by the platform
    (``referral_bonuses`` expense), never from creator money."""
    from app.models import Earning, EarningKind, EarningStatus, JournalKind
    from app.services import ledger
    from app.services.notify import notify

    amount = get_settings().referral_creator_bonus_cents
    if amount <= 0 or earning.amount_cents <= 0 or earning.kind.value not in CREATOR_EARNING_KINDS:
        return False
    ref = db.scalar(select(Referral).where(Referral.referred_user_id == earning.payee_user_id))
    if not ref or ref.status is not ReferralStatus.active or ref.creator_bonus_paid_at is not None:
        return False
    until = ref.attributed_until.replace(tzinfo=UTC) if ref.attributed_until.tzinfo is None else ref.attributed_until
    created = earning.created_at if earning.created_at.tzinfo else earning.created_at.replace(tzinfo=UTC)
    if created > until:
        return False
    referrer = db.get(User, ref.referrer_user_id)
    if not referrer or referrer.status is not UserStatus.active:
        return False
    journal = ledger.post(db, JournalKind.referral_bonus, f"creator-bonus:{ref.id}", "referral", ref.id,
                          "Creator recruitment bonus", earning.currency, [
                              ledger.dr("referral_bonuses", amount, f"referral {ref.id}"),
                              ledger.cr(ledger.affiliate_payable(referrer.id), amount, f"referral {ref.id}", referrer.id),
                          ])
    db.add(Earning(payee_user_id=referrer.id, kind=EarningKind.referral_bonus, amount_cents=amount,
                   currency=earning.currency, status=EarningStatus.available, available_at=datetime.now(UTC),
                   journal_id=journal.id))
    ref.creator_bonus_paid_at = datetime.now(UTC)
    notify(db, referrer.id, "referral_bonus", f"You earned a {amount / 100:,.2f} {earning.currency} referral bonus",
           "A creator you referred made their first sale.", "/dashboard?tab=earnings", send_email=True)
    audit.record(db, "referral.creator_bonus", None, "referral", ref.id, amount=amount)
    return True
