"""GET /api/decisions - recent POLICY_GATE_DECISION events with a plain-
English "why".

The "why" is derived deterministically from the ``reason`` field the gate
itself already wrote to the ledger (``core.policy.gate.evaluate_gate``'s
``overall_reason`` - either "all 10 checks passed" or
"blocked by: <check names>"). Nothing here calls an LLM or invents new
wording beyond formatting the same reason string for a human reader - per
CLAUDE.md SS4, decision reasons are deterministic and auditable.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from core.api.deps import get_session
from core.ledger import list_events

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
}


def _plain_english_why(status: str, reason: str) -> str:
    if status == "ALLOW":
        return (
            "Allowed - all 10 policy gate checks passed (budget, attempts, cooldown, "
            "quiet hours, RBI/NPCI, kill switch)."
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
