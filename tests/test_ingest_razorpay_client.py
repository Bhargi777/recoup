"""Unit tests against httpx.MockTransport - no network call is made.

These prove idempotency-gating, ledger event emission, error parsing, and
retry/circuit-breaker behavior. They are NOT a substitute for the live
Test Mode proof required by CLAUDE.md Phase 2 (create a real payment link
and pay it against api.razorpay.com/v1 with real rzp_test_ credentials).
"""

import json

import httpx
import pytest
from sqlmodel import Session

from core.ingest.circuit_breaker import CircuitBreaker
from core.ingest.razorpay_client import RazorpayAPIError, RazorpayClient
from core.ledger import get_engine, init_ledger_schema, list_events


@pytest.fixture()
def session():
    engine = get_engine("sqlite:///:memory:")
    init_ledger_schema(engine)
    with Session(engine) as s:
        yield s


def _client(session: Session, handler, **kwargs) -> RazorpayClient:
    transport = httpx.MockTransport(handler)
    return RazorpayClient(
        "rzp_test_dummy", "secret", session, transport=transport, max_retries=1, **kwargs
    )


def test_create_order_success_emits_intent_and_succeeded_events(session: Session) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"id": "order_abc123", "status": "created"})

    with _client(session, handler) as client:
        result = client.create_order(10000, "INR", "invoice_1")

    assert result["id"] == "order_abc123"
    assert len(calls) == 1

    events = list_events(session)
    types = [e.event_type for e in events]
    assert "RAZORPAY_CREATE_ORDER_INTENT" in types
    assert "RAZORPAY_CREATE_ORDER_SUCCEEDED" in types


def test_repeated_call_same_attempt_is_deduped_no_second_http_call(session: Session) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"id": "plink_1"})

    with _client(session, handler) as client:
        first = client.create_payment_link(5000, "INR", "recover invoice", "invoice_9")
        second = client.create_payment_link(5000, "INR", "recover invoice", "invoice_9")

    assert first == second
    assert len(calls) == 1  # second call served from the ledger, no HTTP dispatch

    types = [e.event_type for e in list_events(session)]
    assert types.count("RAZORPAY_CREATE_PAYMENT_LINK_DEDUPED") == 1


def test_different_attempt_num_is_a_distinct_idempotency_key(session: Session) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"id": f"plink_{len(calls)}"})

    with _client(session, handler) as client:
        first = client.create_payment_link(5000, "INR", "d", "invoice_9", attempt_num=0)
        second = client.create_payment_link(5000, "INR", "d", "invoice_9", attempt_num=1)

    assert first != second
    assert len(calls) == 2


def test_api_error_response_is_parsed_into_razorpay_api_error(session: Session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "BAD_REQUEST_ERROR",
                    "description": "The card is expired",
                    "source": "customer",
                    "step": "payment_authorization",
                    "reason": "card_expired",
                }
            },
        )

    with _client(session, handler) as client, pytest.raises(RazorpayAPIError) as exc_info:
        client.create_order(1000, "INR", "invoice_bad")

    err = exc_info.value
    assert err.status_code == 400
    assert err.reason == "card_expired"
    assert err.source == "customer"


def test_fetch_payment_always_dispatches_and_logs(session: Session) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"id": "pay_1", "error_reason": "insufficient_funds"})

    with _client(session, handler) as client:
        client.fetch_payment("pay_1")
        client.fetch_payment("pay_1")  # reads are not idempotency-deduped

    assert len(calls) == 2
    types = [e.event_type for e in list_events(session)]
    assert types.count("RAZORPAY_FETCH_PAYMENT") == 2


def test_5xx_retries_then_succeeds_within_max_retries(session: Session) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(502, text="bad gateway")
        return httpx.Response(200, json={"id": "order_retry_ok"})

    with _client(session, handler) as client:
        result = client.create_order(1000, "INR", "invoice_retry")

    assert result["id"] == "order_retry_ok"
    assert len(calls) == 2


def test_repeated_5xx_exhausts_retries_and_opens_circuit_breaker(session: Session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    breaker = CircuitBreaker(failure_threshold=2, reset_timeout_seconds=60)
    with (
        _client(session, handler, circuit_breaker=breaker) as client,
        pytest.raises(RazorpayAPIError),
    ):
        client.create_order(1000, "INR", "invoice_down")

    from core.ingest.circuit_breaker import CircuitState

    assert breaker.state == CircuitState.OPEN


def test_5xx_retries_are_individually_ledgered_in_order(session: Session) -> None:
    """Phase 7: the ledger must show the full retry story - every retried
    attempt, not just the eventual INTENT/SUCCEEDED bookends - so a chaos
    scenario (or an operator) can replay exactly what happened."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "order_full_story"})

    calls = {"n": 0}

    def flaky_handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(503, text="down")
        return handler(request)

    transport = httpx.MockTransport(flaky_handler)
    with RazorpayClient(
        "rzp_test_dummy", "secret", session, transport=transport, max_retries=3
    ) as client:
        client.create_order(1000, "INR", "invoice_full_story")

    events = list_events(session)
    types_in_order = [e.event_type for e in events]
    retry_events = [e for e in events if e.event_type == "RAZORPAY_CREATE_ORDER_RETRYING"]
    assert len(retry_events) == 2

    intent_idx = types_in_order.index("RAZORPAY_CREATE_ORDER_INTENT")
    succeeded_idx = types_in_order.index("RAZORPAY_CREATE_ORDER_SUCCEEDED")
    retry_type = "RAZORPAY_CREATE_ORDER_RETRYING"
    retry_indices = [i for i, t in enumerate(types_in_order) if t == retry_type]
    assert all(intent_idx < i < succeeded_idx for i in retry_indices)

    first_retry_payload = json.loads(retry_events[0].payload_json)
    assert first_retry_payload["attempt"] == 0
    assert first_retry_payload["status_code"] == 503


def test_payload_stored_in_ledger_is_canonical_json(session: Session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "order_x"})

    with _client(session, handler) as client:
        client.create_order(1000, "INR", "invoice_json")

    intent = next(e for e in list_events(session) if e.event_type == "RAZORPAY_CREATE_ORDER_INTENT")
    parsed = json.loads(intent.payload_json)
    assert parsed["request"]["receipt"] == "invoice_json"


def test_payment_link_omits_customer_key_when_not_provided(session: Session) -> None:
    """Regression test for a real bug: sending "customer": {} (rather than
    omitting the key) is rejected by Razorpay's live API with
    BAD_REQUEST_ERROR "faulty key: customer" - a validation MockTransport
    never enforces, so the mocked test suite passed while the real path was
    broken. Discovered via scripts/live_proof.py against the real API."""
    captured_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "plink_no_customer"})

    with _client(session, handler) as client:
        client.create_payment_link(5000, "INR", "recover invoice", "invoice_no_customer")

    assert "customer" not in captured_bodies[0]


def test_payment_link_includes_well_formed_customer_when_provided(session: Session) -> None:
    captured_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "plink_with_customer"})

    customer = {"name": "Jane Doe", "email": "jane@example.com"}
    with _client(session, handler) as client:
        client.create_payment_link(
            5000, "INR", "recover invoice", "invoice_with_customer", customer=customer
        )

    assert captured_bodies[0]["customer"] == customer
