"""Deterministic holdout assignment: same customer+seed always lands in the
same group, and the empirical split over many customers is in a sane range
around the requested holdout percent (not an exact count - it's a hash, not
a literal partition, so an exact-count assertion would be flaky)."""

import pytest

from core.experiment.holdout import assign_group


def test_same_customer_and_seed_always_same_group():
    for _ in range(20):
        assert assign_group("cust_12345", 15.0, seed=42) == assign_group(
            "cust_12345", 15.0, seed=42
        )


def test_different_customers_can_land_in_different_groups():
    groups = {assign_group(f"cust_{i}", 15.0, seed=42) for i in range(200)}
    assert groups == {"treatment", "control"}


def test_different_seed_can_reshuffle_a_given_customer():
    # Not guaranteed for every customer, but over many customers at least one
    # must flip groups between two different seeds - otherwise the seed
    # isn't actually part of the hash input.
    flipped = any(
        assign_group(f"cust_{i}", 15.0, seed=1) != assign_group(f"cust_{i}", 15.0, seed=2)
        for i in range(200)
    )
    assert flipped


def test_empirical_split_is_in_a_sane_range_around_holdout_percent():
    customer_ids = [f"cust_{i:05d}" for i in range(5000)]
    control_count = sum(
        1 for cid in customer_ids if assign_group(cid, 15.0, seed=42) == "control"
    )
    control_ratio = control_count / len(customer_ids)
    # Sane range, not an exact 15% - see module docstring.
    assert 0.10 <= control_ratio <= 0.20


def test_zero_holdout_percent_is_always_treatment():
    for i in range(50):
        assert assign_group(f"cust_{i}", 0.0, seed=42) == "treatment"


def test_hundred_holdout_percent_is_always_control():
    for i in range(50):
        assert assign_group(f"cust_{i}", 100.0, seed=42) == "control"


def test_rejects_out_of_range_holdout_percent():
    with pytest.raises(ValueError):
        assign_group("cust_1", -1.0, seed=42)
    with pytest.raises(ValueError):
        assign_group("cust_1", 100.1, seed=42)


def test_rejects_empty_customer_id():
    with pytest.raises(ValueError):
        assign_group("", 15.0, seed=42)
