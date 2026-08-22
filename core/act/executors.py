"""Action executors - one per intervention-ladder step type
(``core.policy.schema.KNOWN_STEPS``).

Every executor here takes the gate's already-computed ``PolicyDecision``
(``core.policy.gate.evaluate_gate``'s return value) as an explicit argument
and MUST refuse to run any real or simulated action if ``decision.allowed``
is not True - money-action-gate SKILL.md SS2: "No LLM may directly authorize
money actions" generalizes here to "no executor may authorize itself"; the
gate is the only authority, and refusal is a real, tested code path
(``_refuse`` below), not an assumed precondition.

``reminder_message`` / ``incentive_offer`` / ``pre_debit_notification`` draft
their text from ``core.act.templates`` - a deterministic, LLM-free template
keyed by root cause (CLAUDE.md SS4). None of them dispatch anywhere: this
codebase has no SMS/email/push gateway integration in any phase, so these
three executors always log a drafted-but-not-dispatched ledger event,
regardless of ``--dry-run``/``--live`` - claiming a real send with no real
transport would be fabrication.

``payment_link`` is the only executor with a genuine external integration
(``core.ingest.razorpay_client.RazorpayClient.create_payment_link``, reused
as-is from Phase 2). In ``--dry-run`` mode it NEVER touches the client -
callers must not even construct one - and instead logs
``ACTION_SIMULATED_DRY_RUN`` describing exactly what would have been sent.
In ``--live`` mode it makes the real HTTP call, which will fail Razorpay
authentication in this environment (no real ``rzp_test_`` credentials) -
that failure is expected and is not swallowed here.

``mandate_retry`` stays ledger-only in this phase: Phase 2's verified
``RazorpayClient`` surface has no endpoint for triggering a mandate/UPI
AutoPay retry, so this executor records the retry as SCHEDULED on the ledger
rather than fabricating a dispatch call.

``escalate_to_human`` writes a ledger event representing the human exception
queue - also no external call.

Every executor call - refused, drafted, scheduled, simulated, or live -
emits exactly one ledger event. Every executor also has a matching
``rollback_*``/``compensate_*`` handler per the money-action-gate skill's
"Reversibility & Refusal Contract".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session

from core.act.templates import (
    incentive_message,
    pre_debit_notification_message,
    reminder_message,
)
from core.ingest.razorpay_client import RazorpayClient
from core.ledger import append_event
from core.policy.context import GateContext
from core.policy.gate import PolicyDecision

# --- ledger event type constants --------------------------------------------

ACTION_REFUSED_NOT_ALLOWED = "ACTION_REFUSED_NOT_ALLOWED"
ACTION_MESSAGE_DRAFTED = "ACTION_MESSAGE_DRAFTED"
ACTION_SIMULATED_DRY_RUN = "ACTION_SIMULATED_DRY_RUN"
ACTION_PAYMENT_LINK_EXECUTED_LIVE = "ACTION_PAYMENT_LINK_EXECUTED_LIVE"
ACTION_MANDATE_RETRY_SCHEDULED = "ACTION_MANDATE_RETRY_SCHEDULED"
EXCEPTION_QUEUE_ENQUEUED = "EXCEPTION_QUEUE_ENQUEUED"
ACTION_PAYMENT_LINK_CANCELLED_LEDGER = "ACTION_PAYMENT_LINK_CANCELLED_LEDGER"
ACTION_COMPENSATED = "ACTION_COMPENSATED"

DRY_RUN = "dry_run"
LIVE = "live"
VALID_MODES = frozenset({DRY_RUN, LIVE})


class ExecutorInputError(ValueError):
    """Raised for programming errors in how an executor was called (e.g. an
    unknown mode, or --live with no client) - never used for a normal
    ALLOW/refuse decision, which always flows through ActionResult."""


@dataclass(frozen=True)
class ActionResult:
    action_type: str
    status: str  # "refused" | "drafted" | "simulated_dry_run" | "executed_live"
    # | "scheduled" | "exception_queued" | "compensated"
    ledger_event_type: str
    detail: dict[str, Any] = field(default_factory=dict)


def _refuse(session: Session, context: GateContext, action_type: str) -> ActionResult:
    append_event(
        session,
        context.aggregate_id,
        ACTION_REFUSED_NOT_ALLOWED,
        {
            "idempotency_key": context.idempotency_key,
            "action_type": action_type,
            "reason": "policy_gate_did_not_allow",
        },
    )
    return ActionResult(action_type, "refused", ACTION_REFUSED_NOT_ALLOWED, {})


# --- reminder_message ---------------------------------------------------------


def execute_reminder_message(
    session: Session, decision: PolicyDecision, context: GateContext, *, amount_inr: float
) -> ActionResult:
    if not decision.allowed:
        return _refuse(session, context, "reminder_message")

    message = reminder_message(context.root_cause, amount_inr)
    append_event(
        session,
        context.aggregate_id,
        ACTION_MESSAGE_DRAFTED,
        {
            "idempotency_key": context.idempotency_key,
            "action_type": "reminder_message",
            "root_cause": context.root_cause,
            "message": message,
            "dispatched": False,
            "dispatch_note": (
                "no SMS/email/push gateway is integrated in this codebase; the "
                "message is deterministically drafted and ledgered, never sent"
            ),
        },
    )
    return ActionResult(
        "reminder_message", "drafted", ACTION_MESSAGE_DRAFTED, {"message": message}
    )


# --- incentive_offer ------------------------------------------------------------


def execute_incentive_offer(
    session: Session, decision: PolicyDecision, context: GateContext, *, amount_inr: float
) -> ActionResult:
    if not decision.allowed:
        return _refuse(session, context, "incentive_offer")

    message = incentive_message(
        context.root_cause, context.incentive_amount_inr, context.incentive_percent, amount_inr
    )
    append_event(
        session,
        context.aggregate_id,
        ACTION_MESSAGE_DRAFTED,
        {
            "idempotency_key": context.idempotency_key,
            "action_type": "incentive_offer",
            "root_cause": context.root_cause,
            "incentive_amount_inr": context.incentive_amount_inr,
            "incentive_percent": context.incentive_percent,
            "message": message,
            "dispatched": False,
            "dispatch_note": (
                "no SMS/email/push gateway is integrated in this codebase; the "
                "message is deterministically drafted and ledgered, never sent"
            ),
        },
    )
    return ActionResult(
        "incentive_offer", "drafted", ACTION_MESSAGE_DRAFTED, {"message": message}
    )


# --- pre_debit_notification -----------------------------------------------------


def execute_pre_debit_notification(
    session: Session,
    decision: PolicyDecision,
    context: GateContext,
    *,
    amount_inr: float,
    notice_hours: float,
) -> ActionResult:
    if not decision.allowed:
        return _refuse(session, context, "pre_debit_notification")

    message = pre_debit_notification_message(amount_inr, notice_hours)
    append_event(
        session,
        context.aggregate_id,
        ACTION_MESSAGE_DRAFTED,
        {
            "idempotency_key": context.idempotency_key,
            "action_type": "pre_debit_notification",
            "root_cause": context.root_cause,
            "message": message,
            "dispatched": False,
            "dispatch_note": (
                "no SMS/email/push gateway is integrated in this codebase; the "
                "message is deterministically drafted and ledgered, never sent"
            ),
        },
    )
    return ActionResult(
        "pre_debit_notification", "drafted", ACTION_MESSAGE_DRAFTED, {"message": message}
    )


# --- mandate_retry ---------------------------------------------------------------


def execute_mandate_retry(
    session: Session, decision: PolicyDecision, context: GateContext
) -> ActionResult:
    if not decision.allowed:
        return _refuse(session, context, "mandate_retry")

    append_event(
        session,
        context.aggregate_id,
        ACTION_MANDATE_RETRY_SCHEDULED,
        {
            "idempotency_key": context.idempotency_key,
            "action_type": "mandate_retry",
            "root_cause": context.root_cause,
            "executed": False,
            "note": (
                "no mandate/UPI AutoPay retry-trigger endpoint exists in "
                "core.ingest.razorpay_client's verified Phase 2 surface; this "
                "executor records the retry as SCHEDULED on the ledger only, "
                "never claims a dispatched debit attempt"
            ),
        },
    )
    return ActionResult("mandate_retry", "scheduled", ACTION_MANDATE_RETRY_SCHEDULED, {})


# --- escalate_to_human -------------------------------------------------------------


def execute_escalate_to_human(
    session: Session, decision: PolicyDecision, context: GateContext
) -> ActionResult:
    if not decision.allowed:
        return _refuse(session, context, "escalate_to_human")

    append_event(
        session,
        context.aggregate_id,
        EXCEPTION_QUEUE_ENQUEUED,
        {
            "idempotency_key": context.idempotency_key,
            "action_type": "escalate_to_human",
            "cohort": context.cohort,
            "root_cause": context.root_cause,
        },
    )
    return ActionResult("escalate_to_human", "exception_queued", EXCEPTION_QUEUE_ENQUEUED, {})


# --- payment_link ------------------------------------------------------------------


def execute_payment_link(
    session: Session,
    decision: PolicyDecision,
    context: GateContext,
    *,
    mode: str,
    amount_inr: float,
    description: str,
    client: RazorpayClient | None = None,
) -> ActionResult:
    if mode not in VALID_MODES:
        raise ExecutorInputError(f"mode must be one of {sorted(VALID_MODES)}, got {mode!r}")

    if not decision.allowed:
        return _refuse(session, context, "payment_link")

    if mode == DRY_RUN:
        # Deliberately does not construct or touch a RazorpayClient at all -
        # this is the ledger-honesty guarantee for --dry-run.
        append_event(
            session,
            context.aggregate_id,
            ACTION_SIMULATED_DRY_RUN,
            {
                "idempotency_key": context.idempotency_key,
                "action_type": "payment_link",
                "would_call": "RazorpayClient.create_payment_link",
                "amount_inr": amount_inr,
                "description": description,
                "executed": False,
            },
        )
        return ActionResult(
            "payment_link",
            "simulated_dry_run",
            ACTION_SIMULATED_DRY_RUN,
            {"amount_inr": amount_inr, "description": description},
        )

    if client is None:
        raise ExecutorInputError("a RazorpayClient instance is required in --live mode")

    amount_paise = round(amount_inr * 100)
    response = client.create_payment_link(
        amount_paise=amount_paise,
        currency="INR",
        description=description,
        reference_id=context.aggregate_id,
    )
    append_event(
        session,
        context.aggregate_id,
        ACTION_PAYMENT_LINK_EXECUTED_LIVE,
        {
            "idempotency_key": context.idempotency_key,
            "action_type": "payment_link",
            "razorpay_payment_link_id": response.get("id"),
            "executed": True,
        },
    )
    return ActionResult(
        "payment_link", "executed_live", ACTION_PAYMENT_LINK_EXECUTED_LIVE, {"response": response}
    )


# --- rollback / compensate handlers (money-action-gate SKILL.md SS3) --------------


def rollback_payment_link(
    session: Session, context: GateContext, payment_link_id: str | None
) -> ActionResult:
    """Compensating action for ``payment_link``.

    Razorpay's Test Mode payment-links API has no verified cancel endpoint in
    ``.claude/skills/razorpay-testmode/SKILL.md``'s catalog, and none is
    fabricated here. Compensation is therefore ledger-side only: the link is
    marked cancelled in the audit trail so downstream attempt-count/cooldown/
    budget logic treats it as inactive; an operator voids the actual link
    manually in the Razorpay dashboard if one was really created.
    """
    append_event(
        session,
        context.aggregate_id,
        ACTION_PAYMENT_LINK_CANCELLED_LEDGER,
        {
            "idempotency_key": context.idempotency_key,
            "action_type": "payment_link",
            "razorpay_payment_link_id": payment_link_id,
            "note": (
                "no verified Razorpay payment-link cancel API in this codebase's "
                "catalog; compensated via ledger-side cancellation only"
            ),
        },
    )
    return ActionResult(
        "payment_link", "compensated", ACTION_PAYMENT_LINK_CANCELLED_LEDGER, {}
    )


def compensate_ledger_only_action(
    session: Session, context: GateContext, action_type: str
) -> ActionResult:
    """Compensation for the five ledger-only executors (reminder_message,
    incentive_offer, pre_debit_notification, mandate_retry,
    escalate_to_human): none of them ever dispatched anything external, so
    compensation is simply recording the reversal decision itself - there is
    nothing external to undo."""
    append_event(
        session,
        context.aggregate_id,
        ACTION_COMPENSATED,
        {
            "idempotency_key": context.idempotency_key,
            "action_type": action_type,
            "note": "no external dispatch occurred for this action_type; compensation "
            "is a ledger-only reversal record",
        },
    )
    return ActionResult(action_type, "compensated", ACTION_COMPENSATED, {})
