"""CLI smoke test for `recoup eval-diagnosis`."""

from typer.testing import CliRunner

from recoup.cli import app

runner = CliRunner()


def test_eval_diagnosis_reports_real_metrics(tmp_path, monkeypatch):
    from core.config import reset_settings_cache

    db_path = tmp_path / "eval.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()
    try:
        result = runner.invoke(app, ["eval-diagnosis"])
        assert result.exit_code == 0
        assert "held-out records evaluated: 200" in result.output
        assert "macro precision" in result.output
        assert "macro recall" in result.output
        assert "macro f1" in result.output
        assert "abstain rate" in result.output
        assert "confusion matrix" in result.output
        assert "coverage" in result.output
    finally:
        reset_settings_cache()


def test_eval_diagnosis_is_self_contained_on_empty_db(tmp_path, monkeypatch):
    """Runs against a completely empty database - generates the synthetic
    dataset itself rather than requiring a prior `generate-synthetic-data`
    invocation."""
    from core.config import reset_settings_cache

    db_path = tmp_path / "eval_fresh.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()
    try:
        assert not db_path.exists()
        result = runner.invoke(app, ["eval-diagnosis"])
        assert result.exit_code == 0
        assert db_path.exists()
    finally:
        reset_settings_cache()
