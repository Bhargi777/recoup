"""Phase 7: "queue drains correctly on recovery".

Before this phase, ``core.eval.batch_runner.run_batch`` had two real bugs
that together made this guarantee false:

1. A ``RazorpayAPIError``/``CircuitOpenError``/``httpx.TransportError`` raised
   by a real (--live) executor call was never caught, so it propagated out
   of ``run_batch`` and aborted the ENTIRE batch - every record after the
   failing one was silently never processed, even though nothing was wrong
   with them.
2. Because ``core.policy.gate.evaluate_gate`` writes ``MONEY_ACTION_INTENT``
   BEFORE the executor runs (money-action-gate SKILL.md checklist #10), a
   record whose executor then failed had its idempotency_key permanently
   "consumed" - ``check_idempotency`` would refuse to ever re-approve it,
   even on a later run once the transient condition cleared. The record was
   stranded forever.

Both are fixed (core/eval/batch_runner.py's try/except +
core/policy/guardrails.py's check_idempotency retry-after-failure logic).
This test proves the fix, not just that the code doesn't crash: it forces
exactly one record's executor call to fail, proves the REST of that same
batch still completes, then proves a second ("recovery") run picks up the
failed record and completes it - while every record that succeeded on run 1
is NOT reprocessed or double-actioned on run 2.
"""

from collections import Counter

import pytest
from sqlmodel import Session

import core.eval.batch_runner as batch_runner
from core.config import Settings
from core.ingest.razorpay_client import RazorpayAPIError
from core.ingest.synthetic import AtRiskRecord, init_synthetic_schema
from core.ledger import get_engine, init_ledger_schema, list_events
from core.policy.events import ACTION_EXECUTION_FAILED


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


def _seed_small(session: Session, n: int = 60) -> None:
    from core.ingest.synthetic import generate_records

    records = generate_records(seed=42)[:n]
    persisted = [AtRiskRecord(**r) for r in records]
    session.add_all(persisted)
    session.commit()


def test_one_gateway_failure_does_not_abort_the_rest_of_the_batch(session, settings, monkeypatch):
    _seed_small(session, 60)

    original_run_executor = batch_runner._run_executor
    state = {"failed": False, "failed_record_id": None}

    def flaky_run_executor(session_, step, decision, context, record, *, mode, razorpay_client):
        if not state["failed"] and step.step != "escalate_to_human" and decision.allowed:
            state["failed"] = True
            state["failed_record_id"] = record.id
            raise RazorpayAPIError(503, "TRANSIENT_ERROR", "gateway down", None, None, None)
        return original_run_executor(
            session_, step, decision, context, record, mode=mode, razorpay_client=razorpay_client
        )

    monkeypatch.setattr(batch_runner, "_run_executor", flaky_run_executor)

    report = batch_runner.run_batch(session, mode="dry_run", settings=settings)

    assert state["failed_record_id"] is not None
    assert report.failed_execution_count == 1
    # The batch kept going: other treatment records still got a real action.
    assert sum(report.executed_action_counts.values()) > 0

    failed_id = state["failed_record_id"]
    failed_types = [e.event_type for e in list_events(session) if e.aggregate_id == failed_id]
    assert ACTION_EXECUTION_FAILED in failed_types
    # The action genuinely never happened for this record.
    assert "ACTION_MESSAGE_DRAFTED" not in failed_types
    assert "EXCEPTION_QUEUE_ENQUEUED" not in failed_types


def test_recovery_run_completes_the_failed_record_without_touching_successes(
    session, settings, monkeypatch
):
    _seed_small(session, 60)

    original_run_executor = batch_runner._run_executor
    state = {"failed": False, "failed_record_id": None}

    def flaky_run_executor(session_, step, decision, context, record, *, mode, razorpay_client):
        if not state["failed"] and step.step != "escalate_to_human" and decision.allowed:
            state["failed"] = True
            state["failed_record_id"] = record.id
            raise RazorpayAPIError(503, "TRANSIENT_ERROR", "gateway down", None, None, None)
        return original_run_executor(
            session_, step, decision, context, record, mode=mode, razorpay_client=razorpay_client
        )

    monkeypatch.setattr(batch_runner, "_run_executor", flaky_run_executor)
    batch_runner.run_batch(session, mode="dry_run", settings=settings)
    failed_id = state["failed_record_id"]
    assert failed_id is not None

    # The transient condition has cleared - remove the fault injection and
    # re-run over the SAME ledger/session, simulating a recovery re-run.
    monkeypatch.setattr(batch_runner, "_run_executor", original_run_executor)
    batch_runner.run_batch(session, mode="dry_run", settings=settings)

    events_after = list_events(session)
    failed_record_types_after = [e.event_type for e in events_after if e.aggregate_id == failed_id]

    # The previously-failed record was picked up and actually completed.
    terminal_success_types = {
        "ACTION_MESSAGE_DRAFTED",
        "ACTION_SIMULATED_DRY_RUN",
        "ACTION_PAYMENT_LINK_EXECUTED_LIVE",
        "ACTION_MANDATE_RETRY_SCHEDULED",
        "EXCEPTION_QUEUE_ENQUEUED",
    }
    assert terminal_success_types & set(failed_record_types_after), (
        f"record {failed_id} was never completed on the recovery run: {failed_record_types_after}"
    )
    assert "ACTION_REFUSED_NOT_ALLOWED" not in failed_record_types_after

    # No record that already had a terminal action on run 1 was re-actioned
    # (double-drafted / double-executed / double-escalated) on run 2.
    action_events = [
        e
        for e in events_after
        if e.event_type in terminal_success_types
    ]
    counts_per_aggregate = Counter(e.aggregate_id for e in action_events)
    duplicated = {aid: n for aid, n in counts_per_aggregate.items() if n > 1}
    assert duplicated == {}, f"records re-actioned on the recovery run: {duplicated}"
