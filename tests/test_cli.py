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


def test_verify_chain_not_implemented_yet_exits_nonzero():
    result = runner.invoke(app, ["verify-chain"])
    assert result.exit_code == 2
