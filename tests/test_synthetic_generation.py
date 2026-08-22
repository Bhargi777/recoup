"""Cohort composition, split, and determinism tests for the Phase 3 synthetic generator."""

from core.ingest.synthetic import (
    COHORTS,
    HOLDOUT_COUNT,
    RECORDS_PER_COHORT,
    TOTAL_RECORDS,
    assign_holdout_ids,
    generate_records,
)


def test_generates_exactly_total_records_across_all_cohorts():
    records = generate_records(seed=42)
    assert len(records) == TOTAL_RECORDS == 600


def test_every_cohort_present_and_non_empty_and_sums_correctly():
    records = generate_records(seed=42)
    counts: dict[str, int] = {}
    for r in records:
        counts[r["cohort"]] = counts.get(r["cohort"], 0) + 1

    assert set(counts.keys()) == set(COHORTS)
    for cohort in COHORTS:
        assert counts[cohort] > 0
        assert counts[cohort] == RECORDS_PER_COHORT
    assert sum(counts.values()) == TOTAL_RECORDS


def test_exactly_two_hundred_held_out():
    records = generate_records(seed=42)
    held_out = [r for r in records if r["held_out"]]
    assert len(held_out) == HOLDOUT_COUNT == 200


def test_record_ids_are_unique():
    records = generate_records(seed=42)
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids))


def test_same_seed_produces_byte_identical_held_out_set_across_runs():
    run_a = generate_records(seed=42)
    run_b = generate_records(seed=42)

    held_out_a = {r["id"] for r in run_a if r["held_out"]}
    held_out_b = {r["id"] for r in run_b if r["held_out"]}
    assert held_out_a == held_out_b

    # full records identical too, not just the held-out ids
    assert run_a == run_b


def test_different_seed_can_produce_a_different_held_out_set():
    held_out_42 = {r["id"] for r in generate_records(seed=42) if r["held_out"]}
    held_out_7 = {r["id"] for r in generate_records(seed=7) if r["held_out"]}
    assert held_out_42 != held_out_7


def test_assign_holdout_ids_is_pure_function_of_seed_and_ids():
    ids = [f"synth_x_{i:04d}" for i in range(TOTAL_RECORDS)]
    first = assign_holdout_ids(ids, seed=42, holdout_count=HOLDOUT_COUNT)
    second = assign_holdout_ids(ids, seed=42, holdout_count=HOLDOUT_COUNT)
    assert first == second
    assert len(first) == HOLDOUT_COUNT


def test_source_field_is_synthetic_on_every_record():
    records = generate_records(seed=42)
    assert all(r["source"] == "synthetic" for r in records)


def test_invoice_cohort_has_no_gateway_error_fields():
    records = generate_records(seed=42)
    invoices = [r for r in records if r["cohort"] == "overdue_b2b_invoice"]
    assert len(invoices) == RECORDS_PER_COHORT
    for r in invoices:
        assert r["payment_method"] is None
        assert r["error_code"] is None
        assert r["error_reason"] is None
        assert r["true_root_cause"] == "invoice_overdue"


def test_abandonment_cohort_root_cause_is_always_abandonment():
    records = generate_records(seed=42)
    abandoned = [r for r in records if r["cohort"] == "checkout_abandonment"]
    assert len(abandoned) == RECORDS_PER_COHORT
    assert all(r["true_root_cause"] == "abandonment" for r in abandoned)


def test_checkout_cohorts_have_error_code_and_reason_populated():
    records = generate_records(seed=42)
    for r in records:
        if r["cohort"] == "overdue_b2b_invoice":
            continue
        assert r["error_code"] in {"BAD_REQUEST_ERROR", "GATEWAY_ERROR"}
        assert r["error_reason"]
        assert r["payment_method"] in {"card", "upi"}
