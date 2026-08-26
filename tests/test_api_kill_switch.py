import pytest
from fastapi.testclient import TestClient

from core.config import reset_settings_cache


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "api_kill_switch.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()

    from core.ingest.webhook_app import app

    with TestClient(app) as c:
        yield c
    reset_settings_cache()


def test_kill_switch_defaults_inactive(client) -> None:
    resp = client.get("/api/kill-switch")
    assert resp.status_code == 200
    assert resp.json() == {"active": False}


def test_kill_switch_round_trip(client) -> None:
    resp = client.post("/api/kill-switch", json={"action": "on", "reason": "dashboard demo"})
    assert resp.status_code == 200
    assert resp.json() == {"active": True}

    assert client.get("/api/kill-switch").json() == {"active": True}

    resp = client.post("/api/kill-switch", json={"action": "off"})
    assert resp.status_code == 200
    assert resp.json() == {"active": False}

    assert client.get("/api/kill-switch").json() == {"active": False}


def test_kill_switch_rejects_unknown_action(client) -> None:
    resp = client.post("/api/kill-switch", json={"action": "sideways"})
    assert resp.status_code == 400
