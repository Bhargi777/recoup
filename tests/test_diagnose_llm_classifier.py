"""LLM fallback classifier tests: confidence gate + honest-unavailable path.

None of these tests make a network call or require ANTHROPIC_API_KEY -
`apply_confidence_gate` is exercised directly (fake model output in, gated
result out) and `classify()`'s unavailable path is exercised against
Settings with an empty key, per the task's dependency-injection requirement.
"""

import pytest

from core.config import Settings
from core.diagnose.llm_classifier import (
    CONFIDENCE_THRESHOLD,
    LLMUnavailableError,
    apply_confidence_gate,
    classify,
)


def test_confidence_threshold_constant_is_080():
    assert CONFIDENCE_THRESHOLD == 0.80


def test_confidence_below_threshold_abstains():
    result = apply_confidence_gate("insufficient_funds", 0.79)
    assert result.abstained is True
    assert result.predicted_root_cause is None
    assert result.confidence == 0.79


def test_confidence_at_or_above_threshold_does_not_abstain():
    result = apply_confidence_gate("insufficient_funds", 0.81)
    assert result.abstained is False
    assert result.predicted_root_cause == "insufficient_funds"
    assert result.confidence == 0.81


def test_confidence_exactly_at_threshold_does_not_abstain():
    result = apply_confidence_gate("card_expired", 0.80)
    assert result.abstained is False
    assert result.predicted_root_cause == "card_expired"


def test_classify_raises_llm_unavailable_error_when_no_api_key_configured():
    settings = Settings(
        razorpay_key_id="rzp_test_dummy",
        razorpay_key_secret="x",
        razorpay_webhook_secret="x",
        anthropic_api_key="",
    )
    with pytest.raises(LLMUnavailableError):
        classify("customer says the mandate was cancelled by their bank", settings=settings)
