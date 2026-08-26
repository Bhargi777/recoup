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
from core.ingest.webhooks import PAYMENT_LINK_PAID, SUBSCRIPTION_CHARGED
from core.ledger import LedgerEvent, events_for_aggregate, list_events
from core.policy.budget import committed_spend
from core.policy.context import GateContext
from core.policy.events import ACTION_EXECUTION_FAILED, MONEY_ACTION_INTENT
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


# Per-check audit trail entries, not action outcomes - every one of the 10
# checks in a SINGLE evaluate_gate call appends its own POLICY_GATE_EVALUATED
# event carrying the SAME idempotency_key as the context being evaluated.
# Since checks run and log sequentially within one evaluate_gate call (see
# that module's docstring: "exhaustive, not short-circuiting"), a LATER
# check in that same call would otherwise see an EARLIER check's own
# POLICY_GATE_EVALUATED entry as "the most recent event for this key" and
# wrongly treat it as the final outcome - masking a real prior
# ACTION_EXECUTION_FAILED from an entirely earlier run. These two event
# types are therefore never a meaningful "outcome" for this lookup and must
# be skipped.
_GATE_PROCESS_EVENT_TYPES = frozenset({"POLICY_GATE_EVALUATED", "POLICY_GATE_DECISION"})


def _last_event_type_for_idempotency_key(
    session: Session, aggregate_id: str, idempotency_key: str
) -> str | None:
    """The most recent OUTCOME ledger event for this aggregate whose payload
    carries this idempotency_key, or None if it has never been seen.

    "Outcome" deliberately excludes POLICY_GATE_EVALUATED/POLICY_GATE_DECISION
    (see _GATE_PROCESS_EVENT_TYPES above) - the events this is meant to
    distinguish between are MONEY_ACTION_INTENT (approved, not yet resolved),
    ACTION_EXECUTION_FAILED (approved, real execution failed - retryable),
    and every real executor terminal event (approved and resolved,
    permanently blocked from re-approval). events_for_aggregate returns
    events in ascending sequence_num order, so the last matching entry is
    always the final known outcome of the most recent attempt with this key.
    """
    match: str | None = None
    for event in events_for_aggregate(session, aggregate_id):
        if event.event_type in _GATE_PROCESS_EVENT_TYPES:
            continue
        payload = json.loads(event.payload_json)
        if payload.get("idempotency_key") == idempotency_key:
            match = event.event_type
    return match


def _was_a_real_attempt(session: Session, aggregate_id: str, idempotency_key: str) -> bool:
    """True unless this idempotency_key's most recent OUTCOME event is
    ACTION_EXECUTION_FAILED - i.e. unless the communication/action this
    MONEY_ACTION_INTENT approved never actually reached the customer
    (gateway down, retries/circuit-breaker exhausted).

    check_attempt_limits and check_cooldown both scan MONEY_ACTION_INTENT
    events to count "how many times have we actually contacted this
    customer" / "when did we last actually contact them". A failed
    execution never contacted anyone, so counting it here would
    double-penalize a customer for an outage that isn't their fault: it
    would both burn an attempt out of their max_attempts budget AND start a
    cooldown clock for a message they never received - on top of
    check_idempotency correctly allowing the retry, this would still leave
    it wrongly throttled or re-blocked once retried. See
    tests/test_eval_batch_runner_recovery.py for the end-to-end case this
    fixes."""
    return (
        _last_event_type_for_idempotency_key(session, aggregate_id, idempotency_key)
        != ACTION_EXECUTION_FAILED
    )


