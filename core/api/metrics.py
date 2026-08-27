"""GET /api/metrics - real diagnosis metrics, real (simulated-labeled) uplift
+ Wilson CI, and a real exception list.

Three real computations, never fabricated or cached-as-if-static:
  1. ``core.eval.diagnosis_eval.evaluate_holdout`` - macro P/R/F1, confusion
     matrix, abstain rate, coverage over the real 200 held-out records.
  2. ``core.eval.batch_runner.run_batch`` (dry_run) - the real uplift +
     Wilson CI. Every uplift number in this response is
     ``[SIMULATED]``-labeled in the payload itself (not just prose) because
     it is computed over ``core.experiment.simulated_outcome``, not real
     observed Razorpay payments - see that module's docstring.
  3. An exception list: every ABSTAIN diagnosis
     (``DIAGNOSIS_ABSTAINED`` ledger events) and every
     ``EXCEPTION_QUEUE_ENQUEUED`` event this computation produced.

Reading a metric must not mutate the audit ledger. Both computations above
run against a throwaway, in-memory copy of the synthetic dataset
(``_scratch_session_with_records``) rather than the real session - real
diagnosis/policy/executor code is called unmodified and unweakened (nothing
here skips or fakes the ledger-write invariants CLAUDE.md requires for a real
money-action run; the SCRATCH ledger gets every event a real
``recoup run-batch`` would write), it is simply a disposable copy that is
discarded at the end of the request instead of the production ledger. A real
`recoup run-batch` / `recoup eval-diagnosis` CLI invocation against the real
ledger is unaffected and keeps writing real, durable events as before.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from core.act.executors import EXCEPTION_QUEUE_ENQUEUED
from core.api.deps import get_session
from core.config import get_settings
from core.diagnose.diagnose import DIAGNOSIS_ABSTAINED
from core.eval.batch_runner import run_batch
from core.eval.diagnosis_eval import evaluate_holdout
from core.ingest.synthetic import AtRiskRecord, init_synthetic_schema, run_generation
from core.ledger import get_engine, init_ledger_schema, list_events

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


def _scratch_session_with_records(real_session: Session) -> Session:
    """A throwaway in-memory ledger + a copy of the real synthetic records,
    so ``run_batch`` can compute a real report without writing a single
    event to the real, durable ledger. Never committed back; the caller
    discards it at the end of the request."""
    scratch_engine = get_engine("sqlite:///:memory:")
    init_ledger_schema(scratch_engine)
    init_synthetic_schema(scratch_engine)
    scratch_session = Session(scratch_engine)

    records = real_session.exec(select(AtRiskRecord)).all()
    for record in records:
        scratch_session.add(AtRiskRecord(**record.model_dump()))
    scratch_session.commit()
    return scratch_session


@router.get("")
def get_metrics(session: Session = Depends(get_session)) -> dict:
    settings = get_settings()
    init_synthetic_schema(session.get_bind())
    run_generation(session, seed=settings.split_seed, force=False)

    diagnosis_report = evaluate_holdout(session)

    scratch_session = _scratch_session_with_records(session)
    batch_report = run_batch(scratch_session, mode="dry_run", settings=settings)

    exceptions = []
    for event in list_events(scratch_session):
        if event.event_type == DIAGNOSIS_ABSTAINED:
            payload = json.loads(event.payload_json)
            exceptions.append(
                {
                    "sequence_num": event.sequence_num,
                    "timestamp_utc": event.timestamp_utc,
                    "aggregate_id": event.aggregate_id,
                    "kind": "diagnosis_abstained",
                    "reason": payload.get("reason", ""),
                    "confidence": payload.get("confidence"),
                }
            )
        elif event.event_type == EXCEPTION_QUEUE_ENQUEUED:
            payload = json.loads(event.payload_json)
            exceptions.append(
                {
                    "sequence_num": event.sequence_num,
                    "timestamp_utc": event.timestamp_utc,
                    "aggregate_id": event.aggregate_id,
                    "kind": "exception_queue_enqueued",
                    "reason": f"root_cause={payload.get('root_cause')!r} routed to human "
                    f"exception queue (action_type={payload.get('action_type')!r})",
                    "confidence": None,
                }
            )
    exceptions.sort(key=lambda e: e["sequence_num"], reverse=True)
    scratch_session.close()

    return {
        "diagnosis": diagnosis_report.as_dict(),
        "uplift": {
            "simulated": True,
            "qualifier": (
                "Computed over core.experiment.simulated_outcome - a labeled simulation, "
                "NOT real observed Razorpay payment behavior. There are no live test-mode "
                "credentials or real customer traffic in this environment."
            ),
            **batch_report.uplift.as_dict(),
        },
        "batch_run": {
            "mode": batch_report.mode,
            "total_records": batch_report.total_records,
            "elapsed_seconds": batch_report.elapsed_seconds,
            "abstained": batch_report.abstained,
            "treatment_count": batch_report.treatment_count,
            "control_count": batch_report.control_count,
            "actual_control_percent": batch_report.actual_control_percent,
            "blocked_count": batch_report.blocked_count,
            "blocked_reasons": batch_report.blocked_reasons,
            "executed_action_counts": batch_report.executed_action_counts,
            "failed_execution_count": batch_report.failed_execution_count,
            "failed_execution_reasons": batch_report.failed_execution_reasons,
        },
        "exceptions": {
            "total": len(exceptions),
            "items": exceptions,
        },
    }
