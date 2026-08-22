"""The composed evaluate_gate: overall ALLOW/DENY, ledger events emitted for
every check plus the overall decision, budget-meter and kill-switch
interaction, and the idempotency red-team guarantee."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlmodel import Session

from core.config import Settings
from core.ledger import get_engine, init_ledger_schema, list_events
from core.policy import GateContext, evaluate_gate
from core.policy.events import (
    INCENTIVE_COMMITTED,
    MONEY_ACTION_INTENT,
    POLICY_GATE_DECISION,
    POLICY_GATE_EVALUATED,
)
from core.policy.kill_switch import activate_kill_switch

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture()
def session():
    engine = get_engine("sqlite:///:memory:")
    init_ledger_schema(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def settings():
    return Settings(razorpay_key_id="rzp_test_dummy")


def ist_utc(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=IST).astimezone(UTC)


def make_context(**overrides):
    defaults = dict(
        idempotency_key="idem-1",
        aggregate_id="pay_1",
        customer_id="cust_1",
        cohort="one_time_checkout_failure",
        root_cause="card_expired",
        action_type="reminder_message",
        proposed_action_at=ist_utc(2026, 8, 24, 12, 0),
        now=ist_utc(2026, 8, 24, 12, 0),
    )
    defaults.update(overrides)
    return GateContext(**defaults)


def test_clean_action_is_allowed(session, settings):
    decision = evaluate_gate(session, make_context(), settings=settings)
    assert decision.allowed
    assert all(r.allowed for r in decision.results)
    assert len(decision.results) == 10


def test_denied_action_reports_reasons_without_swallowing_them(session, settings):
    # Proposed at 22:00 IST -> DND violation is the only failing check.
    ctx = make_context(proposed_action_at=ist_utc(2026, 8, 24, 22, 0))
    decision = evaluate_gate(session, ctx, settings=settings)
    assert not decision.allowed
    failed = [r.check_name for r in decision.results if not r.allowed]
    assert failed == ["quiet_hours_dnd"]
    assert "quiet_hours_dnd" in decision.reason


def test_every_check_and_the_overall_decision_are_logged(session, settings):
    evaluate_gate(session, make_context(), settings=settings)
    events = list_events(session)
    evaluated = [e for e in events if e.event_type == POLICY_GATE_EVALUATED]
    decisions = [e for e in events if e.event_type == POLICY_GATE_DECISION]
    assert len(evaluated) == 10
    assert len(decisions) == 1


def test_deny_does_not_emit_money_action_intent(session, settings):
    ctx = make_context(proposed_action_at=ist_utc(2026, 8, 24, 22, 0))
    decision = evaluate_gate(session, ctx, settings=settings)
    assert not decision.allowed
    events = list_events(session)
    assert not any(e.event_type == MONEY_ACTION_INTENT for e in events)


def test_allow_emits_money_action_intent_before_returning(session, settings):
    decision = evaluate_gate(session, make_context(), settings=settings)
    assert decision.allowed
    events = list_events(session)
    intents = [e for e in events if e.event_type == MONEY_ACTION_INTENT]
    assert len(intents) == 1


def test_allow_with_incentive_emits_incentive_committed(session, settings):
    ctx = make_context(
        root_cause="insufficient_funds", action_type="incentive_offer", incentive_amount_inr=100
    )
    decision = evaluate_gate(session, ctx, settings=settings)
    assert decision.allowed
    events = list_events(session)
    committed = [e for e in events if e.event_type == INCENTIVE_COMMITTED]
    assert len(committed) == 1


def test_allow_without_incentive_emits_no_incentive_committed(session, settings):
    decision = evaluate_gate(session, make_context(), settings=settings)
    assert decision.allowed
    events = list_events(session)
    assert not any(e.event_type == INCENTIVE_COMMITTED for e in events)


# --- kill switch overrides everything ----------------------------------------


def test_kill_switch_active_forces_deny_even_when_all_else_passes(session, settings):
    activate_kill_switch(session, "manual halt")
    decision = evaluate_gate(session, make_context(), settings=settings)
    assert not decision.allowed
    kill_switch_result = next(r for r in decision.results if r.check_name == "kill_switch")
    assert not kill_switch_result.allowed


# --- budget meter across repeated calls --------------------------------------


def test_budget_meter_blocks_once_exhausted_across_calls(session):
    tight_settings = Settings(razorpay_key_id="rzp_test_dummy", max_global_budget_inr=150)
    ctx1 = make_context(
        idempotency_key="a",
        aggregate_id="pay_a",
        root_cause="insufficient_funds",
        action_type="incentive_offer",
        incentive_amount_inr=100,
    )
    decision1 = evaluate_gate(session, ctx1, settings=tight_settings)
    assert decision1.allowed  # 0 + 100 <= 150

    ctx2 = make_context(
        idempotency_key="b",
        aggregate_id="pay_b",
        root_cause="insufficient_funds",
        action_type="incentive_offer",
        incentive_amount_inr=100,
    )
    decision2 = evaluate_gate(session, ctx2, settings=tight_settings)
    assert not decision2.allowed  # 100 + 100 > 150
    budget_result = next(r for r in decision2.results if r.check_name == "global_budget_meter")
    assert not budget_result.allowed


# --- red-team: idempotency key reuse must never be independently approved --


def test_red_team_duplicate_idempotency_key_is_not_reapproved(session, settings):
    ctx = make_context()
    first = evaluate_gate(session, ctx, settings=settings)
    assert first.allowed

    # Same idempotency_key, same aggregate - a naive re-invocation must be
    # recognized as a duplicate, never independently re-approved.
    second = evaluate_gate(session, ctx, settings=settings)
    assert not second.allowed
    idem_result = next(r for r in second.results if r.check_name == "idempotency_verification")
    assert not idem_result.allowed

    # Only one MONEY_ACTION_INTENT was ever committed for this key.
    events = list_events(session)
    intents = [
        e
        for e in events
        if e.event_type == MONEY_ACTION_INTENT
    ]
    assert len(intents) == 1
