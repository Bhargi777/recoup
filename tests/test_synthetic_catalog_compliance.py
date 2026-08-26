"""No-fabrication guard: every generated error_code/error_reason must come from the
verified catalog in .claude/skills/razorpay-testmode/SKILL.md SS5/SS6, and nothing from
the banned/unverified SS7 list may ever appear.

The allowlists below are a hardcoded mirror of the SKILL.md tables, not an import from
the generator module - so this test fails loudly if the generator or the skill file
drift apart, instead of trivially passing because both sides changed together.
"""

from core.ingest.synthetic import generate_records

VERIFIED_CARD_REASONS = {
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
}

VERIFIED_UPI_REASONS = {
    "insufficient_funds",
    "payment_declined",
    "payment_cancelled",
    "payment_timed_out",
    "payment_collect_request_expired",
    "invalid_vpa",
    "vpa_resolution_failed",
    "credit_failed",
    "bank_technical_error",
    "gateway_technical_error",
}

VERIFIED_REASONS = VERIFIED_CARD_REASONS | VERIFIED_UPI_REASONS

# SKILL.md SS7 - explicitly banned, must never be produced.
BANNED_REASONS = {
    "expired_card",
    "mandate_inactive",
    "amount_limit_exceeded",
    "bank_account_invalid",
    "network_failure",
}

VERIFIED_TOP_LEVEL_CODES = {"BAD_REQUEST_ERROR", "GATEWAY_ERROR"}


def test_no_error_reason_outside_verified_catalog():
    records = generate_records(seed=42)
    seen_reasons = {r["error_reason"] for r in records if r["error_reason"] is not None}
    assert seen_reasons, "sanity: generator should produce at least one error_reason"
    assert seen_reasons <= VERIFIED_REASONS


def test_no_banned_reason_ever_appears():
    records = generate_records(seed=42)
    seen_reasons = {r["error_reason"] for r in records if r["error_reason"] is not None}
    assert seen_reasons.isdisjoint(BANNED_REASONS)


def test_error_code_is_always_a_verified_top_level_code_or_null():
    records = generate_records(seed=42)
    for r in records:
        assert r["error_code"] in VERIFIED_TOP_LEVEL_CODES or r["error_code"] is None


def test_card_reasons_only_appear_on_card_payment_method():
    records = generate_records(seed=42)
    card_only_reasons = VERIFIED_CARD_REASONS - VERIFIED_UPI_REASONS
    for r in records:
        if r["error_reason"] in card_only_reasons:
            assert r["payment_method"] == "card"


def test_upi_reasons_only_appear_on_upi_payment_method():
    records = generate_records(seed=42)
    upi_only_reasons = VERIFIED_UPI_REASONS - VERIFIED_CARD_REASONS
    for r in records:
        if r["error_reason"] in upi_only_reasons:
            assert r["payment_method"] == "upi"
