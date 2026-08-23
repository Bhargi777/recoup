"""Phase 6 batch orchestrator: diagnose -> assign holdout group -> gate ->
execute (treatment only) -> simulated outcome, over every synthetic at-risk
record.

Which records are processed
----------------------------
Every record in ``core.ingest.synthetic.AtRiskRecord`` (600 in the committed
synthetic dataset) is processed on every invocation. Diagnosis
(``core.diagnose.diagnose.diagnose``) is deterministic and append-only-safe,
so re-running this orchestrator against the same database re-diagnoses every
record and adds a fresh ledger event rather than skipping already-diagnosed
records - simpler and just as honest, since nothing here is randomly
re-drawn (holdout group and simulated outcome are pure functions of
customer_id/record_id + the committed seed, so they are identical on every
run). What DOES change between repeated runs against the same persisted
database is the policy gate: idempotency and cooldown checks correctly
start refusing repeat actions on a second pass - that is the gate working
as designed, not a bug in this orchestrator.

Which action is attempted
---------------------------
For a treatment-arm record, this orchestrator gates and (if allowed)
executes the FIRST step of that record's root-cause playbook's
intervention_ladder (offset "T+0" in every committed playbook). A full
multi-day ladder walk (T+0, T+24h, T+48h, ...) would require simulating the
passage of time across multiple batch runs, which is out of scope for a
single timed batch run; this orchestrator demonstrates one real "first
touch" decision per record end to end (diagnose -> holdout -> gate ->
execute -> simulated outcome), which is what the uplift measurement needs.

Control-arm invariant
------------------------
A control-arm record NEVER reaches the policy gate or any executor - full
stop. This is enforced here (not just documented): the control branch below
returns before ``evaluate_gate`` is ever called.

Honesty of the outcome numbers
---------------------------------
Every simulated-outcome ledger event this orchestrator emits carries
``outcome_source: "simulated"`` (core.experiment.simulated_outcome - read
its module docstring). The BatchReport this orchestrator returns is NOT a
report of real recovered revenue; it is a report of a correctly-implemented
statistical pipeline (real diagnosis, real deterministic holdout, real
policy gate, real-or-simulated executors) exercised end to end against
synthetic inputs and a labeled simulated outcome model. Callers (the CLI,
README, PR body) must repeat that qualifier next to any uplift number.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from sqlmodel import Session, select

from core.act.executors import (
    ActionResult,
    execute_escalate_to_human,
    execute_incentive_offer,
    execute_mandate_retry,
    execute_payment_link,
    execute_pre_debit_notification,
    execute_reminder_message,
)
from core.config import Settings, get_settings
from core.diagnose.diagnose import diagnose
from core.experiment.holdout import CONTROL, TREATMENT, assign_group
from core.experiment.simulated_outcome import simulated_outcome
from core.experiment.uplift import UpliftReport, compute_uplift
from core.ingest.circuit_breaker import CircuitOpenError
from core.ingest.idempotency import compute_idempotency_key
from core.ingest.razorpay_client import RazorpayAPIError, RazorpayClient
from core.ingest.synthetic import AtRiskRecord
from core.ledger import append_event
from core.policy.context import GateContext
from core.policy.events import ACTION_EXECUTION_FAILED
from core.policy.gate import PolicyDecision, evaluate_gate
from core.policy.loader import load_playbooks
from core.policy.schema import LadderStep, Playbook

# Real-world failures a live executor call can raise once the policy gate has
# already ALLOWed it (gateway down, retries+circuit breaker exhausted, or a
# raw network failure escaping the client). These are the ONLY exceptions
# run_batch catches per-record - anything else (a programming error) still
# propagates and stops the run, which is correct; only genuine external
# failures get the "log it, keep draining the rest of the queue" treatment.
EXECUTOR_TRANSIENT_FAILURES = (RazorpayAPIError, CircuitOpenError, httpx.TransportError)

IST = ZoneInfo("Asia/Kolkata")

DRY_RUN = "dry_run"
LIVE = "live"

EXPERIMENT_GROUP_ASSIGNED = "EXPERIMENT_GROUP_ASSIGNED"
HOLDOUT_NO_INTERVENTION = "HOLDOUT_NO_INTERVENTION"
SIMULATED_OUTCOME_RECORDED = "SIMULATED_OUTCOME_RECORDED"
BATCH_RECORD_ABSTAINED = "BATCH_RECORD_ABSTAINED"


@dataclass
class BatchReport:
    mode: str
    total_records: int
    abstained: int
    treatment_count: int
    control_count: int
    actual_control_percent: float
    blocked_count: int
    blocked_reasons: dict[str, int]
    executed_action_counts: dict[str, int]
    uplift: UpliftReport
    elapsed_seconds: float
    # Phase 7: records whose gate ALLOWed the action but whose real executor
    # call then failed (gateway 5xx/429 exhausted, circuit open, network
    # error) - logged as ACTION_EXECUTION_FAILED and retryable on a later
    # run (core.policy.guardrails.check_idempotency), never silently dropped
    # and never allowed to abort the rest of the batch.
    failed_execution_count: int = 0
    failed_execution_reasons: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "total_records": self.total_records,
            "abstained": self.abstained,
            "treatment_count": self.treatment_count,
            "control_count": self.control_count,
            "actual_control_percent": self.actual_control_percent,
            "blocked_count": self.blocked_count,
            "blocked_reasons": self.blocked_reasons,
            "executed_action_counts": self.executed_action_counts,
            "failed_execution_count": self.failed_execution_count,
            "failed_execution_reasons": self.failed_execution_reasons,
            "uplift": self.uplift.as_dict(),
            "elapsed_seconds": self.elapsed_seconds,
        }


def _pinned_daytime_ist_instant() -> datetime:
    """A single evaluation instant for the whole batch run, pinned to noon
    IST on the real current date. Pinned to daytime so the DND guardrail
    check evaluates on the record's merits rather than on whatever wall-clock
    hour this batch happens to run at - a real production system would use
    each record's genuine proposed local dispatch time instead."""
    now_ist_date = datetime.now(IST).date()
    return datetime(
        now_ist_date.year, now_ist_date.month, now_ist_date.day, 12, 0, tzinfo=IST
    ).astimezone(UTC)


