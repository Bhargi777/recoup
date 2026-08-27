import threading

import pytest
from sqlmodel import Session

from core.ledger.models import GENESIS_HASH
from core.ledger.store import (
    append_event,
    events_for_aggregate,
    get_engine,
    init_ledger_schema,
    list_events,
)


@pytest.fixture()
def session():
    engine = get_engine("sqlite:///:memory:")
    init_ledger_schema(engine)
    with Session(engine) as s:
        yield s


def test_first_event_chains_to_genesis(session: Session) -> None:
    event = append_event(session, "pay_1", "INGESTED", {"amount": 100})
    assert event.sequence_num == 0
    assert event.previous_hash == GENESIS_HASH
    assert len(event.current_hash) == 64


def test_sequence_and_chain_are_monotonic(session: Session) -> None:
    e0 = append_event(session, "pay_1", "INGESTED", {"a": 1})
    e1 = append_event(session, "pay_1", "DIAGNOSED", {"b": 2})
    e2 = append_event(session, "pay_2", "INGESTED", {"c": 3})

    assert [e.sequence_num for e in (e0, e1, e2)] == [0, 1, 2]
    assert e1.previous_hash == e0.current_hash
    assert e2.previous_hash == e1.current_hash


def test_list_events_returns_ascending_order(session: Session) -> None:
    for i in range(5):
        append_event(session, "pay_1", "EVENT", {"i": i})
    events = list_events(session)
    assert [e.sequence_num for e in events] == [0, 1, 2, 3, 4]


def test_payload_is_canonicalized_on_write(session: Session) -> None:
    event = append_event(session, "pay_1", "EVENT", {"z": 1, "a": 2})
    assert event.payload_json == '{"a":2,"z":1}'


def test_events_for_aggregate_filters_and_preserves_order(session: Session) -> None:
    append_event(session, "pay_1", "INGESTED", {})
    append_event(session, "pay_2", "INGESTED", {})
    append_event(session, "pay_1", "DIAGNOSED", {})
    append_event(session, "pay_1", "ACTION_TAKEN", {})

    events = events_for_aggregate(session, "pay_1")
    assert [e.event_type for e in events] == ["INGESTED", "DIAGNOSED", "ACTION_TAKEN"]
    assert all(e.aggregate_id == "pay_1" for e in events)


def test_concurrent_appends_never_collide_and_stay_contiguous(tmp_path) -> None:
    """Regression guard for the UNIQUE constraint failed: ledger_events.sequence_num
    race: two threads appending at the same time must never compute the same
    next sequence_num. Uses a real file-backed DB (not :memory:) so separate
    threads' separate Session objects actually share one database, the same
    way two concurrent FastAPI request threads do in ``recoup serve``."""
    db_path = tmp_path / "concurrent.db"
    engine = get_engine(f"sqlite:///{db_path}")
    init_ledger_schema(engine)

    appends_per_thread = 25
    thread_count = 8
    errors: list[Exception] = []

    def worker(n: int) -> None:
        try:
            with Session(engine) as s:
                for i in range(appends_per_thread):
                    append_event(s, f"pay_{n}", "EVENT", {"i": i})
        except Exception as exc:  # noqa: BLE001 - captured to fail the test explicitly
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(thread_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []

    with Session(engine) as s:
        events = list_events(s)

    total = thread_count * appends_per_thread
    assert len(events) == total
    sequence_nums = [e.sequence_num for e in events]
    assert sequence_nums == list(range(total))  # contiguous, no gaps, no duplicates
