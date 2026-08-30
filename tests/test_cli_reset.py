"""CLI tests for `recoup reset` - the genuine clean-slate command."""

from typer.testing import CliRunner

from recoup.cli import app

runner = CliRunner()


def test_reset_yes_wipes_ledger_and_records_no_prompt(tmp_path, monkeypatch):
    from core.config import reset_settings_cache

    db_path = tmp_path / "reset.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()
    try:
        first = runner.invoke(app, ["run-batch"])
        assert first.exit_code == 0, first.output

        result = runner.invoke(app, ["reset", "--yes"])
        assert result.exit_code == 0, result.output
        assert "reset complete" in result.output

        from sqlmodel import Session

        from core.ledger import get_engine, list_events
        from core.ingest.synthetic import AtRiskRecord
        from sqlmodel import select

        engine = get_engine(f"sqlite:///{db_path}")
        with Session(engine) as session:
            assert list_events(session) == []
            assert session.exec(select(AtRiskRecord)).all() == []
    finally:
        reset_settings_cache()


def test_reset_without_yes_prompts_and_aborts_on_no(tmp_path, monkeypatch):
    from core.config import reset_settings_cache

    db_path = tmp_path / "reset2.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()
    try:
        first = runner.invoke(app, ["run-batch"])
        assert first.exit_code == 0, first.output

        result = runner.invoke(app, ["reset"], input="n\n")
        assert result.exit_code != 0

        from sqlmodel import Session

        from core.ledger import get_engine, list_events

        engine = get_engine(f"sqlite:///{db_path}")
        with Session(engine) as session:
            assert len(list_events(session)) > 0  # untouched - prompt was declined
    finally:
        reset_settings_cache()


def test_reset_then_run_batch_pass_one_populates_treatment_again(tmp_path, monkeypatch):
    """The end-to-end proof: an already-used database, reset, then pass one
    behaves exactly like a genuinely fresh database - the bug `recoup reset`
    exists to fix."""
    from core.config import reset_settings_cache

    db_path = tmp_path / "reset3.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()
    try:
        first_pass = runner.invoke(app, ["run-batch"])
        assert first_pass.exit_code == 0, first_pass.output

        second_pass_blocked = runner.invoke(app, ["run-batch"])
        blocked_line = next(
            line
            for line in second_pass_blocked.output.splitlines()
            if "blocked by gate" in line
        )
        assert int(blocked_line.split(":")[-1].strip()) > 0

        reset_result = runner.invoke(app, ["reset", "--yes"])
        assert reset_result.exit_code == 0, reset_result.output

        fresh_pass = runner.invoke(app, ["run-batch"])
        assert fresh_pass.exit_code == 0, fresh_pass.output
        treatment_line = next(
            line for line in fresh_pass.output.splitlines() if "treatment / control" in line
        )
        treatment_n = int(treatment_line.split(":", 1)[1].split("(")[0].strip().split("/")[0])
        assert treatment_n > 0
    finally:
        reset_settings_cache()