def _incentive_for_step(step: LadderStep, playbook: Playbook) -> tuple[float, float]:
    """Incentive amount/percent for one ladder step - zero for every step
    except incentive_offer, which is capped exactly at the playbook's
    incentive_ceiling (the gate independently re-verifies this cap; capping
    here just avoids proposing something the gate would always reject)."""
    if step.step != "incentive_offer":
        return 0.0, 0.0
    ceiling = playbook.incentive_ceiling
    if ceiling.type == "amount_inr":
        return ceiling.value, 0.0
    return 0.0, ceiling.value


def _run_executor(
    session: Session,
    step: LadderStep,
    decision: PolicyDecision,
    context: GateContext,
    record: AtRiskRecord,
    *,
    mode: str,
    razorpay_client: RazorpayClient | None,
) -> ActionResult:
    if step.step == "reminder_message":
        return execute_reminder_message(session, decision, context, amount_inr=record.amount_inr)
    if step.step == "incentive_offer":
        return execute_incentive_offer(session, decision, context, amount_inr=record.amount_inr)
    if step.step == "pre_debit_notification":
        return execute_pre_debit_notification(
            session, decision, context, amount_inr=record.amount_inr, notice_hours=24.0
        )
    if step.step == "mandate_retry":
        return execute_mandate_retry(session, decision, context)
    if step.step == "escalate_to_human":
        return execute_escalate_to_human(session, decision, context)
    if step.step == "payment_link":
        return execute_payment_link(
            session,
            decision,
            context,
            mode=mode,
            amount_inr=record.amount_inr,
            description=f"Recover payment for {record.id}",
            client=razorpay_client,
        )
    raise ValueError(f"no executor wired for intervention step {step.step!r}")  # pragma: no cover


