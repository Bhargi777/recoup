"""Boot guard tests: recoup must refuse to start without an rzp_test_ key."""

import pytest
from pydantic import ValidationError

from core.config import TEST_KEY_PREFIX, Settings
from core.config import TestModeViolationError as KeyRejected


def test_valid_test_mode_key_is_accepted():
    settings = Settings(razorpay_key_id="rzp_test_abc123", _env_file=None)
    assert settings.razorpay_key_id.startswith(TEST_KEY_PREFIX)


@pytest.mark.parametrize(
    "bad_key",
    [
        "",
        "rzp_live_abc123",
        "sk_test_whatever",
        "rzp_test",
        "RZP_TEST_uppercase",
    ],
)
def test_live_or_malformed_keys_hard_fail_at_boot(bad_key: str):
    with pytest.raises(KeyRejected):
        Settings(razorpay_key_id=bad_key, _env_file=None)


def test_default_guardrails_are_sane():
    settings = Settings(_env_file=None)
    assert settings.max_global_budget_inr > 0
    assert 0 < settings.default_holdout_percent < 100
    assert 0 <= settings.dnd_start_hour <= 23
    assert 0 <= settings.dnd_end_hour <= 23
    assert settings.split_seed == 42


def test_dnd_hours_out_of_range_fail():
    with pytest.raises(ValidationError):
        Settings(dnd_start_hour=24, _env_file=None)
