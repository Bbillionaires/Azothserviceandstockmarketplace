"""Double-entry ledger.

Chart of accounts (one row per code and currency):

| Code                         | Type      | Meaning                                         |
|------------------------------|-----------|-------------------------------------------------|
| ``clearing:<provider>``      | asset     | Money held in the payment provider balance       |
| ``tax_payable``              | liability | Sales tax / VAT collected for remittance         |
| ``creator_payable:<user>``   | liability | Owed to a creator, not yet transferred           |
| ``affiliate_payable:<user>`` | liability | Owed to a referral partner, not yet transferred  |
| ``client_funds_held``        | liability | Milestone payments awaiting client approval      |
| ``platform_revenue``         | revenue   | Platform share net of affiliate commission       |
| ``fee_recovery``             | revenue   | Processing fees deducted from net revenue        |
| ``processing_fees``          | expense   | Fees charged by the payment provider             |
| ``refund_losses``            | expense   | Fees and amounts the platform absorbs on refunds |

Journals are written once and never edited. ``post`` refuses an unbalanced
journal, and a repeated ``idempotency_key`` returns the existing journal
instead of posting twice.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AccountType, JournalKind, LedgerAccount, LedgerEntry, LedgerJournal

ACCOUNT_TYPES = {
    "clearing": AccountType.asset,
    "tax_payable": AccountType.liability,
    "creator_payable": AccountType.liability,
    "affiliate_payable": AccountType.liability,
    "client_funds_held": AccountType.liability,
    "platform_revenue": AccountType.revenue,
    "fee_recovery": AccountType.revenue,
    "processing_fees": AccountType.expense,
    "refund_losses": AccountType.expense,
    "referral_bonuses": AccountType.expense,
}


class LedgerError(ValueError):
    pass


@dataclass(frozen=True)
class Line:
    account_code: str
    debit: int = 0
    credit: int = 0
    memo: str = ""
    owner_user_id: uuid.UUID | None = None


def dr(code: str, amount: int, memo: str = "", owner: uuid.UUID | None = None) -> Line:
    return Line(code, debit=amount, memo=memo, owner_user_id=owner)


def cr(code: str, amount: int, memo: str = "", owner: uuid.UUID | None = None) -> Line:
    return Line(code, credit=amount, memo=memo, owner_user_id=owner)


def creator_payable(user_id: uuid.UUID) -> str:
    return f"creator_payable:{user_id}"


def affiliate_payable(user_id: uuid.UUID) -> str:
    return f"affiliate_payable:{user_id}"


def account(db: Session, code: str, currency: str, owner_user_id: uuid.UUID | None = None) -> LedgerAccount:
    acct = db.scalar(select(LedgerAccount).where(LedgerAccount.code == code, LedgerAccount.currency == currency))
    if acct:
        return acct
    prefix = code.split(":", 1)[0]
    if prefix not in ACCOUNT_TYPES:
        raise LedgerError(f"unknown account family: {prefix}")
    acct = LedgerAccount(code=code, name=code.replace("_", " "), account_type=ACCOUNT_TYPES[prefix],
                         owner_user_id=owner_user_id, currency=currency)
    db.add(acct)
    db.flush()
    return acct


def post(
    db: Session,
    kind: JournalKind,
    idempotency_key: str,
    reference_type: str,
    reference_id,
    description: str,
    currency: str,
    lines: list[Line],
    created_by: uuid.UUID | None = None,
) -> LedgerJournal:
    existing = db.scalar(select(LedgerJournal).where(LedgerJournal.idempotency_key == idempotency_key))
    if existing:
        return existing
    lines = [ln for ln in lines if ln.debit or ln.credit]
    for ln in lines:
        if ln.debit < 0 or ln.credit < 0 or (ln.debit and ln.credit):
            raise LedgerError(f"invalid line for {ln.account_code}")
    debits, credits = sum(ln.debit for ln in lines), sum(ln.credit for ln in lines)
    if not lines or debits != credits:
        raise LedgerError(f"unbalanced journal {idempotency_key}: debits {debits} != credits {credits}")
    journal = LedgerJournal(kind=kind, idempotency_key=idempotency_key, reference_type=reference_type,
                            reference_id=str(reference_id), description=description[:300], currency=currency,
                            created_by=created_by)
    db.add(journal)
    db.flush()
    for ln in lines:
        acct = account(db, ln.account_code, currency, ln.owner_user_id)
        db.add(LedgerEntry(journal_id=journal.id, account_id=acct.id, debit_cents=ln.debit,
                           credit_cents=ln.credit, memo=ln.memo[:300]))
    db.flush()
    return journal


def balance(db: Session, code: str, currency: str) -> int:
    """Natural-side balance: credit-normal for liabilities and revenue,
    debit-normal for assets and expenses."""
    acct = db.scalar(select(LedgerAccount).where(LedgerAccount.code == code, LedgerAccount.currency == currency))
    if not acct:
        return 0
    debit, credit = db.execute(
        select(func.coalesce(func.sum(LedgerEntry.debit_cents), 0), func.coalesce(func.sum(LedgerEntry.credit_cents), 0))
        .where(LedgerEntry.account_id == acct.id)
    ).one()
    if acct.account_type in (AccountType.asset, AccountType.expense):
        return debit - credit
    return credit - debit


def unbalanced_journals(db: Session) -> list[str]:
    rows = db.execute(
        select(LedgerJournal.idempotency_key)
        .join(LedgerEntry, LedgerEntry.journal_id == LedgerJournal.id)
        .group_by(LedgerJournal.id, LedgerJournal.idempotency_key)
        .having(func.sum(LedgerEntry.debit_cents) != func.sum(LedgerEntry.credit_cents))
    ).all()
    return [r[0] for r in rows]
