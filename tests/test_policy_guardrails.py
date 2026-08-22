"""Each of the 10 money-action-gate checks: at least one ALLOW and one DENY,
including IST boundary cases for quiet hours and NPCI peak hours."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from core.config import Settings
from core.ledger import append_event, get_engine, init_ledger_schema
from core.policy import GateContext
from core.policy.events import ACTION_EXECUTION_FAILED, INCENTIVE_COMMITTED, MONEY_ACTION_INTENT
from core.policy.guardrails import (
    check_attempt_limits,
    check_cohort_incentive_ceiling,
    check_cooldown,
    check_global_budget,
    check_idempotency,
    check_kill_switch,
    check_ledger_writable,
    check_npci_peak_hour,
    check_quiet_hours,
    check_rbi_pre_debit_notice,
)
from core.policy.kill_switch import activate_kill_switch
from core.policy.loader import load_playbooks

IST = "Asia/Kolkata"


@pytest.fixture()
def session():
    engine = get_engine("sqlite:///:memory:")
    init_ledger_schema(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture()
def settings():
    return Settings(razorpay_key_id="rzp_test_dummy")


@pytest.fixture()
def playbooks():
    return load_playbooks()


def ist_utc(year, month, day, hour, minute=0):
    """Build a UTC datetime whose IST (UTC+5:30) wall-clock time is exactly
    (hour, minute). IST has no DST so the offset is fixed."""
    from zoneinfo import ZoneInfo

    local = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(IST))
    return local.astimezone(UTC)


def make_context(**overrides):
    defaults = dict(
        idempotency_key="idem-1",
        aggregate_id="pay_1",
        customer_id="cust_1",
        cohort="one_time_checkout_failure",
        root_cause="card_expired",
        action_type="reminder_message",
        proposed_action_at=ist_utc(2026, 8, 24, 12, 0),  # Monday noon IST
        now=ist_utc(2026, 8, 24, 12, 0),
    )
    defaults.update(overrides)
    return GateContext(**defaults)


# --- 1. Idempotency ----------------------------------------------------------


def test_idempotency_allows_first_use(session, playbooks, settings):
    ctx = make_context()
    result = check_idempotency(session, ctx, playbooks["card_expired"], settings)
    assert result.allowed


def test_idempotency_denies_reused_key(session, playbooks, settings):
    ctx = make_context()
    append_event(
        session, ctx.aggregate_id, MONEY_ACTION_INTENT, {"idempotency_key": ctx.idempotency_key}
    )
    result = check_idempotency(session, ctx, playbooks["card_expired"], settings)
    assert not result.allowed


def test_idempotency_allows_retry_after_real_execution_failure(session, playbooks, settings):
    """Phase 7 chaos gap fix: if the intent was approved but the real
    executor call failed (ACTION_EXECUTION_FAILED is the last event for this
    idempotency_key), the key must be retryable on a subsequent run - a
    gateway outage must not permanently strand a record. See
    core.policy.events.ACTION_EXECUTION_FAILED's module-level docstring."""
    ctx = make_context()
    append_event(
        session, ctx.aggregate_id, MONEY_ACTION_INTENT, {"idempotency_key": ctx.idempotency_key}
    )
    append_event(
        session,
        ctx.aggregate_id,
        ACTION_EXECUTION_FAILED,
        {"idempotency_key": ctx.idempotency_key, "error": "gateway down"},
    )
    result = check_idempotency(session, ctx, playbooks["card_expired"], settings)
    assert result.allowed


def test_idempotency_still_denies_once_a_retry_succeeds(session, playbooks, settings):
    """A failed-then-retried key must go back to permanently denied once a
    later attempt actually succeeds (the last event is a real executor
    success, not ACTION_EXECUTION_FAILED) - retries are not a loophole for
    re-approving an already-completed action."""
    ctx = make_context()
    append_event(
        session, ctx.aggregate_id, MONEY_ACTION_INTENT, {"idempotency_key": ctx.idempotency_key}
    )
    append_event(
        session,
        ctx.aggregate_id,
        ACTION_EXECUTION_FAILED,
        {"idempotency_key": ctx.idempotency_key, "error": "gateway down"},
    )
    append_event(
        session,
        ctx.aggregate_id,
        "ACTION_MESSAGE_DRAFTED",
        {"idempotency_key": ctx.idempotency_key, "action_type": "reminder_message"},
    )
    result = check_idempotency(session, ctx, playbooks["card_expired"], settings)
    assert not result.allowed


# --- 2. Global budget meter ---------------------------------------------------


def test_global_budget_allows_when_under_cap(session, playbooks, settings):
    ctx = make_context(root_cause="insufficient_funds", incentive_amount_inr=100)
    result = check_global_budget(session, ctx, playbooks["insufficient_funds"], settings)
    assert result.allowed


def test_global_budget_denies_when_over_cap(session, playbooks, settings):
    tight_settings = settings.model_copy(update={"max_global_budget_inr": 50})
    ctx = make_context(root_cause="insufficient_funds", incentive_amount_inr=100)
    result = check_global_budget(session, ctx, playbooks["insufficient_funds"], tight_settings)
    assert not result.allowed


