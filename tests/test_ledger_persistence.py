"""Proves the ledger survives a real file-backed SQLite DB across separate connections.

In-memory session tests alone would not catch bugs where state only looks
correct because it never left process memory.
"""

from sqlmodel import Session

from core.ledger.store import append_event, get_engine, init_ledger_schema, list_events
from core.ledger.verify import verify_chain


def test_chain_survives_reopening_the_database_file(tmp_path) -> None:
    db_path = tmp_path / "persist.db"
    db_url = f"sqlite:///{db_path}"

    write_engine = get_engine(db_url)
    init_ledger_schema(write_engine)
    with Session(write_engine) as session:
        append_event(session, "pay_1", "INGESTED", {"amount": 100})
        append_event(session, "pay_1", "DIAGNOSED", {"root_cause": "insufficient_funds"})
        append_event(session, "pay_1", "ACTION_TAKEN", {"action": "payment_link"})
    write_engine.dispose()

    assert db_path.exists()

    read_engine = get_engine(db_url)
    with Session(read_engine) as session:
        events = list_events(session)
        result = verify_chain(session)

    assert len(events) == 3
    assert [e.sequence_num for e in events] == [0, 1, 2]
    assert result.ok is True
    assert result.events_checked == 3
