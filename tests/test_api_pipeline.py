import pytest
from fastapi.testclient import TestClient

from core.config import reset_settings_cache


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "api_pipeline.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()

    from core.ingest.webhook_app import app

    with TestClient(app) as c:
        yield c
    reset_settings_cache()


def test_pipeline_empty_before_synthetic_data_generated(client) -> None:
    resp = client.get("/api/pipeline")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert len(body["cohorts"]) == 4


def test_pipeline_groups_real_records_by_cohort(client) -> None:
    from sqlmodel import Session

    from core.config import get_settings
    from core.ingest.synthetic import init_synthetic_schema, run_generation
    from core.ledger import get_engine, init_ledger_schema

    settings = get_settings()
    engine = get_engine(settings.database_url)
    init_ledger_schema(engine)
    init_synthetic_schema(engine)
    with Session(engine) as session:
        result = run_generation(session, seed=settings.split_seed, force=False)
    assert result.inserted == 600

    resp = client.get("/api/pipeline")
    body = resp.json()
    assert body["total"] == 600
    counts = {c["cohort"]: c["count"] for c in body["cohorts"]}
    assert counts["one_time_checkout_failure"] == 150
    assert counts["checkout_abandonment"] == 150
    assert counts["subscription_mandate_failure"] == 150
    assert counts["overdue_b2b_invoice"] == 150

    one_record = body["cohorts"][0]["records"][0]
    assert one_record["source"] == "synthetic"
    assert "amount_inr" in one_record
    assert "held_out" in one_record
