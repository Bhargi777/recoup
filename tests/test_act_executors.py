"""Action executors: allowed -> executes-or-simulates, refused -> never
executes, exactly one ledger event per call, and the payment_link dry-run
honesty guarantee (never touches the RazorpayClient's HTTP layer)."""

from datetime import UTC, datetime

import httpx
import pytest
from sqlmodel import Session

from core.act.executors import (
    ACTION_MANDATE_RETRY_SCHEDULED,
    ACTION_MESSAGE_DRAFTED,
    ACTION_PAYMENT_LINK_CANCELLED_LEDGER,
    ACTION_PAYMENT_LINK_EXECUTED_LIVE,
    ACTION_REFUSED_NOT_ALLOWED,
    ACTION_SIMULATED_DRY_RUN,
    EXCEPTION_QUEUE_ENQUEUED,
    ExecutorInputError,
    compensate_ledger_only_action,
    execute_escalate_to_human,
    execute_incentive_offer,
    execute_mandate_retry,
    execute_payment_link,
    execute_pre_debit_notification,
    execute_reminder_message,
    rollback_payment_link,
)
from core.ingest.razorpay_client import RazorpayClient
from core.ledger import get_engine, init_ledger_schema, list_events
from core.policy.context import GateContext
from core.policy.gate import PolicyDecision


@pytest.fixture()
def session():
    engine = get_engine("sqlite:///:memory:")
    init_ledger_schema(engine)
    with Session(engine) as s:
        yield s


def make_context(**overrides) -> GateContext:
    defaults = dict(
        idempotency_key="idem-1",
        aggregate_id="pay_1",
        customer_id="cust_1",
        cohort="one_time_checkout_failure",
        root_cause="card_expired",
        action_type="reminder_message",
        proposed_action_at=datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
        now=datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
    )
    defaults.update(overrides)
    return GateContext(**defaults)


ALLOWED = PolicyDecision(allowed=True, results=(), reason="all checks passed")
REFUSED = PolicyDecision(allowed=False, results=(), reason="blocked by: kill_switch")


# --- refusal is a real path for every executor -------------------------------


def test_reminder_message_refuses_when_not_allowed(session):
    result = execute_reminder_message(session, REFUSED, make_context(), amount_inr=500)
    assert result.status == "refused"
    events = list_events(session)
    assert [e.event_type for e in events] == [ACTION_REFUSED_NOT_ALLOWED]


def test_incentive_offer_refuses_when_not_allowed(session):
    result = execute_incentive_offer(session, REFUSED, make_context(), amount_inr=500)
    assert result.status == "refused"
    assert [e.event_type for e in list_events(session)] == [ACTION_REFUSED_NOT_ALLOWED]


def test_pre_debit_notification_refuses_when_not_allowed(session):
    result = execute_pre_debit_notification(
        session, REFUSED, make_context(), amount_inr=500, notice_hours=24
    )
    assert result.status == "refused"
    assert [e.event_type for e in list_events(session)] == [ACTION_REFUSED_NOT_ALLOWED]


def test_mandate_retry_refuses_when_not_allowed(session):
    result = execute_mandate_retry(session, REFUSED, make_context())
    assert result.status == "refused"
    assert [e.event_type for e in list_events(session)] == [ACTION_REFUSED_NOT_ALLOWED]


def test_escalate_to_human_refuses_when_not_allowed(session):
    result = execute_escalate_to_human(session, REFUSED, make_context())
    assert result.status == "refused"
    assert [e.event_type for e in list_events(session)] == [ACTION_REFUSED_NOT_ALLOWED]


def test_payment_link_refuses_when_not_allowed(session):
    result = execute_payment_link(
        session, REFUSED, make_context(), mode="dry_run", amount_inr=500, description="d"
    )
    assert result.status == "refused"
    assert [e.event_type for e in list_events(session)] == [ACTION_REFUSED_NOT_ALLOWED]


# --- allowed path: exactly one ledger event, correct content -----------------


def test_reminder_message_allowed_drafts_and_logs_one_event(session):
    result = execute_reminder_message(session, ALLOWED, make_context(), amount_inr=500)
    assert result.status == "drafted"
    assert "500" in result.detail["message"]
    events = list_events(session)
    assert [e.event_type for e in events] == [ACTION_MESSAGE_DRAFTED]
    import json

    payload = json.loads(events[0].payload_json)
    assert payload["dispatched"] is False


