import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from core.config import reset_settings_cache
from core.ledger import get_engine, list_events


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "api_metrics.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()

    from core.ingest.webhook_app import app

    with TestClient(app) as c:
        yield c
    reset_settings_cache()


@pytest.mark.slow
def test_metrics_returns_real_diagnosis_and_labeled_simulated_uplift(client) -> None:
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    body = resp.json()

    diagnosis = body["diagnosis"]
    assert diagnosis["total"] == 200  # the committed held-out set size
    assert 0.0 <= diagnosis["macro_f1"] <= 1.0
    assert "confusion_matrix" in diagnosis
    assert "coverage" in diagnosis

    uplift = body["uplift"]
    assert uplift["simulated"] is True
    assert "qualifier" in uplift and "simulated" in uplift["qualifier"].lower()
    assert "treatment" in uplift and "control" in uplift

    batch_run = body["batch_run"]
    assert batch_run["total_records"] == 600
    assert batch_run["mode"] == "dry_run"

    exceptions = body["exceptions"]
    assert exceptions["total"] == len(exceptions["items"])
    for item in exceptions["items"]:
        assert item["kind"] in {"diagnosis_abstained", "exception_queue_enqueued"}
        assert item["reason"]


@pytest.mark.slow
def test_second_metrics_load_does_not_inflate_the_ledger(tmp_path, monkeypatch) -> None:
    """Regression guard: loading the Metrics page must be a read, not a write.
    A dashboard reload (or React StrictMode's double-fired effect) must not
    grow the audit ledger - the real UNIQUE constraint failed:
    ledger_events.sequence_num crash this test guards against was caused by
    exactly this: held-out diagnosis being re-persisted on every read."""
    db_path = tmp_path / "api_metrics_two_loads.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()

    from core.ingest.webhook_app import app

    with TestClient(app) as c:
        first = c.get("/api/metrics")
        assert first.status_code == 200
        second = c.get("/api/metrics")
        assert second.status_code == 200
    reset_settings_cache()

    engine = get_engine(f"sqlite:///{db_path}")
    with Session(engine) as s:
        events_after_first_and_second = len(list_events(s))

    # A third load must not add any further diagnosis-evaluation events either.
    with TestClient(app) as c:
        third = c.get("/api/metrics")
        assert third.status_code == 200
    reset_settings_cache()

    with Session(engine) as s:
        events_after_third = len(list_events(s))

    assert events_after_third == events_after_first_and_second
