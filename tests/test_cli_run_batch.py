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


def test_run_batch_pass_one_on_a_clean_slate_populates_the_treatment_arm(tmp_path, monkeypatch):
    """Regression guard for a real bug: synthetic record IDs are deterministic
    (same seed every generation), so a database that has ever run a batch
    permanently pre-blocks every treatment record via check_idempotency, even
    after `generate-synthetic-data --force` (records-only - see
    core/ingest/synthetic.py's run_generation docstring). On a genuinely
    fresh database (never before used, exactly what a brand-new clone or a
    real `recoup reset` produces) pass one must show a populated, computable
    treatment arm - not 0 records blocked by "idempotency_verification"
    before anything was ever actually approved."""
    from core.config import reset_settings_cache

    db_path = tmp_path / "clean_slate.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()
    try:
        result = runner.invoke(app, ["run-batch"])
        assert result.exit_code == 0, result.output

        treatment_line = next(
            line for line in result.output.splitlines() if "treatment / control" in line
        )
        # "  treatment / control    : 516 / 84 (actual control % = 14.00)"
        counts = treatment_line.split(":", 1)[1].split("(")[0].strip()
        treatment_n = int(counts.split("/")[0].strip())
        assert treatment_n > 0, (
            "treatment arm is empty on a clean-slate first pass - "
            f"full output:\n{result.output}"
        )

        blocked_line = next(
            line for line in result.output.splitlines() if "blocked by gate" in line
        )
        assert blocked_line.strip().endswith(": 0")

        assert "uplift not computable" not in result.output.lower()
    finally:
        reset_settings_cache()