def test_incentive_offer_allowed_uses_incentive_amount(session):
    ctx = make_context(
        root_cause="insufficient_funds", action_type="incentive_offer", incentive_amount_inr=150
    )
    result = execute_incentive_offer(session, ALLOWED, ctx, amount_inr=2000)
    assert result.status == "drafted"
    assert "150" in result.detail["message"]


def test_pre_debit_notification_allowed_logs_one_event(session):
    result = execute_pre_debit_notification(
        session, ALLOWED, make_context(), amount_inr=1000, notice_hours=24
    )
    assert result.status == "drafted"
    assert [e.event_type for e in list_events(session)] == [ACTION_MESSAGE_DRAFTED]


def test_mandate_retry_allowed_logs_scheduled_not_executed(session):
    result = execute_mandate_retry(session, ALLOWED, make_context())
    assert result.status == "scheduled"
    events = list_events(session)
    assert [e.event_type for e in events] == [ACTION_MANDATE_RETRY_SCHEDULED]
    import json

    payload = json.loads(events[0].payload_json)
    assert payload["executed"] is False


def test_escalate_to_human_allowed_enqueues_exception(session):
    result = execute_escalate_to_human(session, ALLOWED, make_context())
    assert result.status == "exception_queued"
    assert [e.event_type for e in list_events(session)] == [EXCEPTION_QUEUE_ENQUEUED]


# --- payment_link: the dry-run honesty guarantee ------------------------------


def test_payment_link_dry_run_never_touches_http_layer(session):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        calls.append(request)
        return httpx.Response(200, json={"id": "plink_should_never_happen"})

    # A client that WOULD fail loudly if ever dispatched to, to prove
    # dry-run mode truly never constructs/uses a client.
    transport = httpx.MockTransport(handler)
    spy_client = RazorpayClient(
        "rzp_test_dummy", "secret", session, transport=transport, max_retries=0
    )

    result = execute_payment_link(
        session,
        ALLOWED,
        make_context(action_type="payment_link"),
        mode="dry_run",
        amount_inr=500,
        description="recover payment",
        client=spy_client,  # even if a caller passed one in, dry-run must ignore it
    )

    assert result.status == "simulated_dry_run"
    assert calls == []  # no HTTP request was ever made
    events = list_events(session)
    assert [e.event_type for e in events] == [ACTION_SIMULATED_DRY_RUN]
    import json

    payload = json.loads(events[0].payload_json)
    assert payload["executed"] is False


def test_payment_link_dry_run_works_with_no_client_at_all(session):
    result = execute_payment_link(
        session,
        ALLOWED,
        make_context(action_type="payment_link"),
        mode="dry_run",
        amount_inr=500,
        description="recover payment",
    )
    assert result.status == "simulated_dry_run"


def test_payment_link_live_calls_client_and_logs_executed(session):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "plink_real_1", "status": "created"})

    transport = httpx.MockTransport(handler)
    client = RazorpayClient("rzp_test_dummy", "secret", session, transport=transport)

    result = execute_payment_link(
        session,
        ALLOWED,
        make_context(action_type="payment_link"),
        mode="live",
        amount_inr=500,
        description="recover payment",
        client=client,
    )
    assert result.status == "executed_live"
    assert result.detail["response"]["id"] == "plink_real_1"
    types = [e.event_type for e in list_events(session)]
    assert ACTION_PAYMENT_LINK_EXECUTED_LIVE in types


def test_payment_link_live_without_client_raises():
    with pytest.raises(ExecutorInputError):
        execute_payment_link(
            None,  # type: ignore[arg-type]
            ALLOWED,
            make_context(),
            mode="live",
            amount_inr=500,
            description="d",
        )


def test_payment_link_unknown_mode_raises(session):
    with pytest.raises(ExecutorInputError):
        execute_payment_link(
            session,
            ALLOWED,
            make_context(),
            mode="not_a_real_mode",
            amount_inr=500,
            description="d",
        )


# --- rollback / compensate ------------------------------------------------------


def test_rollback_payment_link_is_ledger_only(session):
    ctx = make_context(action_type="payment_link")
    result = rollback_payment_link(session, ctx, "plink_real_1")
    assert result.status == "compensated"
    events = list_events(session)
    assert [e.event_type for e in events] == [ACTION_PAYMENT_LINK_CANCELLED_LEDGER]


def test_compensate_ledger_only_action_logs_one_event(session):
    ctx = make_context(action_type="reminder_message")
    result = compensate_ledger_only_action(session, ctx, "reminder_message")
    assert result.status == "compensated"
    events = list_events(session)
    assert len(events) == 1
