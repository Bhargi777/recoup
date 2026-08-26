"""CLI smoke tests for `recoup run-batch`."""

from typer.testing import CliRunner

from recoup.cli import app

runner = CliRunner()


def test_run_batch_dry_run_default_reports_summary(tmp_path, monkeypatch):
    from core.config import reset_settings_cache

    db_path = tmp_path / "batch.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()
    try:
        result = runner.invoke(app, ["run-batch"])
        assert result.exit_code == 0, result.output
        assert "run-batch (dry_run) complete" in result.output
        assert "records processed" in result.output
        assert "treatment / control" in result.output
        assert "blocked by gate" in result.output
        assert "SIMULATED" in result.output
        assert "NOT real observed Razorpay payments" in result.output
    finally:
        reset_settings_cache()


def test_run_batch_never_prints_uplift_without_simulated_qualifier(tmp_path, monkeypatch):
    from core.config import reset_settings_cache

    db_path = tmp_path / "batch2.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()
    try:
        result = runner.invoke(app, ["run-batch"])
        assert result.exit_code == 0, result.output
        for line in result.output.splitlines():
            if "uplift" in line.lower() and "+" in line:
                assert "SIMULATED" in line
    finally:
        reset_settings_cache()
