"""Emergency kill switch, reconstructed purely by ledger replay.

No mutable "is_active" row exists anywhere. Current state is always derived
from the sequence of KILL_SWITCH_ACTIVATED / KILL_SWITCH_DEACTIVATED events -
the same replay contract audit-ledger SKILL.md SS4 requires for every other
piece of derived state.
"""

from __future__ import annotations

from sqlmodel import Session

from core.ledger import append_event, events_for_aggregate
from core.policy.events import (
    KILL_SWITCH_ACTIVATED,
    KILL_SWITCH_AGGREGATE_ID,
    KILL_SWITCH_DEACTIVATED,
)

_KILL_SWITCH_EVENT_TYPES = frozenset({KILL_SWITCH_ACTIVATED, KILL_SWITCH_DEACTIVATED})


def is_kill_switch_active(session: Session) -> bool:
    """Replay all kill-switch events and return whether the most recent one
    (by sequence_num - ledger append order, never wall-clock time) was an
    activation. An empty history means inactive (the safe default)."""
    events = [
        e
        for e in events_for_aggregate(session, KILL_SWITCH_AGGREGATE_ID)
        if e.event_type in _KILL_SWITCH_EVENT_TYPES
    ]
    if not events:
        return False
    latest = max(events, key=lambda e: e.sequence_num)
    return latest.event_type == KILL_SWITCH_ACTIVATED


def activate_kill_switch(session: Session, reason: str) -> None:
    append_event(
        session,
        aggregate_id=KILL_SWITCH_AGGREGATE_ID,
        event_type=KILL_SWITCH_ACTIVATED,
        payload={"reason": reason},
    )


def deactivate_kill_switch(session: Session, reason: str) -> None:
    append_event(
        session,
        aggregate_id=KILL_SWITCH_AGGREGATE_ID,
        event_type=KILL_SWITCH_DEACTIVATED,
        payload={"reason": reason},
    )
