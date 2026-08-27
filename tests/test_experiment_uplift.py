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


def test_uplift_not_computable_when_treatment_arm_is_empty():
    """Regression test: a second run-batch where every treatment record is
    correctly blocked by the gate (idempotency) leaves treatment n=0. That
    must report as not-computable, never as a misleading negative number
    from arithmetic on an empty arm."""
    report = compute_uplift(
        treatment_recovered=0, treatment_total=0, control_recovered=27, control_total=84
    )
    assert report.treatment.n == 0
    assert report.is_computable is False
    assert report.uplift is None
    assert report.not_computable_reason is not None
    assert "treatment" in report.not_computable_reason
    assert "n=0" in report.not_computable_reason


def test_uplift_not_computable_when_control_arm_is_empty():
    report = compute_uplift(
        treatment_recovered=196, treatment_total=516, control_recovered=0, control_total=0
    )
    assert report.is_computable is False
    assert report.uplift is None
    assert "control" in report.not_computable_reason


def test_uplift_is_computable_when_both_arms_have_data():
    report = compute_uplift(
        treatment_recovered=43, treatment_total=100, control_recovered=30, control_total=100
    )
    assert report.is_computable is True
    assert report.not_computable_reason is None
    assert report.uplift == 0.13


def test_uplift_not_computable_as_dict_has_null_uplift_and_a_reason():
    report = compute_uplift(
        treatment_recovered=0, treatment_total=0, control_recovered=27, control_total=84
    )
    d = report.as_dict()
    assert d["uplift"] is None
    assert d["uplift_computable"] is False
    assert d["uplift_not_computable_reason"] is not None
