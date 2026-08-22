"""The composed Deterministic Policy Gate (money-action-gate SKILL.md SS1).

``evaluate_gate`` is the ONLY function in this codebase allowed to decide
whether a money action may proceed. It never calls Razorpay or any executor -
core/policy owns gating, not execution (core/act/ does not exist yet). No LLM
is involved anywhere in this module or anything it imports (CLAUDE.md SS4).

Evaluation is exhaustive, not short-circuiting: all 10 checks always run and
every individual result - pass or fail - is written to the ledger, plus one
overall POLICY_GATE_DECISION event. This is a deliberate choice over
short-circuiting: money-action-gate SKILL.md is explicit that "every gate
decision - allow AND deny - goes to the ledger with a reason string" for
EVERY check, and an operator debugging a denial benefits from seeing every
reason a request failed at once (e.g. both over budget AND in a DND window)
rather than only the first one encountered. The cost is a handful of extra,
cheap, read-only queries per evaluation - negligible next to the audit value.

Only on an overall ALLOW does evaluate_gate append MONEY_ACTION_INTENT (and,
if an incentive is involved, INCENTIVE_COMMITTED) - strictly BEFORE returning
to the caller, satisfying checklist item #10 ("before any hypothetical
execution").
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session

from core.config import Settings, get_settings
from core.ledger import append_event
from core.policy.context import GateContext
from core.policy.events import INCENTIVE_COMMITTED, MONEY_ACTION_INTENT
from core.policy.guardrails import ALL_CHECKS, GateResult
from core.policy.loader import PlaybookLoadError, load_playbooks
from core.policy.schema import Playbook


class PolicyEngineError(RuntimeError):
    """Raised when the gate cannot even be evaluated - e.g. no playbook exists
    for the proposed root_cause. This is a configuration/programming error,
    never a normal DENY outcome, so it is raised rather than folded into
    PolicyDecision."""


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    results: tuple[GateResult, ...]
    reason: str


def _load_playbook(root_cause: str, playbooks_dir: Path | None) -> Playbook:
    try:
        playbooks = load_playbooks(playbooks_dir)
    except PlaybookLoadError as exc:
        raise PolicyEngineError(f"playbook set failed to load: {exc}") from exc

    playbook = playbooks.get(root_cause)
    if playbook is None:
        raise PolicyEngineError(f"no playbook exists for root_cause {root_cause!r}")
    return playbook


def evaluate_gate(
    session: Session,
    context: GateContext,
    *,
    playbooks_dir: Path | None = None,
    settings: Settings | None = None,
) -> PolicyDecision:
    settings = settings or get_settings()
    playbook = _load_playbook(context.root_cause, playbooks_dir)

    results: list[GateResult] = []
    for check in ALL_CHECKS:
        result = check(session, context, playbook, settings)
        results.append(result)
        append_event(
            session,
            aggregate_id=context.aggregate_id,
            event_type="POLICY_GATE_EVALUATED",
            payload={
                "idempotency_key": context.idempotency_key,
                "rule_name": result.check_name,
                "status": "ALLOW" if result.allowed else "BLOCKED",
                "reason": result.reason,
            },
        )

    overall_allowed = all(result.allowed for result in results)
    failed = [r.check_name for r in results if not r.allowed]
    overall_reason = (
        "all 10 checks passed" if overall_allowed else f"blocked by: {', '.join(failed)}"
    )

    append_event(
        session,
        aggregate_id=context.aggregate_id,
        event_type="POLICY_GATE_DECISION",
        payload={
            "idempotency_key": context.idempotency_key,
            "status": "ALLOW" if overall_allowed else "BLOCKED",
            "reason": overall_reason,
            "root_cause": context.root_cause,
            "cohort": context.cohort,
            "action_type": context.action_type,
        },
    )

    if overall_allowed:
        append_event(
            session,
            aggregate_id=context.aggregate_id,
            event_type=MONEY_ACTION_INTENT,
            payload={
                "idempotency_key": context.idempotency_key,
                "customer_id": context.customer_id,
                "cohort": context.cohort,
                "root_cause": context.root_cause,
                "action_type": context.action_type,
                "incentive_amount_inr": context.incentive_amount_inr,
                "incentive_percent": context.incentive_percent,
            },
        )
        if context.incentive_amount_inr > 0:
            append_event(
                session,
                aggregate_id=context.aggregate_id,
                event_type=INCENTIVE_COMMITTED,
                payload={
                    "idempotency_key": context.idempotency_key,
                    "cohort": context.cohort,
                    "root_cause": context.root_cause,
                    "amount_inr": context.incentive_amount_inr,
                },
            )

    return PolicyDecision(allowed=overall_allowed, results=tuple(results), reason=overall_reason)
