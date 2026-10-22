"""Rights-availability checks that prevent conflicting license grants.

A grant's scope is (territory × permitted uses × time window). Two scopes
overlap when all three dimensions intersect. A requested grant conflicts with
an existing active grant when they overlap and either one is exclusive.

When an exclusive grant is requested over a scope that already carries
nonexclusive licenses, those licenses are not silently overridden: they are
returned as *prior obligations* that block the grant unless the caller
explicitly accepts them as carve-outs (they then must be disclosed in the
exclusive agreement).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

WORLDWIDE = "WORLDWIDE"
ALL_USES = "ALL"


@dataclass(frozen=True)
class RightsScope:
    territory: frozenset[str]
    uses: frozenset[str]
    starts_at: datetime
    ends_at: datetime | None  # None = perpetual
    exclusive: bool
    grant_id: str = ""

    @classmethod
    def build(cls, territory, uses, starts_at, ends_at=None, exclusive=False, grant_id=""):
        return cls(
            frozenset(t.upper() for t in territory),
            frozenset(u.lower() if u != ALL_USES else u for u in uses),
            starts_at,
            ends_at,
            exclusive,
            grant_id,
        )


@dataclass
class AvailabilityResult:
    available: bool
    conflicts: list[RightsScope] = field(default_factory=list)
    prior_obligations: list[RightsScope] = field(default_factory=list)


def territories_overlap(a: frozenset[str], b: frozenset[str]) -> bool:
    if not a or not b:
        return False
    return WORLDWIDE in a or WORLDWIDE in b or bool(a & b)


def uses_overlap(a: frozenset[str], b: frozenset[str]) -> bool:
    if not a or not b:
        return False
    return ALL_USES in a or ALL_USES in b or bool(a & b)


def periods_overlap(a: RightsScope, b: RightsScope) -> bool:
    a_before_b = a.ends_at is not None and a.ends_at <= b.starts_at
    b_before_a = b.ends_at is not None and b.ends_at <= a.starts_at
    return not (a_before_b or b_before_a)


def scopes_overlap(a: RightsScope, b: RightsScope) -> bool:
    return territories_overlap(a.territory, b.territory) and uses_overlap(a.uses, b.uses) and periods_overlap(a, b)


def check_availability(
    existing: list[RightsScope], requested: RightsScope, accept_prior_nonexclusive: bool = False
) -> AvailabilityResult:
    result = AvailabilityResult(available=True)
    for grant in existing:
        if not scopes_overlap(grant, requested):
            continue
        if grant.exclusive:
            result.conflicts.append(grant)
        elif requested.exclusive:
            result.prior_obligations.append(grant)
    blocked_by_prior = bool(result.prior_obligations) and not accept_prior_nonexclusive
    result.available = not result.conflicts and not blocked_by_prior
    return result
