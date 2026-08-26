"""Append-only access to the audit ledger.

No update or delete path exists here by design: mutating a past row is a
tamper event, not a supported operation. See
``.claude/skills/audit-ledger/SKILL.md``.
"""

import threading
import uuid
from typing import Any

from sqlmodel import Session, SQLModel, create_engine, select

from core.ledger.hashing import canonicalize_payload, compute_hash
from core.ledger.models import GENESIS_HASH, LedgerEvent, utc_now_iso

# Serializes the read-HEAD-then-insert critical section below across threads
# within one process (e.g. FastAPI's threadpool executing two concurrent
# requests that both append events). This makes a single-process deployment
# safe against the exact race append_event's docstring already flagged;
# multiple separate processes/machines writing to the same database still
# need external serialization (a DB-level lock), which is unchanged.
_APPEND_LOCK = threading.Lock()


def get_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


def init_ledger_schema(engine) -> None:
    SQLModel.metadata.create_all(engine, tables=[LedgerEvent.__table__])


def _latest_event(session: Session) -> LedgerEvent | None:
    statement = select(LedgerEvent).order_by(LedgerEvent.sequence_num.desc()).limit(1)
    return session.exec(statement).first()


def append_event(
    session: Session,
    aggregate_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> LedgerEvent:
    """Append one immutable event, chaining it to the current HEAD.

    Reads-then-writes HEAD; serialized process-wide by ``_APPEND_LOCK`` so two
    threads (e.g. two concurrent FastAPI requests) can never both read the
    same HEAD and race on ``sequence_num``. Multiple separate writer
    processes/machines still need external serialization (a DB-level lock)
    to avoid a fork in the chain.
    """
    with _APPEND_LOCK:
        previous = _latest_event(session)
        sequence_num = 0 if previous is None else previous.sequence_num + 1
        previous_hash = GENESIS_HASH if previous is None else previous.current_hash
        timestamp_utc = utc_now_iso()

        current_hash = compute_hash(
            sequence_num, timestamp_utc, aggregate_id, event_type, payload, previous_hash
        )

        event = LedgerEvent(
            sequence_num=sequence_num,
            event_id=f"evt_{uuid.uuid4().hex}",
            timestamp_utc=timestamp_utc,
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload_json=canonicalize_payload(payload),
            previous_hash=previous_hash,
            current_hash=current_hash,
        )
        session.add(event)
        session.commit()
        session.refresh(event)
        return event


def list_events(session: Session) -> list[LedgerEvent]:
    statement = select(LedgerEvent).order_by(LedgerEvent.sequence_num.asc())
    return list(session.exec(statement).all())


def events_for_aggregate(session: Session, aggregate_id: str) -> list[LedgerEvent]:
    """All events for one aggregate (e.g. a customer or payment) in sequence order.

    Used by state-replay projections (per-customer cooldowns, retry counts) so
    they never have to scan the full ledger to answer one aggregate's history.
    """
    statement = (
        select(LedgerEvent)
        .where(LedgerEvent.aggregate_id == aggregate_id)
        .order_by(LedgerEvent.sequence_num.asc())
    )
    return list(session.exec(statement).all())
