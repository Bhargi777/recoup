"""Deterministic mapper tests (core/diagnose/mapper.py)."""

from core.diagnose.mapper import (
    BANNED_ERROR_REASONS,
    ERROR_REASON_TO_ROOT_CAUSE,
    INVOICE_ROOT_CAUSE,
    deterministic_diagnose,
    map_cohort,
    map_error_reason,
)
from core.ingest.synthetic import COHORT_INVOICE, COHORT_ONE_TIME

# Transcribed directly from .claude/skills/razorpay-testmode/SKILL.md SS5 (cards)
# and SS6 (UPI) - every verified error.reason must map to a taxonomy label.
VERIFIED_REASONS = (
    "card_expired",
    "incorrect_cvv",
    "card_not_enrolled",
    "card_disabled_for_online_payments",
    "debit_instrument_inactive",
    "debit_instrument_blocked",
    "insufficient_funds",
    "transaction_limit_exceeded",
    "authentication_failed",
    "invalid_otp",
    "payment_cancelled",
    "payment_timed_out",
    "payment_risk_check_failed",
    "card_declined",
    "payment_failed",
    "bank_technical_error",
    "gateway_technical_error",
    "payment_declined",
    "payment_collect_request_expired",
    "invalid_vpa",
    "vpa_resolution_failed",
    "credit_failed",
)


def test_every_verified_reason_maps_to_a_root_cause():
    for reason in VERIFIED_REASONS:
        assert map_error_reason(reason) is not None, f"{reason} did not map"
        assert map_error_reason(reason) == ERROR_REASON_TO_ROOT_CAUSE[reason]


def test_specific_verified_mappings_match_skill_catalog():
    assert map_error_reason("card_expired") == "card_expired"
    assert map_error_reason("insufficient_funds") == "insufficient_funds"
    assert map_error_reason("authentication_failed") == "authentication_failed"
    assert map_error_reason("payment_cancelled") == "abandonment"
    assert map_error_reason("payment_timed_out") == "abandonment"
    assert map_error_reason("payment_collect_request_expired") == "abandonment"
    assert map_error_reason("payment_risk_check_failed") == "risk_blocked"
    assert map_error_reason("bank_technical_error") == "bank_technical_error"
    assert map_error_reason("gateway_technical_error") == "gateway_technical_error"
    assert map_error_reason("invalid_vpa") == "invalid_vpa"
    assert map_error_reason("vpa_resolution_failed") == "vpa_resolution_failed"
    assert map_error_reason("credit_failed") == "credit_failed"


def test_unknown_and_missing_error_reason_returns_none():
    assert map_error_reason(None) is None
    assert map_error_reason("") is None
    assert map_error_reason("totally_unmapped_reason") is None


def test_banned_reasons_are_never_mapper_keys():
    """SS7 of the SKILL.md catalog: these codes were never verified in
    official docs and must never appear as mapper keys."""
    assert set(ERROR_REASON_TO_ROOT_CAUSE) & BANNED_ERROR_REASONS == set()
    for banned in BANNED_ERROR_REASONS:
        assert map_error_reason(banned) is None


def test_overdue_b2b_invoice_cohort_resolves_via_cohort_rule():
    """No gateway error exists for this cohort - it must resolve through its
    own deterministic branch, not fall through to ABSTAIN."""
    assert map_cohort(COHORT_INVOICE) == INVOICE_ROOT_CAUSE
    assert deterministic_diagnose(COHORT_INVOICE, None, None) == INVOICE_ROOT_CAUSE


def test_cohort_rule_does_not_apply_to_other_cohorts():
    assert map_cohort(COHORT_ONE_TIME) is None
    assert map_cohort(None) is None


def test_deterministic_diagnose_prefers_cohort_rule_then_error_reason():
    assert deterministic_diagnose(COHORT_INVOICE, "BAD_REQUEST_ERROR", "card_expired") == (
        INVOICE_ROOT_CAUSE
    )
    assert (
        deterministic_diagnose(COHORT_ONE_TIME, "BAD_REQUEST_ERROR", "card_expired")
        == "card_expired"
    )
    assert deterministic_diagnose(COHORT_ONE_TIME, "BAD_REQUEST_ERROR", None) is None