def check_idempotency(
    session: Session, context: GateContext, playbook: Playbook, settings: Settings
) -> GateResult:
    last_type = _last_event_type_for_idempotency_key(
        session, context.aggregate_id, context.idempotency_key
    )

    if last_type is None:
        return GateResult(
            "idempotency_verification",
            True,
            "idempotency_key not previously seen for this aggregate",
        )

    if last_type == ACTION_EXECUTION_FAILED:
        # The intent was approved and ledgered, but the real executor call
        # failed (gateway down, circuit open, etc.) - no external action
        # actually happened, so this is a legitimate retry, not a duplicate.
        return GateResult(
            "idempotency_verification",
            True,
            f"idempotency_key {context.idempotency_key!r} was previously approved but its "
            "execution failed (ACTION_EXECUTION_FAILED); allowing a retry rather than "
            "permanently blocking a record whose action never actually happened",
        )

    return GateResult(
        "idempotency_verification",
        False,
        f"idempotency_key {context.idempotency_key!r} was already approved for "
        f"aggregate {context.aggregate_id!r}; refusing to re-approve as an "
        "independent action",
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
        and _was_a_real_attempt(session, context.aggregate_id, payload.get("idempotency_key"))
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
        # A MONEY_ACTION_INTENT is logged BEFORE execution (checklist #10),
        # so an intent whose real send then failed (ACTION_EXECUTION_FAILED)
        # never actually reached the customer - it must not start a
        # cooldown clock, or a transient gateway outage would wrongly block
        # a same-day recovery retry for the full cooldown window. Same
        # reasoning (and same helper) as check_attempt_limits just above.
        and _was_a_real_attempt(session, context.aggregate_id, payload.get("idempotency_key"))
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


# --- 11. Not already settled (recoup addition, beyond the original
# money-action-gate SKILL.md checklist) ---------------------------------


def _find_settlement_event(session: Session, record_id: str) -> LedgerEvent | None:
    """A PAYMENT_LINK_PAID or SUBSCRIPTION_CHARGED event that settles this
    record, if one exists in the ledger.

    A payment_link.paid webhook is ledgered under the Razorpay payment_link's
    OWN id as aggregate_id (core.ingest.webhooks._extract_aggregate_id), not
    this record's id - so a direct events_for_aggregate(record_id) lookup
    would never find it. Correlation is via ``reference_id``:
    execute_payment_link's live path creates the link with
    ``reference_id=context.aggregate_id`` (== record_id) -
    core.ingest.razorpay_client.RazorpayClient.create_payment_link - and a
    real Razorpay webhook echoes reference_id back on the entity. This scans
    for either that reference_id match or (covering subscription.charged,
    which this codebase has no subscription-creation path to set a
    reference_id for) a direct aggregate_id == record_id match.

    O(n) full-ledger scan, same pattern already used by
    check_idempotency/check_cooldown above; fine at current data volumes,
    revisit with an index if ledger size grows into the millions.
    """
    for event in list_events(session):
        if event.event_type not in (PAYMENT_LINK_PAID, SUBSCRIPTION_CHARGED):
            continue
        if event.aggregate_id == record_id:
            return event
        payload = json.loads(event.payload_json)
        raw = payload.get("raw", {})
        link_entity = raw.get("payload", {}).get("payment_link", {}).get("entity", {})
        if link_entity.get("reference_id") == record_id:
            return event
    return None


def check_not_already_settled(
    session: Session, context: GateContext, playbook: Playbook, settings: Settings
) -> GateResult:
    """Refuses any action against a record the ledger already shows as paid
    or charged - closes the gap where ``stopping_rules: [already_paid]`` is
    schema-validated (core/policy/schema.py) but was not, until this check,
    enforced anywhere at runtime. See core/chaos/scenarios.py's
    paid_during_flight scenario for the end-to-end proof."""
    settlement = _find_settlement_event(session, context.aggregate_id)
    if settlement is not None:
        return GateResult(
            "not_already_settled",
            False,
            f"{settlement.event_type} already recorded for this record "
            f"(sequence_num {settlement.sequence_num}); refusing to act on a settled record",
        )
    return GateResult(
        "not_already_settled", True, "no PAYMENT_LINK_PAID/SUBSCRIPTION_CHARGED event on record"
    )


# Ordered to match the money-action-gate SKILL.md checklist numbering 1-10,
# plus #11 (check_not_already_settled) - a recoup addition beyond the
# original SKILL.md checklist, added after a review found stopping_rules
# was schema-validated but not runtime-enforced. See README's "Guardrails"
# section for the same disclosure.
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
    check_not_already_settled,
)
