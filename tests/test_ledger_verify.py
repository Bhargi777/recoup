import pytest
from sqlalchemy import text
from sqlmodel import Session

from core.ledger.store import append_event, get_engine, init_ledger_schema
from core.ledger.verify import verify_chain


@pytest.fixture()
def session():
    engine = get_engine("sqlite:///:memory:")
    init_ledger_schema(engine)
    with Session(engine) as s:
        yield s


def test_empty_ledger_verifies_ok(session: Session) -> None:
    result = verify_chain(session)
    assert result.ok is True
    assert result.events_checked == 0


def test_untampered_chain_verifies_ok(session: Session) -> None:
    for i in range(10):
        append_event(session, "pay_1", "EVENT", {"i": i})
    result = verify_chain(session)
    assert result.ok is True
    assert result.events_checked == 10
    assert result.first_bad_sequence is None
    assert result.errors == []


def test_tampered_payload_is_detected_at_exact_sequence(session: Session) -> None:
    for i in range(5):
        append_event(session, "pay_1", "EVENT", {"i": i})

    # Simulate an attacker editing row 2's payload in place, without recomputing hashes.
    session.execute(
        text("UPDATE ledger_events SET payload_json = '{\"i\"\\:999}' WHERE sequence_num = 2")
    )
    session.commit()

    result = verify_chain(session)
    assert result.ok is False
    assert result.first_bad_sequence == 2
    assert any("current_hash" in e for e in result.errors)


def test_tampered_previous_hash_breaks_the_chain_at_next_link(session: Session) -> None:
    for i in range(5):
        append_event(session, "pay_1", "EVENT", {"i": i})

    session.execute(
        text(
            "UPDATE ledger_events SET previous_hash = 'deadbeef' || previous_hash "
            "WHERE sequence_num = 3"
        )
    )
    session.commit()

    result = verify_chain(session)
    assert result.ok is False
    assert result.first_bad_sequence == 3
