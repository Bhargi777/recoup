"""GET /api/decisions - recent POLICY_GATE_DECISION events with a plain-
English "why".

The "why" is derived deterministically from the ``reason`` field the gate
itself already wrote to the ledger (``core.policy.gate.evaluate_gate``'s
``overall_reason`` - either "all N checks passed" or
"blocked by: <check names>"). Nothing here calls an LLM or invents new
wording beyond formatting the same reason string for a human reader - per
CLAUDE.md SS4, decision reasons are deterministic and auditable.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from core.api.deps import get_session
from core.ledger import LedgerEvent, list_events

router = APIRouter(prefix="/api/decisions", tags=["decisions"])

POLICY_GATE_DECISION = "POLICY_GATE_DECISION"

_CHECK_NAME_PLAIN_ENGLISH = {
    "idempotency_verification": "this exact action was already approved for this record",
    "global_budget_meter": "the global incentive budget cap would be exceeded",
    "cohort_incentive_ceiling": "the proposed incentive exceeds this root cause's ceiling",
    "customer_attempt_limits": "the customer already received the maximum allowed attempts",
    "cooldown_interval": "not enough time has passed since the last communication",
    "quiet_hours_dnd": "the target time falls within the quiet-hours (DND) window",
    "rbi_emandate_pre_debit_notice": "the RBI 24-hour e-mandate pre-debit notice was not satisfied",
    "npci_peak_hour_restriction": "the target time falls in an NPCI UPI AutoPay peak window",
    "kill_switch": "the emergency kill switch was ACTIVE",
    "pre_action_ledger_event": "the audit ledger was not reachable",
    "not_already_settled": (
        "this record already shows a PAYMENT_LINK_PAID/SUBSCRIPTION_CHARGED event"
    ),
}


def _plain_english_why(status: str, reason: str) -> str:
    if status == "ALLOW":
        return (
            "Allowed - all policy gate checks passed (budget, attempts, cooldown, "
            "quiet hours, RBI/NPCI, kill switch, not-already-settled)."
        )
    # reason looks like "blocked by: check_a, check_b"
    failed = [c.strip() for c in reason.split("blocked by:", 1)[-1].split(",") if c.strip()]
    explained = [_CHECK_NAME_PLAIN_ENGLISH.get(c, c) for c in failed]
    return "Blocked because " + "; and ".join(explained) + "."


@router.get("")
def get_decisions(
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_session),
) -> dict:
    events = [e for e in list_events(session) if e.event_type == POLICY_GATE_DECISION]
    events.sort(key=lambda e: e.sequence_num, reverse=True)
    page = events[:limit]

    decisions = []
    for event in page:
        payload = json.loads(event.payload_json)
        status = payload.get("status", "")
        reason = payload.get("reason", "")
        decisions.append(
            {
                "sequence_num": event.sequence_num,
                "event_id": event.event_id,
                "timestamp_utc": event.timestamp_utc,
                "aggregate_id": event.aggregate_id,
                "idempotency_key": payload.get("idempotency_key"),
                "root_cause": payload.get("root_cause"),
                "cohort": payload.get("cohort"),
                "action_type": payload.get("action_type"),
                "status": status,
                "reason": reason,
                "why": _plain_english_why(status, reason),
            }
        )

    return {"total_available": len(events), "returned": len(decisions), "decisions": decisions}


def find_decision_by_key(session: Session, key: str) -> LedgerEvent | None:
    """The POLICY_GATE_DECISION event matching ``key`` - either its own
    event_id, or the idempotency_key carried in its payload. Either form is
    accepted since a decision's event_id is what the Decisions feed links
    from, but an idempotency_key is what an operator debugging a specific
    money action already has on hand from other ledger events."""
    for event in list_events(session):
        if event.event_type != POLICY_GATE_DECISION:
            continue
        if event.event_id == key:
            return event
        payload = json.loads(event.payload_json)
        if payload.get("idempotency_key") == key:
            return event
    return None


def replay_decision(session: Session, key: str) -> dict | None:
    """Full replay of one decision: the matching POLICY_GATE_DECISION event
    plus every sibling ledger event sharing its idempotency_key (every
    POLICY_GATE_EVALUATED check, MONEY_ACTION_INTENT/INCENTIVE_COMMITTED if
    ALLOWed, and whatever the executor layer or run_batch recorded), in
    sequence order, with the exact same plain-English "why"
    ``get_decisions`` already computes - reused directly via
    ``_plain_english_why``, not reimplemented. Returns None if ``key``
    matches no decision - callers (the CLI, the API route) turn that into
    an explicit "not found" response rather than an empty/silent one."""
    decision_event = find_decision_by_key(session, key)
    if decision_event is None:
        return None

    decision_payload = json.loads(decision_event.payload_json)
    idempotency_key = decision_payload.get("idempotency_key")
    status = decision_payload.get("status", "")
    reason = decision_payload.get("reason", "")

    siblings = []
    for event in list_events(session):
        payload = json.loads(event.payload_json)
        if payload.get("idempotency_key") == idempotency_key:
            siblings.append((event, payload))
    siblings.sort(key=lambda pair: pair[0].sequence_num)

    return {
        "event_id": decision_event.event_id,
        "idempotency_key": idempotency_key,
        "aggregate_id": decision_event.aggregate_id,
        "root_cause": decision_payload.get("root_cause"),
        "cohort": decision_payload.get("cohort"),
        "action_type": decision_payload.get("action_type"),
        "status": status,
        "reason": reason,
        "why": _plain_english_why(status, reason),
        "events": [
            {
                "sequence_num": e.sequence_num,
                "event_id": e.event_id,
                "timestamp_utc": e.timestamp_utc,
                "aggregate_id": e.aggregate_id,
                "event_type": e.event_type,
                "payload": p,
            }
            for e, p in siblings
        ],
    }


@router.get("/{event_id}")
def get_decision_replay(event_id: str, session: Session = Depends(get_session)) -> dict:
    """Dashboard click-through counterpart to `recoup replay` - same
    underlying replay_decision(), exposed as a route so a Decisions-feed
    card (already keyed by event_id) can link straight into this view."""
    result = replay_decision(session, event_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"no decision found for {event_id!r}")
    return result
