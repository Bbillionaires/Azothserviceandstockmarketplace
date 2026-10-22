import random

import pytest

from app.services.royalty_engine import (
    Collaborator,
    Model,
    RoyaltyError,
    RoyaltyInput,
    ShareRule,
    calculate,
    split_by_bps,
)

MODEL_A = ShareRule("model_a", 1, Model.nonexclusive, creator_bps=5000, affiliate_bps_of_platform=1000)
MODEL_B = ShareRule("model_b", 1, Model.exclusive, creator_bps=5000, initial_exclusive_creator_bps=6500,
                    affiliate_bps_of_platform=1000)
MODEL_C = ShareRule("model_c", 1, Model.free, creator_bps=0)


def amounts(result):
    return {(a.party_type, a.party_id): a.amount_cents for a in result.allocations}


def test_model_a_with_affiliate_matches_business_plan_example():
    # $100 license -> creator $50, platform $50, affiliate $5 (10% of platform), platform keeps $45.
    r = calculate(RoyaltyInput(10_000, MODEL_A, "creator", affiliate_party_id="aff"))
    assert r.creator_pool_cents == 5_000
    assert r.platform_share_cents == 5_000
    assert r.affiliate_cents == 500
    assert r.platform_net_cents == 4_500
    assert amounts(r) == {("creator", "creator"): 5_000, ("affiliate", "aff"): 500, ("platform", "platform"): 4_500}


def test_affiliate_never_reduces_creator_royalty():
    with_aff = calculate(RoyaltyInput(12_345, MODEL_A, "c", affiliate_party_id="aff"))
    without = calculate(RoyaltyInput(12_345, MODEL_A, "c"))
    assert with_aff.creator_pool_cents == without.creator_pool_cents
    assert without.affiliate_cents == 0


def test_collaboration_split_matches_business_plan_example():
    # $100 -> $50 creator pool split 50/30/20 -> $25 / $15 / $10; platform unchanged.
    collabs = (Collaborator("videographer", 5000), Collaborator("editor", 3000), Collaborator("drone", 2000))
    r = calculate(RoyaltyInput(10_000, MODEL_A, "owner", collaborators=collabs))
    a = amounts(r)
    assert a[("creator", "videographer")] == 2_500
    assert a[("creator", "editor")] == 1_500
    assert a[("creator", "drone")] == 1_000
    assert r.platform_net_cents == 5_000


def test_model_b_initial_exclusive_is_65_35_then_50_50():
    initial = calculate(RoyaltyInput(100_000, MODEL_B, "c", is_initial_exclusive_transaction=True))
    assert (initial.creator_pool_cents, initial.platform_share_cents) == (65_000, 35_000)
    later = calculate(RoyaltyInput(100_000, MODEL_B, "c"))
    assert (later.creator_pool_cents, later.platform_share_cents) == (50_000, 50_000)


def test_initial_exclusive_flag_rejected_for_nonexclusive_rule():
    with pytest.raises(RoyaltyError):
        calculate(RoyaltyInput(10_000, MODEL_A, "c", is_initial_exclusive_transaction=True))


def test_free_model_zero_revenue_and_rejects_paid():
    r = calculate(RoyaltyInput(0, MODEL_C, "c"))
    assert r.net_cents == 0 and all(a.amount_cents == 0 for a in r.allocations)
    with pytest.raises(RoyaltyError):
        calculate(RoyaltyInput(100, MODEL_C, "c"))


def test_only_configured_deductions_reduce_net():
    rule = ShareRule("r", 1, Model.nonexclusive, 5000, net_revenue_deductions=("taxes_collected",))
    r = calculate(RoyaltyInput(10_000, rule, "c", deductions={"taxes_collected": 700, "payment_processing_fees": 320}))
    assert r.deductions_applied == {"taxes_collected": 700}
    assert r.net_cents == 9_300
    assert r.creator_pool_cents == 4_650


def test_deductions_cannot_exceed_gross_or_be_negative():
    with pytest.raises(RoyaltyError):
        calculate(RoyaltyInput(100, MODEL_A, "c", deductions={"taxes_collected": 200}))
    with pytest.raises(RoyaltyError):
        calculate(RoyaltyInput(100, MODEL_A, "c", deductions={"taxes_collected": -1}))
    with pytest.raises(RoyaltyError):
        calculate(RoyaltyInput(100, MODEL_A, "c", deductions={"made_up": 1}))


def test_negative_gross_rejected():
    with pytest.raises(RoyaltyError):
        calculate(RoyaltyInput(-1, MODEL_A, "c"))


def test_rounding_always_reconciles_to_net():
    rng = random.Random(42)
    for _ in range(2_000):
        gross = rng.randint(0, 1_000_000)
        n = rng.randint(1, 5)
        cuts = sorted(rng.sample(range(1, 10_000), n - 1)) if n > 1 else []
        bps = [b - a for a, b in zip([0, *cuts], [*cuts, 10_000], strict=False)]
        rule = ShareRule("r", 1, Model.nonexclusive, rng.randint(0, 10_000),
                         affiliate_bps_of_platform=rng.randint(0, 10_000))
        r = calculate(RoyaltyInput(gross, rule, "c", affiliate_party_id="a",
                                   collaborators=tuple(Collaborator(f"p{i}", b) for i, b in enumerate(bps))))
        assert sum(a.amount_cents for a in r.allocations) == r.net_cents == gross
        assert r.creator_pool_cents + r.platform_share_cents == r.net_cents
        assert all(a.amount_cents >= 0 for a in r.allocations)


def test_split_by_bps_largest_remainder():
    assert split_by_bps(100, [3333, 3333, 3334]) == [33, 33, 34]
    assert split_by_bps(1, [5000, 5000]) == [1, 0]
    with pytest.raises(RoyaltyError):
        split_by_bps(100, [5000, 4000])


def test_invalid_rule_rejected():
    with pytest.raises(RoyaltyError):
        ShareRule("bad", 1, Model.nonexclusive, creator_bps=10_001)


def test_explanation_lists_rule_version():
    lines = calculate(RoyaltyInput(10_000, MODEL_A, "c", affiliate_party_id="a")).explain()
    assert lines[-1] == "Rule: model_a v1"
    assert any("Affiliate commission" in line for line in lines)
