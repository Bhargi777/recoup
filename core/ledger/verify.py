"""Hash-chain verification and tamper localization.

Implements the tamper-detection contract from
``.claude/skills/audit-ledger/SKILL.md``: recompute every hash, check the
chain links, and check monotonic sequence/timestamp ordering.
"""

import json
from dataclasses import dataclass, field

from sqlmodel import Session

from core.ledger.hashing import compute_hash
from core.ledger.models import GENESIS_HASH
from core.ledger.store import list_events


@dataclass
class VerificationResult:
    ok: bool
    events_checked: int
    first_bad_sequence: int | None = None
    errors: list[str] = field(default_factory=list)


def verify_chain(session: Session) -> VerificationResult:
    events = list_events(session)
    if not events:
        return VerificationResult(ok=True, events_checked=0)

    errors: list[str] = []
    first_bad: int | None = None
    expected_previous_hash = GENESIS_HASH
    expected_sequence = 0
    last_timestamp = ""

    for event in events:
        event_errors: list[str] = []

        if event.sequence_num != expected_sequence:
            event_errors.append(
                f"sequence_num {event.sequence_num} is not the expected {expected_sequence}"
            )

        if event.previous_hash != expected_previous_hash:
            event_errors.append(
                f"previous_hash {event.previous_hash} does not match prior current_hash "
                f"{expected_previous_hash}"
            )

        if event.timestamp_utc < last_timestamp:
            event_errors.append(
                f"timestamp_utc {event.timestamp_utc} is earlier than prior {last_timestamp}"
            )

        recomputed = compute_hash(
            event.sequence_num,
            event.timestamp_utc,
            event.aggregate_id,
            event.event_type,
            json.loads(event.payload_json),
            event.previous_hash,
        )
        if recomputed != event.current_hash:
            event_errors.append(
                f"current_hash {event.current_hash} does not match recomputed {recomputed}"
            )

        if event_errors:
            if first_bad is None:
                first_bad = event.sequence_num
            errors.extend(f"sequence {event.sequence_num}: {msg}" for msg in event_errors)

        expected_previous_hash = event.current_hash
        expected_sequence = event.sequence_num + 1
        last_timestamp = event.timestamp_utc

    return VerificationResult(
        ok=first_bad is None,
        events_checked=len(events),
        first_bad_sequence=first_bad,
        errors=errors,
    )
