import pytest
from fastapi.testclient import TestClient

from core.config import reset_settings_cache


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "api_ledger.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()

    from core.ingest.webhook_app import app

    with TestClient(app) as c:
        yield c, db_path
    reset_settings_cache()


def test_ledger_empty_verify_ok(client) -> None:
    c, _ = client
    resp = c.get("/api/ledger/verify")
    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "events_checked": 0,
        "first_bad_sequence": None,
        "errors": [],
    }


def test_ledger_pagination_and_verify_after_writes(client) -> None:
    c, db_path = client

    resp = c.post("/api/kill-switch", json={"action": "on", "reason": "test"})
    assert resp.status_code == 200
    resp = c.post("/api/kill-switch", json={"action": "off", "reason": "test"})
    assert resp.status_code == 200

    resp = c.get("/api/ledger", params={"limit": 1, "offset": 0})
    body = resp.json()
    assert body["total"] == 2
    assert len(body["events"]) == 1
    # Most recent first.
    assert body["events"][0]["event_type"] == "KILL_SWITCH_DEACTIVATED"

    resp = c.get("/api/ledger", params={"event_type": "KILL_SWITCH_ACTIVATED"})
    body = resp.json()
    assert body["total"] == 1
    assert body["events"][0]["payload"]["reason"] == "test"

    verify_resp = c.get("/api/ledger/verify")
    verify_body = verify_resp.json()
    assert verify_body["ok"] is True
    assert verify_body["events_checked"] == 2


def test_ledger_verify_detects_tamper(client) -> None:
    c, db_path = client
    c.post("/api/kill-switch", json={"action": "on", "reason": "test"})

    from sqlmodel import Session

    from core.ledger import get_engine

    engine = get_engine(f"sqlite:///{db_path}")
    with Session(engine) as session:
        from core.ledger.models import LedgerEvent

        event = session.exec(
            LedgerEvent.__table__.select()
        ).first()  # sanity: table has rows
        assert event is not None
        session.exec(
            LedgerEvent.__table__.update()
            .where(LedgerEvent.__table__.c.sequence_num == 0)
            .values(payload_json='{"reason": "tampered"}')
        )
        session.commit()

    resp = c.get("/api/ledger/verify")
    body = resp.json()
    assert body["ok"] is False
    assert body["first_bad_sequence"] == 0
