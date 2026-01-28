from retikon_core.retention import RetentionPolicy


def test_retention_tiers():
    policy = RetentionPolicy(
        hot_after_days=0,
        warm_after_days=7,
        cold_after_days=30,
        delete_after_days=90,
    )

    assert policy.tier_for_age(0) == "hot"
    assert policy.tier_for_age(7) == "warm"
    assert policy.tier_for_age(15) == "warm"
    assert policy.tier_for_age(30) == "cold"
    assert policy.tier_for_age(120) == "delete"
