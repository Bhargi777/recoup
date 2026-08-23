from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from core.config import reset_settings_cache


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "api_decisions.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()

    from core.ingest.webhook_app import app

    with TestClient(app) as c:
        yield c, db_path
    reset_settings_cache()


def _seed_one_allow_and_one_block(db_path) -> None:
    from sqlmodel import Session

    from core.config import get_settings
    from core.ledger import get_engine, init_ledger_schema
    from core.policy.context import GateContext
    from core.policy.gate import evaluate_gate

    settings = get_settings()
    engine = get_engine(f"sqlite:///{db_path}")
    init_ledger_schema(engine)

    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)  # noon UTC -> daytime IST, outside DND
    with Session(engine) as session:
        allow_ctx = GateContext(
            idempotency_key="key_allow_1",
            aggregate_id="agg_allow_1",
            customer_id="cust_1",
            cohort="one_time_checkout_failure",
            root_cause="card_expired",
            action_type="reminder_message",
            proposed_action_at=now,
            now=now,
        )
        evaluate_gate(session, allow_ctx, settings=settings)

        # 21:00 UTC ~ 02:30 IST next day -> inside the 21:00-09:00 DND window,
        # so this one is guaranteed BLOCKED by quiet_hours_dnd.
        blocked_time = datetime(2026, 6, 1, 21, 0, tzinfo=UTC)
        block_ctx = GateContext(
            idempotency_key="key_block_1",
            aggregate_id="agg_block_1",
            customer_id="cust_2",
            cohort="one_time_checkout_failure",
            root_cause="card_expired",
            action_type="reminder_message",
            proposed_action_at=blocked_time,
            now=blocked_time,
        )
        evaluate_gate(session, block_ctx, settings=settings)


def test_decisions_lists_allow_and_block_with_plain_english_why(client) -> None:
    c, db_path = client
    _seed_one_allow_and_one_block(db_path)

    resp = c.get("/api/decisions")
    assert resp.status_code == 200
    body = resp.json()
    assert body["returned"] == 2

    statuses = {d["idempotency_key"]: d["status"] for d in body["decisions"]}
    assert statuses["key_allow_1"] == "ALLOW"
    assert statuses["key_block_1"] == "BLOCKED"

    why_by_key = {d["idempotency_key"]: d["why"] for d in body["decisions"]}
    assert "Allowed" in why_by_key["key_allow_1"]
    assert "Blocked" in why_by_key["key_block_1"]


def test_guardrails_lists_blocked_checks_not_allows(client) -> None:
    c, db_path = client
    _seed_one_allow_and_one_block(db_path)

    resp = c.get("/api/guardrails")
    assert resp.status_code == 200
    body = resp.json()

    assert body["distinct_blocked_actions"] == 1
    assert all(b["aggregate_id"] == "agg_block_1" for b in body["blocks"])
    assert "quiet_hours_dnd" in body["reasons_by_check"]
