import hashlib
import hmac
import json
import os

import pytest
from fastapi.testclient import TestClient

from core.config import reset_settings_cache
from core.ingest.webhooks import EVENT_ID_HEADER, SIGNATURE_HEADER
from core.ledger import get_engine, list_events


def _sign(body: bytes) -> str:
    # Read live: RAZORPAY_WEBHOOK_SECRET may be set by conftest's default or
    # overridden by the CI workflow env - either way it must match whatever
    # the running app actually validates against.
    secret = os.environ["RAZORPAY_WEBHOOK_SECRET"]
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "webhook_app.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()

    from core.ingest.webhook_app import app

    with TestClient(app) as c:
        yield c, db_path
    reset_settings_cache()


def test_healthz(client) -> None:
    c, _ = client
    resp = c.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_valid_signature_is_accepted_and_recorded(client) -> None:
    c, db_path = client
    body = json.dumps(
        {
            "event": "payment.failed",
            "payload": {"payment": {"entity": {"id": "pay_app_1"}}},
        }
    ).encode()

    resp = c.post(
        "/webhooks/razorpay",
        content=body,
        headers={SIGNATURE_HEADER: _sign(body), EVENT_ID_HEADER: "evt_app_1"},
    )
    assert resp.status_code == 200

    from sqlmodel import Session

    engine = get_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        types = [e.event_type for e in list_events(session)]
    assert "PAYMENT_FAILED" in types


def test_invalid_signature_is_rejected(client) -> None:
    c, _ = client
    body = b'{"event":"payment.failed","payload":{}}'
    resp = c.post(
        "/webhooks/razorpay",
        content=body,
        headers={SIGNATURE_HEADER: "not-the-real-signature", EVENT_ID_HEADER: "evt_bad"},
    )
    assert resp.status_code == 400


def test_duplicate_delivery_returns_200_and_does_not_double_record(client) -> None:
    c, db_path = client
    body = json.dumps(
        {
            "event": "payment_link.paid",
            "payload": {"payment_link": {"entity": {"id": "plink_app_1"}}},
        }
    ).encode()
    headers = {SIGNATURE_HEADER: _sign(body), EVENT_ID_HEADER: "evt_app_dup"}

    first = c.post("/webhooks/razorpay", content=body, headers=headers)
    second = c.post("/webhooks/razorpay", content=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200

    from sqlmodel import Session

    engine = get_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        paid_events = [e for e in list_events(session) if e.event_type == "PAYMENT_LINK_PAID"]
    assert len(paid_events) == 1
