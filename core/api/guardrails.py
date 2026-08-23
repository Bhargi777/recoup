"""GET /api/guardrails - blocked decisions with their per-check breakdown.

IMPORTANT distinction (see the Phase 8 task brief / README): a guardrail
correctly BLOCKING a proposed action is the system working as designed, not
a violation. This endpoint surfaces exactly that - every
``POLICY_GATE_EVALUATED`` event with ``status="BLOCKED"``, grouped by
``rule_name`` (check) and joined back to its overall
``POLICY_GATE_DECISION`` for context - real per-check block reasons real
callers can inspect, never a fabricated summary.
"""

from __future__ import annotations

import json
from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from core.api.deps import get_session
from core.ledger import list_events

router = APIRouter(prefix="/api/guardrails", tags=["guardrails"])

POLICY_GATE_EVALUATED = "POLICY_GATE_EVALUATED"
POLICY_GATE_DECISION = "POLICY_GATE_DECISION"


@router.get("")
def get_guardrails(
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> dict:
    events = list_events(session)

    blocked_checks = [
        e for e in events if e.event_type == POLICY_GATE_EVALUATED
        and json.loads(e.payload_json).get("status") == "BLOCKED"
    ]

    # overall decision reason, keyed by idempotency_key, for context alongside
    # each individual blocked check.
    decision_by_key: dict[str, dict] = {}
    for e in events:
        if e.event_type != POLICY_GATE_DECISION:
            continue
        payload = json.loads(e.payload_json)
        key = payload.get("idempotency_key")
        if key:
            decision_by_key[key] = payload

    reasons_by_check: Counter[str] = Counter()
    rows = []
    for e in sorted(blocked_checks, key=lambda e: e.sequence_num, reverse=True):
        payload = json.loads(e.payload_json)
        rule_name = payload.get("rule_name", "")
        reasons_by_check[rule_name] += 1
        decision = decision_by_key.get(payload.get("idempotency_key"), {})
        rows.append(
            {
                "sequence_num": e.sequence_num,
                "timestamp_utc": e.timestamp_utc,
                "aggregate_id": e.aggregate_id,
                "idempotency_key": payload.get("idempotency_key"),
                "check_name": rule_name,
                "reason": payload.get("reason", ""),
                "root_cause": decision.get("root_cause"),
                "cohort": decision.get("cohort"),
                "action_type": decision.get("action_type"),
            }
        )

    # Distinct blocked (aggregate, idempotency_key) pairs - one proposed
    # action can fail more than one check; this is the "correctly blocked
    # actions" count, distinct from the raw per-check row count above.
    distinct_blocked_actions = {
        (row["aggregate_id"], row["idempotency_key"]) for row in rows
    }

    return {
        "blocked_check_events": len(rows),
        "distinct_blocked_actions": len(distinct_blocked_actions),
        "reasons_by_check": dict(reasons_by_check),
        "blocks": rows[:limit],
    }
