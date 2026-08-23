"""GET /api/ledger (paginated) and GET /api/ledger/verify.

``/api/ledger`` returns real ``LedgerEvent`` rows straight from
``core.ledger.list_events`` - columns match ``core.ledger.models.LedgerEvent``
exactly (``sequence_num``, ``event_id``, ``timestamp_utc``, ``aggregate_id``,
``event_type``, ``previous_hash``, ``current_hash``); ``payload`` is included
too since the dashboard's decision/guardrail/metrics views all need to read
event payloads.

``/api/ledger/verify`` calls the real ``core.ledger.verify_chain`` - it is
never faked or hard-coded to ``ok: true``.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from core.api.deps import get_session
from core.ledger import list_events, verify_chain

router = APIRouter(prefix="/api/ledger", tags=["ledger"])


@router.get("")
def get_ledger(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    event_type: str | None = Query(default=None),
    aggregate_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> dict:
    events = list_events(session)
    if event_type is not None:
        events = [e for e in events if e.event_type == event_type]
    if aggregate_id is not None:
        events = [e for e in events if e.aggregate_id == aggregate_id]

    events.sort(key=lambda e: e.sequence_num, reverse=True)
    total = len(events)
    page = events[offset : offset + limit]

    rows = [
        {
            "sequence_num": e.sequence_num,
            "event_id": e.event_id,
            "timestamp_utc": e.timestamp_utc,
            "aggregate_id": e.aggregate_id,
            "event_type": e.event_type,
            "previous_hash": e.previous_hash,
            "current_hash": e.current_hash,
            "payload": json.loads(e.payload_json),
        }
        for e in page
    ]

    return {"total": total, "limit": limit, "offset": offset, "events": rows}


@router.get("/verify")
def get_ledger_verify(session: Session = Depends(get_session)) -> dict:
    result = verify_chain(session)
    return {
        "ok": result.ok,
        "events_checked": result.events_checked,
        "first_bad_sequence": result.first_bad_sequence,
        "errors": result.errors,
    }
