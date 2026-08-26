"""CLI smoke tests."""

from typer.testing import CliRunner

from recoup.cli import app

runner = CliRunner()


def test_version_command():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "recoup" in result.output


def test_check_config_reports_guardrails():
    result = runner.invoke(app, ["check-config"])
    assert result.exit_code == 0
    assert "configuration OK" in result.output
    assert "quiet hours (DND)" in result.output
    assert "holdout percent       : 15.0" in result.output


def test_check_config_never_prints_full_key():
    import os

    from core.config import reset_settings_cache

    os.environ["RAZORPAY_KEY_ID"] = "rzp_test_supersecretvalue123456"
    reset_settings_cache()
    try:
        result = runner.invoke(app, ["check-config"])
        assert result.exit_code == 0
        assert "supersecretvalue" not in result.output
        assert result.output.count("rzp_test_supersec") == 0  # never leaks
        assert "rzp_test_sup..." in result.output  # exactly the masked form
    finally:
        os.environ["RAZORPAY_KEY_ID"] = "rzp_test_dummy_key_id_for_ci"
        reset_settings_cache()


def test_serve_fails_fast_on_bad_key_before_binding_a_port(monkeypatch):
    from core.config import reset_settings_cache

    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_should_never_boot")
    reset_settings_cache()
    try:
        result = runner.invoke(app, ["serve"])
        assert result.exit_code != 0
        assert "rzp_test_" in str(result.exception) or "rzp_test_" in result.output
    finally:
        monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_dummy_key_id_for_ci")
        reset_settings_cache()


def test_verify_chain_on_empty_ledger_exits_zero(tmp_path, monkeypatch):
    from core.config import reset_settings_cache

    db_path = tmp_path / "empty.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    reset_settings_cache()
    try:
        result = runner.invoke(app, ["verify-chain"])
        assert result.exit_code == 0
        assert "empty" in result.output
    finally:
        reset_settings_cache()


def test_verify_chain_on_untampered_ledger_exits_zero(tmp_path, monkeypatch):
    from sqlmodel import Session

    from core.config import reset_settings_cache
    from core.ledger import append_event, get_engine, init_ledger_schema

    db_path = tmp_path / "clean.db"
    db_url = f"sqlite:///{db_path}"
    engine = get_engine(db_url)
    init_ledger_schema(engine)
    with Session(engine) as session:
        append_event(session, "pay_1", "INGESTED", {"amount": 100})
        append_event(session, "pay_1", "DIAGNOSED", {"root_cause": "insufficient_funds"})

    monkeypatch.setenv("DATABASE_URL", db_url)
    reset_settings_cache()
    try:
        result = runner.invoke(app, ["verify-chain"])
        assert result.exit_code == 0
        assert "chain OK: 2 events verified" in result.output
    finally:
        reset_settings_cache()


def test_verify_chain_on_tampered_ledger_exits_nonzero_with_location(tmp_path, monkeypatch):
    from sqlalchemy import text
    from sqlmodel import Session

    from core.config import reset_settings_cache
    from core.ledger import append_event, get_engine, init_ledger_schema

    db_path = tmp_path / "tampered.db"
    db_url = f"sqlite:///{db_path}"
    engine = get_engine(db_url)
    init_ledger_schema(engine)
    with Session(engine) as session:
        append_event(session, "pay_1", "INGESTED", {"amount": 100})
        append_event(session, "pay_1", "DIAGNOSED", {"root_cause": "insufficient_funds"})
        session.execute(
            text("UPDATE ledger_events SET payload_json = '{}' WHERE sequence_num = 1")
        )
        session.commit()

    monkeypatch.setenv("DATABASE_URL", db_url)
    reset_settings_cache()
    try:
        result = runner.invoke(app, ["verify-chain"])
        assert result.exit_code == 1
        assert "chain BROKEN at sequence 1" in result.output
    finally:
        reset_settings_cache()
