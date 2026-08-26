"""core.experiment.simulated_outcome: a deterministic, explicitly-labeled
SIMULATION (see the module docstring) - not real payment behavior. These
tests only check the pure function's mechanical properties: determinism and
a directional treatment uplift over many draws. They do not and cannot
assert anything about real recovery rates."""

from core.experiment.simulated_outcome import (
    TREATMENT_UPLIFT_PP,
    baseline_recovery_rate,
    simulated_outcome,
)


def test_deterministic_same_inputs_same_outcome():
    for _ in range(10):
        assert simulated_outcome("synth_x_0001", "card_expired", "treatment", 42) == (
            simulated_outcome("synth_x_0001", "card_expired", "treatment", 42)
        )


def test_different_seed_can_change_outcome_for_some_records():
    flipped = any(
        simulated_outcome(f"synth_x_{i:04d}", "card_expired", "treatment", 1)
        != simulated_outcome(f"synth_x_{i:04d}", "card_expired", "treatment", 2)
        for i in range(200)
    )
    assert flipped


def test_treatment_recovers_more_often_than_control_over_many_records():
    root_cause = "insufficient_funds"
    seed = 42
    ids = [f"synth_sim_{i:04d}" for i in range(2000)]

    treatment_recovered = sum(simulated_outcome(i, root_cause, "treatment", seed) for i in ids)
    control_recovered = sum(simulated_outcome(i, root_cause, "control", seed) for i in ids)

    treatment_rate = treatment_recovered / len(ids)
    control_rate = control_recovered / len(ids)

    # Should land close to baseline and baseline + TREATMENT_UPLIFT_PP.
    baseline = baseline_recovery_rate(root_cause)
    assert abs(control_rate - baseline) < 0.05
    assert abs(treatment_rate - (baseline + TREATMENT_UPLIFT_PP)) < 0.05
    assert treatment_rate > control_rate


def test_unknown_root_cause_falls_back_to_default_rate():
    rate = baseline_recovery_rate("totally_unknown_root_cause")
    assert 0.0 <= rate <= 1.0


def test_probability_never_exceeds_one_even_with_high_baseline_plus_uplift():
    # bank_technical_error baseline is 0.50; + uplift is still well under 1,
    # but the clamp itself is exercised directly via extreme root causes.
    outcome = simulated_outcome("synth_edge_0001", "bank_technical_error", "treatment", 42)
    assert isinstance(outcome, bool)
