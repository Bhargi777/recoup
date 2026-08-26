"""Uplift computation: treatment vs. control Wilson CIs and the uplift point
estimate derived from them."""

from core.experiment.uplift import compute_uplift


def test_uplift_is_treatment_rate_minus_control_rate():
    report = compute_uplift(
        treatment_recovered=43, treatment_total=100, control_recovered=30, control_total=100
    )
    assert report.uplift == 0.13
    assert report.treatment.point_estimate == 0.43
    assert report.control.point_estimate == 0.30


def test_uplift_report_carries_n_per_arm():
    report = compute_uplift(
        treatment_recovered=43, treatment_total=100, control_recovered=30, control_total=100
    )
    assert report.treatment.n == 100
    assert report.control.n == 100


def test_uplift_zero_control_conversions_gives_wide_control_ci():
    report = compute_uplift(
        treatment_recovered=10, treatment_total=50, control_recovered=0, control_total=20
    )
    assert report.control.point_estimate == 0.0
    assert report.control.upper > 0.1  # honestly wide, not collapsed to zero


def test_uplift_as_dict_round_trips_key_fields():
    report = compute_uplift(
        treatment_recovered=43, treatment_total=100, control_recovered=30, control_total=100
    )
    d = report.as_dict()
    assert d["uplift"] == report.uplift
    assert d["treatment"]["n"] == 100
    assert d["control"]["n"] == 100
