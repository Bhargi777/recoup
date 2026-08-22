import hashlib
import hmac
import json

import pytest
from sqlmodel import Session

from core.ingest.webhooks import (
    EVENT_ID_HEADER,
    handle_webhook_event,
    verify_signature,
)
from core.ledger import get_engine, init_ledger_schema, list_events

SECRET = "whsec_test_dummy"


@pytest.fixture()
def session():
    engine = get_engine("sqlite:///:memory:")
    init_ledger_schema(engine)
    with Session(engine) as s:
        yield s


def _sign(body: bytes) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_verify_signature_accepts_valid_hmac() -> None:
    body = b'{"event":"payment.failed"}'
    assert verify_signature(body, _sign(body), SECRET) is True


def test_verify_signature_rejects_tampered_body() -> None:
    body = b'{"event":"payment.failed"}'
    sig = _sign(body)
    tampered = b'{"event":"payment.captured"}'
    assert verify_signature(tampered, sig, SECRET) is False


def test_verify_signature_rejects_missing_header() -> None:
    assert verify_signature(b"{}", "", SECRET) is False


def _payment_failed_body(payment_id: str = "pay_1") -> bytes:
    return json.dumps(
        {
            "event": "payment.failed",
            "payload": {
                "payment": {
                    "entity": {
                        "id": payment_id,
                        "error_reason": "insufficient_funds",
                    }
                }
            },
        }
    ).encode()


def test_payment_failed_event_is_recorded_against_payment_id(session: Session) -> None:
    body = _payment_failed_body("pay_42")
    result = handle_webhook_event(session, body, {EVENT_ID_HEADER: "evt_1"})
    assert result == {
        "status": "recorded",
        "event_name": "payment.failed",
        "aggregate_id": "pay_42",
    }
    events = list_events(session)
    assert any(e.event_type == "PAYMENT_FAILED" and e.aggregate_id == "pay_42" for e in events)
    assert any(e.event_type == "WEBHOOK_RECEIVED" for e in events)


def test_duplicate_event_id_is_a_no_op(session: Session) -> None:
    body = _payment_failed_body("pay_1")
    handle_webhook_event(session, body, {EVENT_ID_HEADER: "evt_dup"})
    result = handle_webhook_event(session, body, {EVENT_ID_HEADER: "evt_dup"})

    assert result["status"] == "duplicate"
    domain_events = [e for e in list_events(session) if e.event_type == "PAYMENT_FAILED"]
    assert len(domain_events) == 1  # never recorded twice


def test_duplicate_webhook_never_double_creates_downstream_state(session: Session) -> None:
    """A duplicate payment_link.paid delivery must not be able to trigger a
    second payment link creation - this is the ledger-level guarantee that
    makes that true regardless of what the executor layer eventually does."""
    body = json.dumps(
        {
            "event": "payment_link.paid",
            "payload": {"payment_link": {"entity": {"id": "plink_1"}}},
        }
    ).encode()

    first = handle_webhook_event(session, body, {EVENT_ID_HEADER: "evt_plink"})
    second = handle_webhook_event(session, body, {EVENT_ID_HEADER: "evt_plink"})

    assert first["status"] == "recorded"
    assert second["status"] == "duplicate"
    paid_events = [e for e in list_events(session) if e.event_type == "PAYMENT_LINK_PAID"]
    assert len(paid_events) == 1


def test_unrecognized_event_is_recorded_but_not_routed(session: Session) -> None:
    body = json.dumps({"event": "refund.created", "payload": {}}).encode()
    result = handle_webhook_event(session, body, {EVENT_ID_HEADER: "evt_unknown"})
    assert result["status"] == "unrecognized"
    types = [e.event_type for e in list_events(session)]
    assert "WEBHOOK_UNRECOGNIZED" in types


def test_missing_event_id_header_falls_back_to_body_hash_dedup(session: Session) -> None:
    body = _payment_failed_body("pay_9")
    first = handle_webhook_event(session, body, {})
    second = handle_webhook_event(session, body, {})
    assert first["status"] == "recorded"
    assert second["status"] == "duplicate"


def test_subscription_halted_is_recorded_against_subscription_id(session: Session) -> None:
    body = json.dumps(
        {
            "event": "subscription.halted",
            "payload": {"subscription": {"entity": {"id": "sub_1"}}},
        }
    ).encode()
    result = handle_webhook_event(session, body, {EVENT_ID_HEADER: "evt_halt"})
    assert result["aggregate_id"] == "sub_1"
    assert any(
        e.event_type == "SUBSCRIPTION_HALTED" and e.aggregate_id == "sub_1"
        for e in list_events(session)
    )
