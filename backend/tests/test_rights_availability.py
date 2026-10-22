from datetime import UTC, datetime

from app.services.rights_availability import RightsScope, check_availability

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime(2027, 1, 1, tzinfo=UTC)
T2 = datetime(2028, 1, 1, tzinfo=UTC)


def scope(territory=("WORLDWIDE",), uses=("commercial_digital",), start=T0, end=None, exclusive=False, gid="g"):
    return RightsScope.build(territory, uses, start, end, exclusive, gid)


def test_nonexclusive_grants_coexist():
    assert check_availability([scope()], scope()).available


def test_exclusive_blocks_overlapping_nonexclusive():
    result = check_availability([scope(exclusive=True, territory=("US",))], scope(territory=("WORLDWIDE",)))
    assert not result.available and result.conflicts


def test_exclusive_does_not_block_other_territory_use_or_period():
    existing = [scope(exclusive=True, territory=("US",), uses=("broadcast",), start=T0, end=T1)]
    assert check_availability(existing, scope(territory=("CA",), uses=("broadcast",))).available
    assert check_availability(existing, scope(territory=("US",), uses=("editorial",))).available
    assert check_availability(existing, scope(territory=("US",), uses=("broadcast",), start=T1, end=T2)).available


def test_two_exclusive_grants_conflict():
    result = check_availability([scope(exclusive=True)], scope(exclusive=True))
    assert not result.available


def test_exclusive_request_over_prior_nonexclusive_requires_carve_out():
    existing = [scope(gid="prior")]
    blocked = check_availability(existing, scope(exclusive=True))
    assert not blocked.available and [g.grant_id for g in blocked.prior_obligations] == ["prior"]
    accepted = check_availability(existing, scope(exclusive=True), accept_prior_nonexclusive=True)
    assert accepted.available and accepted.prior_obligations


def test_all_uses_wildcard_overlaps():
    assert not check_availability([scope(uses=("ALL",), exclusive=True)], scope(uses=("merchandise",))).available
