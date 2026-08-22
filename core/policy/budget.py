"""Budget meter, reconstructed purely by ledger replay.

Current cumulative spend - global or per-cohort - is always ``sum()`` over
INCENTIVE_COMMITTED events read straight from the ledger, never a separately
maintained running-total column. See ``.claude/skills/audit-ledger/SKILL.md``
SS4 (state replay contract).
"""

from __future__ import annotations

import json

from sqlmodel import Session

from core.ledger import list_events
from core.policy.events import INCENTIVE_COMMITTED


def committed_spend(session: Session, cohort: str | None = None) -> float:
    """Sum of INCENTIVE_COMMITTED amounts, optionally filtered to one cohort."""
    total = 0.0
    for event in list_events(session):
        if event.event_type != INCENTIVE_COMMITTED:
            continue
        payload = json.loads(event.payload_json)
        if cohort is not None and payload.get("cohort") != cohort:
            continue
        total += float(payload.get("amount_inr", 0.0))
    return total
