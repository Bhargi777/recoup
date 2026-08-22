"""core.eval.batch_runner: diagnose -> holdout -> gate -> execute -> simulated
outcome, over synthetic records.

Covers: the control-arm invariant (never reaches the gate or an executor),
the outcome_source: "simulated" label on every simulated-outcome ledger
event (the single most important test in this phase per the task brief),
blocked-vs-clean-comparison bucketing, and a real, timed full run against
the actual 600 Phase-3 synthetic records in --dry-run mode.
"""

import json

import pytest
from sqlmodel import Session

from core.config import Settings
from core.eval.batch_runner import (
    HOLDOUT_NO_INTERVENTION,
    SIMULATED_OUTCOME_RECORDED,
    run_batch,
)
from core.ingest.synthetic import AtRiskRecord, init_synthetic_schema, run_generation
from core.ledger import get_engine, init_ledger_schema, list_events


@pytest.fixture()
def session():
    engine = get_engine("sqlite:///:memory:")
    init_ledger_schema(engine)
    init_synthetic_schema(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def settings():
    return Settings(razorpay_key_id="rzp_test_dummy")


def _seed_small(session: Session, n: int = 40) -> None:
    """A small, fast subset of realistic records for unit-level tests -
    real error_code/error_reason/cohort combinations drawn straight from
    core.ingest.synthetic.generate_records, just truncated for speed."""
    from core.ingest.synthetic import generate_records

    records = generate_records(seed=42)[:n]
    persisted = [AtRiskRecord(**r) for r in records]
    session.add_all(persisted)
    session.commit()


def test_control_arm_never_reaches_gate_or_executor(session, settings):
    _seed_small(session, 60)
    report = run_batch(session, mode="dry_run", settings=settings)

    assert report.control_count > 0
    events = list_events(session)

    # No MONEY_ACTION_INTENT, POLICY_GATE_DECISION, or any executor-ledger
    # event may reference a control-arm record - check via the
    # HOLDOUT_NO_INTERVENTION aggregate ids.
    control_ids = {
        e.aggregate_id for e in events if e.event_type == HOLDOUT_NO_INTERVENTION
    }
    assert control_ids  # sanity: some records were control

    forbidden_types = {
        "POLICY_GATE_DECISION",
        "MONEY_ACTION_INTENT",
        "ACTION_MESSAGE_DRAFTED",
        "ACTION_SIMULATED_DRY_RUN",
        "ACTION_PAYMENT_LINK_EXECUTED_LIVE",
        "EXCEPTION_QUEUE_ENQUEUED",
        "ACTION_MANDATE_RETRY_SCHEDULED",
    }
    for event in events:
        if event.aggregate_id in control_ids and event.event_type in forbidden_types:
            pytest.fail(
                f"control-arm record {event.aggregate_id} reached {event.event_type} "
                "- control must never reach the gate or an executor"
            )


def test_every_simulated_outcome_event_is_labeled(session, settings):
    _seed_small(session, 60)
    run_batch(session, mode="dry_run", settings=settings)

    events = [e for e in list_events(session) if e.event_type == SIMULATED_OUTCOME_RECORDED]
    assert events  # sanity: the run actually produced outcome events
    for event in events:
        payload = json.loads(event.payload_json)
        assert payload["outcome_source"] == "simulated"


def test_treatment_and_control_totals_match_report(session, settings):
    _seed_small(session, 60)
    report = run_batch(session, mode="dry_run", settings=settings)

    outcome_events = [
        json.loads(e.payload_json)
        for e in list_events(session)
        if e.event_type == SIMULATED_OUTCOME_RECORDED
    ]
    treatment_events = [e for e in outcome_events if e["group"] == "treatment"]
    control_events = [e for e in outcome_events if e["group"] == "control"]
    assert len(treatment_events) == report.treatment_count
    assert len(control_events) == report.control_count


def test_actual_control_percent_is_in_sane_range(session, settings):
    _seed_small(session, 200)
    report = run_batch(session, mode="dry_run", settings=settings)
    assert 5.0 <= report.actual_control_percent <= 25.0


def test_dry_run_never_executes_live_payment_link(session, settings):
    _seed_small(session, 60)
    run_batch(session, mode="dry_run", settings=settings)
    types = [e.event_type for e in list_events(session)]
    assert "ACTION_PAYMENT_LINK_EXECUTED_LIVE" not in types


def test_report_has_elapsed_time_and_all_summary_fields(session, settings):
    _seed_small(session, 30)
    report = run_batch(session, mode="dry_run", settings=settings)
    assert report.elapsed_seconds > 0
    d = report.as_dict()
    for key in (
        "mode",
        "total_records",
        "abstained",
        "treatment_count",
        "control_count",
        "actual_control_percent",
        "blocked_count",
        "blocked_reasons",
        "executed_action_counts",
        "uplift",
        "elapsed_seconds",
    ):
        assert key in d


def test_rejects_unknown_mode(session, settings):
    with pytest.raises(ValueError):
        run_batch(session, mode="not_a_real_mode", settings=settings)


def test_blocked_records_are_tracked_separately_from_the_comparison(session, settings):
    """With the kill switch active, every treatment-arm record must be
    blocked at the gate rather than executed - and blocked records must be
    excluded from the treatment/control uplift comparison entirely (not
    counted as "not recovered"), per honest-metrics SKILL.md SS5."""
    from core.policy.kill_switch import activate_kill_switch

    _seed_small(session, 80)
    activate_kill_switch(session, "test: force every treatment action to be blocked")

    report = run_batch(session, mode="dry_run", settings=settings)

    assert report.blocked_count > 0
    assert report.blocked_reasons.get("kill_switch", 0) == report.blocked_count
    assert report.treatment_count == 0  # every would-be-treatment record was blocked, not counted
    assert report.executed_action_counts == {}

    # No executor ledger event exists for any record - the kill switch blocked
    # every treatment-arm gate evaluation before an executor was ever called.
    types = {e.event_type for e in list_events(session)}
    assert "ACTION_MESSAGE_DRAFTED" not in types
    assert "EXCEPTION_QUEUE_ENQUEUED" not in types


def test_full_batch_of_600_synthetic_records_dry_run(settings):
    """A real, timed run against the actual 600 Phase-3 synthetic records -
    not a subset, not an estimate. The counts and elapsed_seconds this
    produces are what the README/PR quote."""
    engine = get_engine("sqlite:///:memory:")
    init_ledger_schema(engine)
    init_synthetic_schema(engine)

    with Session(engine) as session:
        generation = run_generation(session, seed=settings.split_seed, force=False)
        assert generation.inserted == 600

        report = run_batch(session, mode="dry_run", settings=settings)

    assert report.total_records == 600
    assert report.treatment_count + report.control_count + report.blocked_count == (
        600 - report.abstained
    )
    assert report.elapsed_seconds > 0
