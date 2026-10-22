"""Royalty and revenue-split calculation engine.

Pure functions, no database access, so every rule is unit-testable and the
same code can be reused by the order pipeline, statements and admin previews.
All money is integer minor units (cents). Shares are basis points
(10_000 bps = 100%).

Calculation order (see docs/LICENSING_AND_ROYALTIES.md):

1. ``gross``           amount the buyer paid for the license line.
2. ``net``             gross minus the deductions the rule version lists
                       (taxes collected, payment processing fees, partner
                       distribution fees...). This is "net licensing revenue".
3. ``creator_pool``    net × creator share (initial-exclusive share for the
                       first transaction under a Model B agreement), rounded
                       half-up to the cent.
4. ``platform_share``  net − creator_pool (absorbs rounding, so the split
                       always reconciles exactly to net).
5. ``affiliate``       platform_share × affiliate bps, rounded down. Taken
                       from the platform share, never from the creator.
6. ``platform_net``    platform_share − affiliate.
7. Collaborators split ``creator_pool`` by their signed allocation using the
   largest-remainder method, so their parts sum exactly to the pool and the
   platform's share is unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

BPS_DENOMINATOR = 10_000

DEDUCTION_KEYS = (
    "taxes_collected",
    "payment_processing_fees",
    "partner_distribution_fees",
    "chargeback_fees",
)


class RoyaltyError(ValueError):
    pass


class Model(str, Enum):
    nonexclusive = "nonexclusive"  # Model A
    exclusive = "exclusive"  # Model B
    free = "free"  # Model C
    service = "service"  # custom production commission (creator keeps creator_bps)


@dataclass(frozen=True)
class ShareRule:
    """Snapshot of one ``RevenueShareRule`` version."""

    code: str
    version: int
    model: Model
    creator_bps: int
    initial_exclusive_creator_bps: int | None = None
    affiliate_bps_of_platform: int = 0
    net_revenue_deductions: tuple[str, ...] = ("taxes_collected", "payment_processing_fees")

    def __post_init__(self) -> None:
        for name in ("creator_bps", "affiliate_bps_of_platform"):
            _check_bps(name, getattr(self, name))
        if self.initial_exclusive_creator_bps is not None:
            _check_bps("initial_exclusive_creator_bps", self.initial_exclusive_creator_bps)
        unknown = set(self.net_revenue_deductions) - set(DEDUCTION_KEYS)
        if unknown:
            raise RoyaltyError(f"unknown deduction keys: {sorted(unknown)}")


@dataclass(frozen=True)
class Collaborator:
    party_id: str
    bps: int
    role: str = ""


@dataclass(frozen=True)
class RoyaltyInput:
    gross_cents: int
    rule: ShareRule
    creator_party_id: str
    currency: str = "USD"
    deductions: dict[str, int] = field(default_factory=dict)
    is_initial_exclusive_transaction: bool = False
    affiliate_party_id: str | None = None
    collaborators: tuple[Collaborator, ...] = ()


@dataclass(frozen=True)
class Allocation:
    party_type: str  # creator | platform | affiliate
    party_id: str
    amount_cents: int
    basis: str


@dataclass(frozen=True)
class RoyaltyResult:
    currency: str
    gross_cents: int
    deductions_applied: dict[str, int]
    net_cents: int
    creator_bps_applied: int
    creator_pool_cents: int
    platform_share_cents: int
    affiliate_cents: int
    platform_net_cents: int
    allocations: tuple[Allocation, ...]
    rule_code: str
    rule_version: int

    def explain(self) -> list[str]:
        """Human-readable calculation lines for statements and certificates."""
        lines = [f"Gross: {_fmt(self.gross_cents)} {self.currency}"]
        for key, amount in self.deductions_applied.items():
            lines.append(f"Less {key.replace('_', ' ')}: {_fmt(amount)}")
        lines += [
            f"Net licensing revenue: {_fmt(self.net_cents)}",
            f"Creator pool ({self.creator_bps_applied / 100:g}%): {_fmt(self.creator_pool_cents)}",
            f"Platform share: {_fmt(self.platform_share_cents)}",
        ]
        if self.affiliate_cents:
            lines.append(f"Affiliate commission (from platform share): {_fmt(self.affiliate_cents)}")
        lines.append(f"Platform net: {_fmt(self.platform_net_cents)}")
        lines += [f"  {a.party_type} {a.party_id}: {_fmt(a.amount_cents)} ({a.basis})" for a in self.allocations]
        lines.append(f"Rule: {self.rule_code} v{self.rule_version}")
        return lines


def calculate(inp: RoyaltyInput) -> RoyaltyResult:
    rule = inp.rule
    if inp.gross_cents < 0:
        raise RoyaltyError("gross must be non-negative; refunds are recorded as reversals")
    if rule.model is Model.free and inp.gross_cents != 0:
        raise RoyaltyError("free-media rule cannot be applied to a paid transaction")
    if inp.is_initial_exclusive_transaction and rule.model is not Model.exclusive:
        raise RoyaltyError("initial-exclusive pricing only applies to an exclusive rule")
    if any(v < 0 for v in inp.deductions.values()):
        raise RoyaltyError("deductions must be non-negative")
    unknown = set(inp.deductions) - set(DEDUCTION_KEYS)
    if unknown:
        raise RoyaltyError(f"unknown deduction keys: {sorted(unknown)}")

    applied = {k: inp.deductions[k] for k in rule.net_revenue_deductions if inp.deductions.get(k)}
    net = inp.gross_cents - sum(applied.values())
    if net < 0:
        raise RoyaltyError("deductions exceed gross")

    if inp.is_initial_exclusive_transaction:
        if rule.initial_exclusive_creator_bps is None:
            raise RoyaltyError("rule has no initial exclusive share configured")
        creator_bps = rule.initial_exclusive_creator_bps
    else:
        creator_bps = rule.creator_bps

    creator_pool = _mul_bps_half_up(net, creator_bps)
    platform_share = net - creator_pool

    affiliate = 0
    if inp.affiliate_party_id and rule.affiliate_bps_of_platform:
        affiliate = platform_share * rule.affiliate_bps_of_platform // BPS_DENOMINATOR
    platform_net = platform_share - affiliate

    allocations: list[Allocation] = []
    collaborators = inp.collaborators or (Collaborator(inp.creator_party_id, BPS_DENOMINATOR, "owner"),)
    for collab, amount in zip(collaborators, split_by_bps(creator_pool, [c.bps for c in collaborators]), strict=False):
        basis = f"{collab.bps / 100:g}% of creator pool" + (f" as {collab.role}" if collab.role else "")
        allocations.append(Allocation("creator", collab.party_id, amount, basis))
    if affiliate:
        allocations.append(
            Allocation(
                "affiliate",
                inp.affiliate_party_id or "",
                affiliate,
                f"{rule.affiliate_bps_of_platform / 100:g}% of platform share",
            )
        )
    allocations.append(Allocation("platform", "platform", platform_net, "platform share net of affiliate"))

    assert sum(a.amount_cents for a in allocations) == net, "allocations must reconcile to net"
    return RoyaltyResult(
        currency=inp.currency,
        gross_cents=inp.gross_cents,
        deductions_applied=applied,
        net_cents=net,
        creator_bps_applied=creator_bps,
        creator_pool_cents=creator_pool,
        platform_share_cents=platform_share,
        affiliate_cents=affiliate,
        platform_net_cents=platform_net,
        allocations=tuple(allocations),
        rule_code=rule.code,
        rule_version=rule.version,
    )


def split_by_bps(amount_cents: int, shares_bps: list[int]) -> list[int]:
    """Split an amount by basis-point shares that must total 100%.

    Largest-remainder method: every party gets the floor of its exact share,
    then leftover cents go to the largest fractional remainders (ties broken
    by input order). The parts always sum exactly to ``amount_cents``.
    """
    if not shares_bps:
        raise RoyaltyError("at least one share is required")
    for bps in shares_bps:
        _check_bps("collaborator bps", bps)
    if sum(shares_bps) != BPS_DENOMINATOR:
        raise RoyaltyError(f"collaborator shares must total 10000 bps, got {sum(shares_bps)}")
    exact = [amount_cents * bps for bps in shares_bps]
    parts = [e // BPS_DENOMINATOR for e in exact]
    leftover = amount_cents - sum(parts)
    order = sorted(range(len(shares_bps)), key=lambda i: (-(exact[i] % BPS_DENOMINATOR), i))
    for i in order[:leftover]:
        parts[i] += 1
    return parts


def _mul_bps_half_up(amount: int, bps: int) -> int:
    return (amount * bps + BPS_DENOMINATOR // 2) // BPS_DENOMINATOR


def _check_bps(name: str, value: int) -> None:
    if not isinstance(value, int) or not 0 <= value <= BPS_DENOMINATOR:
        raise RoyaltyError(f"{name} must be an integer between 0 and 10000")


def _fmt(cents: int) -> str:
    return f"{cents / 100:,.2f}"
