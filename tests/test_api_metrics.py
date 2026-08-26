import pytest
from fastapi.testclient import TestClient

from core.config import reset_settings_cache


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
