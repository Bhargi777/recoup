"""CLI smoke tests for `recoup kill-switch on|off|status`."""

from typer.testing import CliRunner

from recoup.cli import app

runner = CliRunner()


def test_status_on_fresh_db_is_inactive(tmp_path, monkeypatch):
    from core.config import reset_settings_cache

    db_path = tmp_path / "fresh.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()
    try:
        result = runner.invoke(app, ["kill-switch", "status"])
        assert result.exit_code == 0
        assert "INACTIVE" in result.output
    finally:
        reset_settings_cache()


def test_on_then_status_reports_active(tmp_path, monkeypatch):
    from core.config import reset_settings_cache

    db_path = tmp_path / "toggle.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()
    try:
        on_result = runner.invoke(app, ["kill-switch", "on", "--reason", "test"])
        assert on_result.exit_code == 0
        assert "ACTIVATED" in on_result.output

        status_result = runner.invoke(app, ["kill-switch", "status"])
        assert status_result.exit_code == 0
        assert "currently ACTIVE" in status_result.output
    finally:
        reset_settings_cache()


def test_on_then_off_reports_inactive_again(tmp_path, monkeypatch):
    from core.config import reset_settings_cache

    db_path = tmp_path / "toggle2.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()
    try:
        runner.invoke(app, ["kill-switch", "on"])
        off_result = runner.invoke(app, ["kill-switch", "off", "--reason", "resolved"])
        assert off_result.exit_code == 0
        assert "DEACTIVATED" in off_result.output

        status_result = runner.invoke(app, ["kill-switch", "status"])
        assert "currently INACTIVE" in status_result.output
    finally:
        reset_settings_cache()


def test_unknown_action_exits_nonzero(tmp_path, monkeypatch):
    from core.config import reset_settings_cache

    db_path = tmp_path / "bad_action.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()
    try:
        result = runner.invoke(app, ["kill-switch", "flibbertigibbet"])
        assert result.exit_code == 1
        assert "unknown action" in result.output
    finally:
        reset_settings_cache()
