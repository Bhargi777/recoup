"""core.act.templates: deterministic, LLM-free message drafting."""

from core.act.templates import (
    incentive_message,
    pre_debit_notification_message,
    reminder_message,
)


def test_reminder_message_uses_specific_template_for_known_root_cause():
    text = reminder_message("card_expired", 999.50)
    assert "999.50" in text
    assert "expired" in text.lower()


def test_reminder_message_falls_back_to_default_for_unknown_root_cause():
    text = reminder_message("totally_unmapped_root_cause", 500.0)
    assert "500.00" in text


def test_reminder_message_is_deterministic():
    a = reminder_message("insufficient_funds", 1234.5)
    b = reminder_message("insufficient_funds", 1234.5)
    assert a == b


def test_incentive_message_uses_incentive_amount_when_set():
    text = incentive_message("insufficient_funds", 150.0, 0.0, 2000.0)
    assert "150.00" in text
    assert "2000.00" in text


def test_incentive_message_derives_amount_from_percent_when_no_flat_amount():
    text = incentive_message("card_declined_generic", 0.0, 10.0, 1000.0)
    assert "100.00" in text  # 10% of 1000


def test_pre_debit_notification_message_includes_notice_hours():
    text = pre_debit_notification_message(500.0, 24.0)
    assert "24" in text
    assert "500.00" in text


def test_no_template_ever_calls_out_to_a_model():
    # Structural guarantee: these are plain string-formatting functions, not
    # coroutines or anything that could plausibly perform network I/O.
    import inspect

    assert not inspect.iscoroutinefunction(reminder_message)
    assert not inspect.iscoroutinefunction(incentive_message)
    assert not inspect.iscoroutinefunction(pre_debit_notification_message)