def test_global_budget_accounts_for_prior_committed_spend(session, playbooks, settings):
    tight_settings = settings.model_copy(update={"max_global_budget_inr": 150})
    append_event(
        session, "pay_other", INCENTIVE_COMMITTED, {"cohort": "x", "amount_inr": 100}
    )
    ctx = make_context(root_cause="insufficient_funds", incentive_amount_inr=100)
    result = check_global_budget(session, ctx, playbooks["insufficient_funds"], tight_settings)
    assert not result.allowed  # 100 already spent + 100 proposed > 150 cap


# --- 3. Cohort incentive ceiling ----------------------------------------------


def test_cohort_ceiling_allows_within_cap(session, playbooks, settings):
    ctx = make_context(root_cause="insufficient_funds", incentive_amount_inr=100)
    result = check_cohort_incentive_ceiling(session, ctx, playbooks["insufficient_funds"], settings)
    assert result.allowed


def test_cohort_ceiling_denies_over_cap(session, playbooks, settings):
    ctx = make_context(root_cause="insufficient_funds", incentive_amount_inr=9999)
    result = check_cohort_incentive_ceiling(session, ctx, playbooks["insufficient_funds"], settings)
    assert not result.allowed


def test_invoice_ceiling_denies_any_nonzero_incentive(session, playbooks, settings):
    ctx = make_context(
        root_cause="invoice_overdue",
        cohort="overdue_b2b_invoice",
        incentive_amount_inr=1,
    )
    result = check_cohort_incentive_ceiling(session, ctx, playbooks["invoice_overdue"], settings)
    assert not result.allowed


# --- 4. Customer attempt limits -----------------------------------------------


def test_attempt_limits_allows_under_max(session, playbooks, settings):
    ctx = make_context()
    result = check_attempt_limits(session, ctx, playbooks["card_expired"], settings)
    assert result.allowed


def test_attempt_limits_denies_at_playbook_max(session, playbooks, settings):
    ctx = make_context()
    playbook = playbooks["card_expired"]  # max_attempts: 3
    for i in range(playbook.max_attempts):
        append_event(
            session,
            ctx.aggregate_id,
            MONEY_ACTION_INTENT,
            {"action_type": "reminder_message", "idempotency_key": f"prior-{i}"},
        )
    result = check_attempt_limits(session, ctx, playbook, settings)
    assert not result.allowed


def test_attempt_limits_uses_npci_limit_for_mandate_debits(session, playbooks, settings):
    ctx = make_context(root_cause="insufficient_funds", is_emandate_debit=True)
    playbook = playbooks["insufficient_funds"]  # playbook max_attempts is 4, same as NPCI here
    for i in range(settings.npci_upi_autopay_max_attempts):
        append_event(
            session,
            ctx.aggregate_id,
            MONEY_ACTION_INTENT,
            {"action_type": "mandate_retry", "idempotency_key": f"prior-{i}"},
        )
    result = check_attempt_limits(session, ctx, playbook, settings)
    assert not result.allowed
    assert "NPCI" in result.reason


# --- 5. Cooldown interval ------------------------------------------------------


def test_cooldown_allows_with_no_prior_communication(session, playbooks, settings):
    ctx = make_context()
    result = check_cooldown(session, ctx, playbooks["card_expired"], settings)
    assert result.allowed


def test_cooldown_denies_within_window(session, playbooks, settings):
    append_event(
        session,
        "pay_1",
        MONEY_ACTION_INTENT,
        {"action_type": "reminder_message", "idempotency_key": "prior"},
    )
    # append_event stamps the real wall-clock UTC time; evaluate "now" as
    # right after that, well within the 6h default cooldown.
    ctx = make_context(now=datetime.now(UTC))
    result = check_cooldown(session, ctx, playbooks["card_expired"], settings)
    assert not result.allowed


def test_cooldown_allows_after_window_elapses(session, playbooks, settings):
    append_event(
        session,
        "pay_1",
        MONEY_ACTION_INTENT,
        {"action_type": "reminder_message", "idempotency_key": "prior"},
    )
    ctx = make_context(now=datetime.now(UTC) + timedelta(hours=7))
    result = check_cooldown(session, ctx, playbooks["card_expired"], settings)
    assert result.allowed


# --- 6. Quiet hours / DND (09:00-21:00 IST allowed) ---------------------------


def test_quiet_hours_allows_midday(session, playbooks, settings):
    ctx = make_context(proposed_action_at=ist_utc(2026, 8, 24, 14, 0))
    result = check_quiet_hours(session, ctx, playbooks["card_expired"], settings)
    assert result.allowed


def test_quiet_hours_denies_at_exactly_21_00(session, playbooks, settings):
    ctx = make_context(proposed_action_at=ist_utc(2026, 8, 24, 21, 0))
    result = check_quiet_hours(session, ctx, playbooks["card_expired"], settings)
    assert not result.allowed


def test_quiet_hours_denies_at_08_59(session, playbooks, settings):
    ctx = make_context(proposed_action_at=ist_utc(2026, 8, 24, 8, 59))
    result = check_quiet_hours(session, ctx, playbooks["card_expired"], settings)
    assert not result.allowed


