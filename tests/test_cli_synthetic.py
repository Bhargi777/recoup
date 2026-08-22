"""CLI smoke tests for `recoup generate-synthetic-data`."""

from typer.testing import CliRunner

from recoup.cli import app

runner = CliRunner()


def test_generate_synthetic_data_reports_counts(tmp_path, monkeypatch):
    from core.config import reset_settings_cache

    db_path = tmp_path / "synth.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()
    try:
        result = runner.invoke(app, ["generate-synthetic-data"])
        assert result.exit_code == 0
        assert "generated 600 synthetic records" in result.output
        assert "held_out" in result.output
        for cohort in (
            "one_time_checkout_failure",
            "checkout_abandonment",
            "subscription_mandate_failure",
            "overdue_b2b_invoice",
        ):
            assert cohort in result.output
    finally:
        reset_settings_cache()


def test_generate_synthetic_data_second_run_skips_without_force(tmp_path, monkeypatch):
    from core.config import reset_settings_cache

    db_path = tmp_path / "synth.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()
    try:
        first = runner.invoke(app, ["generate-synthetic-data"])
        second = runner.invoke(app, ["generate-synthetic-data"])
        assert first.exit_code == 0
        assert second.exit_code == 0
        assert "skipped" in second.output
    finally:
        reset_settings_cache()


def test_generate_synthetic_data_force_regenerates_without_duplicating(tmp_path, monkeypatch):
    from sqlmodel import Session, select

    from core.config import reset_settings_cache
    from core.ingest.synthetic import AtRiskRecord
    from core.ledger import get_engine

    db_path = tmp_path / "synth.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    reset_settings_cache()
    try:
        runner.invoke(app, ["generate-synthetic-data"])
        result = runner.invoke(app, ["generate-synthetic-data", "--force"])
        assert result.exit_code == 0
        assert "generated 600 synthetic records" in result.output

        engine = get_engine(db_url)
        with Session(engine) as session:
            rows = session.exec(select(AtRiskRecord)).all()
        assert len(rows) == 600
    finally:
        reset_settings_cache()
