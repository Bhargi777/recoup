"""Wilson score interval correctness against hand-verifiable reference cases."""

import pytest

from core.experiment.stats import wilson_score_interval


def test_wilson_matches_known_reference_case_n10_k8():
    # Textbook reference (Newcombe 1998; widely cited worked example):
    # n=10, k=8 successes (p_hat=0.8) -> 95% Wilson CI approx (0.492, 0.943).
    result = wilson_score_interval(8, 10)
    assert result.point_estimate == pytest.approx(0.8)
    assert result.lower == pytest.approx(0.490, abs=0.01)
    assert result.upper == pytest.approx(0.943, abs=0.01)


def test_wilson_interval_always_contains_point_estimate():
    result = wilson_score_interval(37, 120)
    assert result.lower <= result.point_estimate <= result.upper


def test_wilson_interval_stays_within_zero_one():
    result = wilson_score_interval(1, 2)
    assert 0.0 <= result.lower
    assert result.upper <= 1.0


def test_wilson_zero_n_returns_maximally_wide_interval():
    result = wilson_score_interval(0, 0)
    assert result.lower == 0.0
    assert result.upper == 1.0


def test_wilson_zero_successes_is_not_zero_width():
    # A normal-approximation interval would collapse to (0, 0) here - Wilson
    # must not, per honest-metrics SKILL.md SS3 ("if control conversions are
    # zero, say the CI is wide rather than quoting a raw multiple").
    result = wilson_score_interval(0, 50)
    assert result.point_estimate == 0.0
    assert result.upper > 0.0


def test_wilson_all_successes_is_not_perfectly_tight():
    result = wilson_score_interval(50, 50)
    assert result.point_estimate == 1.0
    assert result.lower < 1.0


def test_wilson_rejects_k_greater_than_n():
    with pytest.raises(ValueError):
        wilson_score_interval(5, 3)


def test_wilson_rejects_negative_inputs():
    with pytest.raises(ValueError):
        wilson_score_interval(-1, 10)
    with pytest.raises(ValueError):
        wilson_score_interval(1, -10)


def test_wilson_narrows_as_n_grows():
    small = wilson_score_interval(30, 100)
    large = wilson_score_interval(300, 1000)
    assert (large.upper - large.lower) < (small.upper - small.lower)
