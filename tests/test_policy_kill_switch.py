"""Kill switch state is reconstructed purely by replaying ledger events - no
parallel mutable table exists. Same determinism spirit as
tests/test_ledger_verify.py."""

import pytest
from sqlmodel import Session

from core.ledger import get_engine, init_ledger_schema, list_events
from core.policy.events import KILL_SWITCH_ACTIVATED, KILL_SWITCH_DEACTIVATED
from core.policy.kill_switch import (
    activate_kill_switch,
    deactivate_kill_switch,
    is_kill_switch_active,
)


@pytest.fixture()
def session():
    engine = get_engine("sqlite:///:memory:")
    init_ledger_schema(engine)
    with Session(engine) as s:
        yield s


def test_default_state_is_inactive(session):
    assert is_kill_switch_active(session) is False


def test_activate_then_active(session):
    activate_kill_switch(session, "incident-1")
    assert is_kill_switch_active(session) is True


def test_activate_then_deactivate(session):
    activate_kill_switch(session, "incident-1")
    deactivate_kill_switch(session, "resolved")
    assert is_kill_switch_active(session) is False


def test_state_is_whichever_event_is_most_recent_in_a_long_sequence(session):
    sequence = [
        activate_kill_switch,
        deactivate_kill_switch,
        activate_kill_switch,
        activate_kill_switch,  # idempotent re-activation is allowed
        deactivate_kill_switch,
        deactivate_kill_switch,  # idempotent re-deactivation is allowed
        activate_kill_switch,
    ]
    for fn in sequence:
        fn(session, "toggle")
    # last call was activate -> should be active
    assert is_kill_switch_active(session) is True


def test_toggle_events_are_hash_chained_like_any_other_ledger_event(session):
    activate_kill_switch(session, "incident")
    deactivate_kill_switch(session, "resolved")
    kill_switch_types = {KILL_SWITCH_ACTIVATED, KILL_SWITCH_DEACTIVATED}
    events = [e for e in list_events(session) if e.event_type in kill_switch_types]
    assert [e.event_type for e in events] == [KILL_SWITCH_ACTIVATED, KILL_SWITCH_DEACTIVATED]
    assert events[1].previous_hash == events[0].current_hash


def test_replay_is_deterministic_regardless_of_query_repetition(session):
    activate_kill_switch(session, "a")
    deactivate_kill_switch(session, "b")
    activate_kill_switch(session, "c")
    first = is_kill_switch_active(session)
    second = is_kill_switch_active(session)
    third = is_kill_switch_active(session)
    assert first == second == third is True