def run_batch(
    session: Session,
    *,
    mode: str = DRY_RUN,
    playbooks_dir: Path | None = None,
    settings: Settings | None = None,
    razorpay_client: RazorpayClient | None = None,
) -> BatchReport:
    if mode not in {DRY_RUN, LIVE}:
        raise ValueError(f"mode must be 'dry_run' or 'live', got {mode!r}")

    settings = settings or get_settings()
    playbooks = load_playbooks(playbooks_dir)
    run_instant = _pinned_daytime_ist_instant()

    start = time.monotonic()

    records = list(session.exec(select(AtRiskRecord)))

    abstained = 0
    treatment_recovered = treatment_total = 0
    control_recovered = control_total = 0
    control_assigned = 0
    blocked_records = 0
    blocked_reasons: Counter[str] = Counter()
    executed_action_counts: Counter[str] = Counter()
    failed_execution_count = 0
    failed_execution_reasons: Counter[str] = Counter()

    for record in records:
        diagnosis = diagnose(session, record)
        if diagnosis.predicted_root_cause is None:
            abstained += 1
            append_event(
                session,
                record.id,
                BATCH_RECORD_ABSTAINED,
                {"reason": "diagnosis_abstained; excluded from treatment/control comparison"},
            )
            continue

        root_cause = diagnosis.predicted_root_cause
        group = assign_group(
            record.customer_id, settings.default_holdout_percent, settings.split_seed
        )
        append_event(
            session,
            record.id,
            EXPERIMENT_GROUP_ASSIGNED,
            {
                "group": group,
                "seed": settings.split_seed,
                "holdout_percent": settings.default_holdout_percent,
            },
        )

        if group == CONTROL:
            control_assigned += 1
            # Control NEVER reaches the gate or any executor - enforced here,
            # not just documented.
            append_event(
                session,
                record.id,
                HOLDOUT_NO_INTERVENTION,
                {"group": CONTROL, "root_cause": root_cause},
            )
            recovered = simulated_outcome(record.id, root_cause, CONTROL, settings.split_seed)
            append_event(
                session,
                record.id,
                SIMULATED_OUTCOME_RECORDED,
                {
                    "outcome_source": "simulated",
                    "group": CONTROL,
                    "root_cause": root_cause,
                    "recovered": recovered,
                    "seed": settings.split_seed,
                },
            )
            control_total += 1
            control_recovered += int(recovered)
            continue

        # --- treatment arm --------------------------------------------------
        playbook = playbooks.get(root_cause)
        if playbook is None:  # pragma: no cover - taxonomy is validated at load time elsewhere
            abstained += 1
            continue

        step = playbook.intervention_ladder[0]
        incentive_amount, incentive_percent = _incentive_for_step(step, playbook)
        idempotency_key = compute_idempotency_key(step.step, record.id, 0)

        context = GateContext(
            idempotency_key=idempotency_key,
            aggregate_id=record.id,
            customer_id=record.customer_id,
            cohort=record.cohort,
            root_cause=root_cause,
            action_type=step.step,
            incentive_amount_inr=incentive_amount,
            incentive_percent=incentive_percent,
            proposed_action_at=run_instant,
            now=run_instant,
        )
        decision = evaluate_gate(session, context, playbooks_dir=playbooks_dir, settings=settings)

        if not decision.allowed:
            blocked_records += 1
            for result in decision.results:
                if not result.allowed:
                    blocked_reasons[result.check_name] += 1
            continue

        try:
            action_result = _run_executor(
                session,
                step,
                decision,
                context,
                record,
                mode=mode,
                razorpay_client=razorpay_client,
            )
        except EXECUTOR_TRANSIENT_FAILURES as exc:
            # The gate already ALLOWed and ledgered MONEY_ACTION_INTENT
            # (checklist #10), but the real external call failed. Record
            # that honestly and move on to the next record - one gateway
            # outage must not abort the rest of the queue. The idempotency
            # key stays retryable on a later run (see
            # core.policy.guardrails.check_idempotency).
            failed_execution_count += 1
            failed_execution_reasons[step.step] += 1
            append_event(
                session,
                record.id,
                ACTION_EXECUTION_FAILED,
                {
                    "idempotency_key": idempotency_key,
                    "action_type": step.step,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            continue

        executed_action_counts[step.step] += 1
        if action_result.status == "refused":  # pragma: no cover - decision.allowed already True
            continue

        recovered = simulated_outcome(record.id, root_cause, TREATMENT, settings.split_seed)
        append_event(
            session,
            record.id,
            SIMULATED_OUTCOME_RECORDED,
            {
                "outcome_source": "simulated",
                "group": TREATMENT,
                "root_cause": root_cause,
                "recovered": recovered,
                "seed": settings.split_seed,
                "action_type": step.step,
            },
        )
        treatment_total += 1
        treatment_recovered += int(recovered)

    elapsed = time.monotonic() - start
    diagnosed_total = len(records) - abstained
    actual_control_percent = (
        (control_assigned / diagnosed_total * 100.0) if diagnosed_total else 0.0
    )

    return BatchReport(
        mode=mode,
        total_records=len(records),
        abstained=abstained,
        treatment_count=treatment_total,
        control_count=control_total,
        actual_control_percent=actual_control_percent,
        blocked_count=blocked_records,
        blocked_reasons=dict(blocked_reasons),
        executed_action_counts=dict(executed_action_counts),
        failed_execution_count=failed_execution_count,
        failed_execution_reasons=dict(failed_execution_reasons),
        uplift=compute_uplift(
            treatment_recovered, treatment_total, control_recovered, control_total
        ),
        elapsed_seconds=elapsed,
    )