def test_quiet_hours_allows_at_exactly_09_00(session, playbooks, settings):
    ctx = make_context(proposed_action_at=ist_utc(2026, 8, 24, 9, 0))
    result = check_quiet_hours(session, ctx, playbooks["card_expired"], settings)
    assert result.allowed


def test_quiet_hours_denies_late_night(session, playbooks, settings):
    ctx = make_context(proposed_action_at=ist_utc(2026, 8, 24, 23, 30))
    result = check_quiet_hours(session, ctx, playbooks["card_expired"], settings)
    assert not result.allowed


# --- 7. RBI e-mandate pre-debit notification (>=24h) --------------------------


def test_rbi_notice_not_applicable_when_not_a_mandate_debit(session, playbooks, settings):
    ctx = make_context(is_emandate_debit=False)
    result = check_rbi_pre_debit_notice(session, ctx, playbooks["card_expired"], settings)
    assert result.allowed


def test_rbi_notice_denies_missing_notification(session, playbooks, settings):
    ctx = make_context(is_emandate_debit=True, pre_debit_notification_sent_at=None)
    result = check_rbi_pre_debit_notice(session, ctx, playbooks["card_expired"], settings)
    assert not result.allowed


def test_rbi_notice_denies_under_24h(session, playbooks, settings):
    debit_at = ist_utc(2026, 8, 24, 12, 0)
    ctx = make_context(
        is_emandate_debit=True,
        proposed_action_at=debit_at,
        pre_debit_notification_sent_at=debit_at - timedelta(hours=23, minutes=59),
    )
    result = check_rbi_pre_debit_notice(session, ctx, playbooks["card_expired"], settings)
    assert not result.allowed


def test_rbi_notice_allows_at_exactly_24h(session, playbooks, settings):
    debit_at = ist_utc(2026, 8, 24, 12, 0)
    ctx = make_context(
        is_emandate_debit=True,
        proposed_action_at=debit_at,
        pre_debit_notification_sent_at=debit_at - timedelta(hours=24),
    )
    result = check_rbi_pre_debit_notice(session, ctx, playbooks["card_expired"], settings)
    assert result.allowed


# --- 8. NPCI peak-hour restriction (10:00-13:00, 17:00-21:30 IST) ------------


def test_npci_peak_hour_not_applicable_when_not_upi_autopay(session, playbooks, settings):
    ctx = make_context(
        is_upi_autopay_execution=False, proposed_action_at=ist_utc(2026, 8, 24, 11, 0)
    )
    result = check_npci_peak_hour(session, ctx, playbooks["card_expired"], settings)
    assert result.allowed


def test_npci_peak_hour_denies_at_exactly_10_00(session, playbooks, settings):
    ctx = make_context(
        is_upi_autopay_execution=True, proposed_action_at=ist_utc(2026, 8, 24, 10, 0)
    )
    result = check_npci_peak_hour(session, ctx, playbooks["card_expired"], settings)
    assert not result.allowed


def test_npci_peak_hour_allows_at_exactly_13_00(session, playbooks, settings):
    ctx = make_context(
        is_upi_autopay_execution=True, proposed_action_at=ist_utc(2026, 8, 24, 13, 0)
    )
    result = check_npci_peak_hour(session, ctx, playbooks["card_expired"], settings)
    assert result.allowed


def test_npci_peak_hour_denies_at_17_00(session, playbooks, settings):
    ctx = make_context(
        is_upi_autopay_execution=True, proposed_action_at=ist_utc(2026, 8, 24, 17, 0)
    )
    result = check_npci_peak_hour(session, ctx, playbooks["card_expired"], settings)
    assert not result.allowed


def test_npci_peak_hour_allows_at_exactly_21_30(session, playbooks, settings):
    ctx = make_context(
        is_upi_autopay_execution=True, proposed_action_at=ist_utc(2026, 8, 24, 21, 30)
    )
    result = check_npci_peak_hour(session, ctx, playbooks["card_expired"], settings)
    assert result.allowed


def test_npci_peak_hour_allows_early_morning(session, playbooks, settings):
    ctx = make_context(
        is_upi_autopay_execution=True, proposed_action_at=ist_utc(2026, 8, 24, 9, 0)
    )
    result = check_npci_peak_hour(session, ctx, playbooks["card_expired"], settings)
    assert result.allowed


# --- 9. Kill switch -------------------------------------------------------------


def test_kill_switch_allows_when_inactive(session, playbooks, settings):
    ctx = make_context()
    result = check_kill_switch(session, ctx, playbooks["card_expired"], settings)
    assert result.allowed


def test_kill_switch_denies_when_active(session, playbooks, settings):
    activate_kill_switch(session, "incident")
    ctx = make_context()
    result = check_kill_switch(session, ctx, playbooks["card_expired"], settings)
    assert not result.allowed


# --- 10. Pre-action ledger event (readiness) ------------------------------------


def test_ledger_writable_allows_on_healthy_session(session, playbooks, settings):
    ctx = make_context()
    result = check_ledger_writable(session, ctx, playbooks["card_expired"], settings)
    assert result.allowed
