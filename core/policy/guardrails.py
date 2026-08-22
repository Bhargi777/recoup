"""The 10 individual guardrail checks from
``.claude/skills/money-action-gate/SKILL.md`` SS1, each independently
testable and pure with respect to its inputs (session is read-only in every
function here; only ``core.policy.gate.evaluate_gate`` writes to the ledger).

Every check has the same shape: ``(session, context, playbook, settings) ->
GateResult``. ``core/policy/gate.py`` composes all 10, logs every result
(pass and fail) to the ledger, and derives the overall decision.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import Session

from core.config import Settings
from core.ledger import LedgerEvent, events_for_aggregate, list_events
from core.policy.budget import committed_spend
from core.policy.context import GateContext
from core.policy.events import MONEY_ACTION_INTENT
from core.policy.kill_switch import is_kill_switch_active
from core.policy.schema import Playbook

# action_type values that represent a customer-facing communication or
# mandate-debit attempt - what the attempt-limit and cooldown checks count.
# Deliberately excludes "escalate_to_human", which hands the case to a human
# and is not itself a metered customer-facing attempt.
COMMUNICATION_ACTION_TYPES = frozenset(
    {
        "reminder_message",
        "payment_link",
        "incentive_offer",
        "pre_debit_notification",
        "mandate_retry",
    }
)

# NPCI UPI AutoPay peak windows (IST), half-open [start, end). See README.md
# "Regulatory constraints (Phase 5)" for sourcing / confidence.
NPCI_PEAK_WINDOWS_IST: tuple[tuple[int, int, int, int], ...] = (
    (10, 0, 13, 0),
    (17, 0, 21, 30),
)


@dataclass(frozen=True)
class GateResult:
    check_name: str
    allowed: bool
    reason: str


def _money_action_intents(session: Session, aggregate_id: str) -> list[tuple[LedgerEvent, dict]]:
    """All MONEY_ACTION_INTENT events for one aggregate, oldest first, with
    their decoded payloads. This is the single append-only source of truth
    idempotency, attempt-count, and cooldown all replay from - see
    core/policy/events.py."""
    return [
        (event, json.loads(event.payload_json))
        for event in events_for_aggregate(session, aggregate_id)
        if event.event_type == MONEY_ACTION_INTENT
    ]


def _parse_ledger_timestamp(timestamp_utc: str) -> datetime:
    return datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))


def _in_npci_peak_window(local_hour: int, local_minute: int) -> bool:
    minutes = local_hour * 60 + local_minute
    for start_h, start_m, end_h, end_m in NPCI_PEAK_WINDOWS_IST:
        start = start_h * 60 + start_m
        end = end_h * 60 + end_m
        if start <= minutes < end:
            return True
    return False


# --- 1. Idempotency verification -------------------------------------------


def check_idempotency(
    session: Session, context: GateContext, playbook: Playbook, settings: Settings
) -> GateResult:
    for _, payload in _money_action_intents(session, context.aggregate_id):
        if payload.get("idempotency_key") == context.idempotency_key:
            return GateResult(
                "idempotency_verification",
                False,
                f"idempotency_key {context.idempotency_key!r} was already approved for "
                f"aggregate {context.aggregate_id!r}; refusing to re-approve as an "
                "independent action",
            )
    return GateResult(
        "idempotency_verification", True, "idempotency_key not previously seen for this aggregate"
    )


# --- 2. Global budget meter --------------------------------------------------


def check_global_budget(
    session: Session, context: GateContext, playbook: Playbook, settings: Settings
) -> GateResult:
    current = committed_spend(session)
    proposed = context.incentive_amount_inr
    cap = settings.max_global_budget_inr
    if current + proposed > cap:
        return GateResult(
            "global_budget_meter",
            False,
            f"committed spend Rs.{current:.2f} + proposed Rs.{proposed:.2f} would exceed "
            f"global cap Rs.{cap:.2f}",
        )
    return GateResult(
        "global_budget_meter",
        True,
        f"committed spend Rs.{current:.2f} + proposed Rs.{proposed:.2f} within global cap "
        f"Rs.{cap:.2f}",
    )


# --- 3. Cohort incentive ceiling --------------------------------------------


def check_cohort_incentive_ceiling(
    session: Session, context: GateContext, playbook: Playbook, settings: Settings
) -> GateResult:
    ceiling = playbook.incentive_ceiling
    if ceiling.type == "amount_inr":
        proposed = context.incentive_amount_inr
        unit = "Rs."
    else:
        proposed = context.incentive_percent
        unit = "%"

    if proposed > ceiling.value:
        return GateResult(
            "cohort_incentive_ceiling",
            False,
            f"proposed incentive {unit}{proposed:.2f} exceeds {playbook.root_cause} "
            f"ceiling {unit}{ceiling.value:.2f}",
        )
    return GateResult(
        "cohort_incentive_ceiling",
        True,
        f"proposed incentive {unit}{proposed:.2f} within {playbook.root_cause} "
        f"ceiling {unit}{ceiling.value:.2f}",
    )


# --- 4. Customer attempt limits ---------------------------------------------


def check_attempt_limits(
    session: Session, context: GateContext, playbook: Playbook, settings: Settings
) -> GateResult:
    if context.is_emandate_debit or context.is_upi_autopay_execution:
        limit = settings.npci_upi_autopay_max_attempts
        limit_source = "NPCI UPI AutoPay max_attempts"
    else:
        limit = playbook.max_attempts
        limit_source = f"{playbook.root_cause} playbook max_attempts"

    prior_attempts = sum(
        1
        for _, payload in _money_action_intents(session, context.aggregate_id)
        if payload.get("action_type") in COMMUNICATION_ACTION_TYPES
    )
    if prior_attempts >= limit:
        return GateResult(
            "customer_attempt_limits",
            False,
            f"{prior_attempts} prior attempts already reached {limit_source} limit of {limit}",
        )
    return GateResult(
        "customer_attempt_limits",
        True,
        f"{prior_attempts} prior attempts within {limit_source} limit of {limit}",
    )


# --- 5. Cooldown interval ----------------------------------------------------


def check_cooldown(
    session: Session, context: GateContext, playbook: Playbook, settings: Settings
) -> GateResult:
    intents = [
        (event, payload)
        for event, payload in _money_action_intents(session, context.aggregate_id)
        if payload.get("action_type") in COMMUNICATION_ACTION_TYPES
    ]
    if not intents:
        return GateResult(
            "cooldown_interval", True, "no prior communication recorded for this aggregate"
        )

    last_event, _ = max(intents, key=lambda pair: pair[0].sequence_num)
    last_at = _parse_ledger_timestamp(last_event.timestamp_utc)
    elapsed = context.now - last_at
    threshold = timedelta(hours=settings.default_cooldown_hours)

    if elapsed < threshold:
        return GateResult(
            "cooldown_interval",
            False,
            f"only {elapsed} since last communication; cooldown requires >= {threshold}",
        )
    return GateResult(
        "cooldown_interval",
        True,
        f"{elapsed} since last communication satisfies cooldown >= {threshold}",
    )


# --- 6. Quiet hours / DND ----------------------------------------------------


def check_quiet_hours(
    session: Session, context: GateContext, playbook: Playbook, settings: Settings
) -> GateResult:
    local = context.proposed_action_at_ist()
    start, end = settings.dnd_start_hour, settings.dnd_end_hour  # e.g. 21, 9: wraps midnight
    in_dnd = local.hour >= start or local.hour < end
    label = f"{start:02d}:00-{end:02d}:00 IST"
    if in_dnd:
        return GateResult(
            "quiet_hours_dnd",
            False,
            f"target time {local.strftime('%H:%M')} IST falls within the DND window ({label})",
        )
    return GateResult(
        "quiet_hours_dnd",
        True,
        f"target time {local.strftime('%H:%M')} IST is outside the DND window ({label})",
    )


# --- 7. RBI e-mandate pre-debit notification --------------------------------


def check_rbi_pre_debit_notice(
    session: Session, context: GateContext, playbook: Playbook, settings: Settings
) -> GateResult:
    if not context.is_emandate_debit:
        return GateResult(
            "rbi_emandate_pre_debit_notice", True, "not an e-mandate debit; check not applicable"
        )

    required = timedelta(hours=settings.rbi_emandate_pre_debit_notice_hours)
    if context.pre_debit_notification_sent_at is None:
        return GateResult(
            "rbi_emandate_pre_debit_notice",
            False,
            f"e-mandate debit proposed with no pre-debit notification on record "
            f"(RBI requires >= {required} notice)",
        )

    elapsed = context.proposed_action_at - context.pre_debit_notification_sent_at
    if elapsed < required:
        return GateResult(
            "rbi_emandate_pre_debit_notice",
            False,
            f"only {elapsed} between pre-debit notice and proposed debit; "
            f"RBI E-mandate Framework requires >= {required}",
        )
    return GateResult(
        "rbi_emandate_pre_debit_notice",
        True,
        f"{elapsed} between pre-debit notice and proposed debit satisfies >= {required}",
    )


# --- 8. NPCI peak-hour restriction ------------------------------------------


def check_npci_peak_hour(
    session: Session, context: GateContext, playbook: Playbook, settings: Settings
) -> GateResult:
    if not context.is_upi_autopay_execution:
        return GateResult(
            "npci_peak_hour_restriction", True, "not a UPI AutoPay execution; check not applicable"
        )

    local = context.proposed_action_at_ist()
    if _in_npci_peak_window(local.hour, local.minute):
        return GateResult(
            "npci_peak_hour_restriction",
            False,
            f"target time {local.strftime('%H:%M')} IST falls in an NPCI peak window "
            "(10:00-13:00 or 17:00-21:30 IST)",
        )
    return GateResult(
        "npci_peak_hour_restriction",
        True,
        f"target time {local.strftime('%H:%M')} IST is outside NPCI peak windows",
    )


# --- 9. Kill switch -----------------------------------------------------------


def check_kill_switch(
    session: Session, context: GateContext, playbook: Playbook, settings: Settings
) -> GateResult:
    if is_kill_switch_active(session):
        return GateResult(
            "kill_switch", False, "emergency kill switch is ACTIVE; all money actions are blocked"
        )
    return GateResult("kill_switch", True, "kill switch is INACTIVE")


# --- 10. Pre-action ledger event (readiness) --------------------------------


def check_ledger_writable(
    session: Session, context: GateContext, playbook: Playbook, settings: Settings
) -> GateResult:
    """The actual MONEY_ACTION_INTENT append happens in evaluate_gate, only on
    an overall ALLOW (checklist #10: "before any hypothetical execution").
    This check only confirms the ledger is reachable, so a DB outage fails
    this check rather than silently skipping the pre-action record."""
    try:
        list_events(session)
    except Exception as exc:  # pragma: no cover - defensive; DB failures are environmental
        return GateResult("pre_action_ledger_event", False, f"ledger is not accessible: {exc}")
    return GateResult(
        "pre_action_ledger_event",
        True,
        "ledger is accessible; MONEY_ACTION_INTENT will be emitted before ALLOW is returned",
    )


# Ordered to match the money-action-gate SKILL.md checklist numbering 1-10.
ALL_CHECKS = (
    check_idempotency,
    check_global_budget,
    check_cohort_incentive_ceiling,
    check_attempt_limits,
    check_cooldown,
    check_quiet_hours,
    check_rbi_pre_debit_notice,
    check_npci_peak_hour,
    check_kill_switch,
    check_ledger_writable,
)
