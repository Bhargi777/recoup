"""Secondary LLM fallback classifier with a hard-coded confidence gate.

CLAUDE.md SS4 ("AI Authority & Judgment Boundary") is explicit: LLMs are
NEVER the sole authority for money actions, and here specifically they are
"utilized only as a secondary classifier for ambiguous/free-text failure
reasons" with an explicit ABSTAIN path below a confidence threshold. This
module implements exactly that boundary:

- The LLM (when available) only ever produces a *label + confidence*.
- The decision to trust that label or ABSTAIN is a plain, deterministic
  Python comparison (``confidence >= CONFIDENCE_THRESHOLD``) - the model
  never decides whether to abstain; this code does.

Honesty requirement (this phase's task spec, and CLAUDE.md SS4 zero
fabrication rule): there is no ``ANTHROPIC_API_KEY`` in this sandboxed
environment. Rather than silently returning a fabricated confident label,
``classify()`` raises ``LLMUnavailableError`` when no key is configured. It
is never called for real as part of this task - only unit-tested via an
injected fake ``classify_fn`` (see ``core/diagnose/diagnose.py`` and
``tests/test_llm_classifier.py``), so nothing here claims a live model call
happened when it did not.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.config import Settings, get_settings

CONFIDENCE_THRESHOLD = 0.80


class LLMUnavailableError(RuntimeError):
    """Raised when the LLM fallback path is invoked but no API key is configured.

    This is the honest failure mode: no key means no call was made, so no
    result may be reported. Callers (core.diagnose.diagnose.diagnose) catch
    this and route the record to ABSTAIN rather than letting it propagate as
    an unhandled crash.
    """


@dataclass(frozen=True)
class ClassificationResult:
    """Output of the LLM classification step, before OR after the gate.

    ``abstained`` is set by ``apply_confidence_gate`` (or by the caller for
    an unavailable/errored path) - never by the raw model call itself.
    """

    predicted_root_cause: str | None
    confidence: float
    abstained: bool


def apply_confidence_gate(predicted_root_cause: str, confidence: float) -> ClassificationResult:
    """Deterministic gate: confidence < 0.80 -> ABSTAIN. Hard-coded, not LLM-decided."""
    if confidence < CONFIDENCE_THRESHOLD:
        return ClassificationResult(
            predicted_root_cause=None, confidence=confidence, abstained=True
        )
    return ClassificationResult(
        predicted_root_cause=predicted_root_cause, confidence=confidence, abstained=False
    )


def classify(free_text: str, settings: Settings | None = None) -> ClassificationResult:
    """Real implementation: call the Anthropic API, then apply the confidence gate.

    Not exercised with a live network call anywhere in this repo's test
    suite or CI - there is no ANTHROPIC_API_KEY available. It exists so the
    integration point is real code, not a stub, and so a future environment
    with a key can use it as-is.
    """
    settings = settings or get_settings()
    if not settings.anthropic_api_key:
        raise LLMUnavailableError(
            "ANTHROPIC_API_KEY is not configured; the LLM fallback classifier is "
            "unavailable in this environment. Refusing to fabricate a classification."
        )

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    taxonomy = (
        "card_expired, incorrect_cvv, card_not_enabled_online, card_blocked, "
        "insufficient_funds, limit_exceeded, authentication_failed, abandonment, "
        "risk_blocked, card_declined_generic, bank_technical_error, "
        "gateway_technical_error, invalid_vpa, vpa_resolution_failed, credit_failed, "
        "invoice_overdue"
    )
    prompt = (
        "Classify this payment-failure free-text description into exactly one of "
        f"this closed taxonomy: {taxonomy}. "
        'Respond ONLY with JSON: {"root_cause": "<label>", "confidence": <0..1 float>}. '
        f"Description: {free_text}"
    )
    response = client.messages.create(
        model="claude-3-5-haiku-latest",
        max_tokens=128,
        messages=[{"role": "user", "content": prompt}],
    )

    import json

    text = response.content[0].text
    parsed = json.loads(text)
    predicted_root_cause = parsed["root_cause"]
    confidence = float(parsed["confidence"])

    return apply_confidence_gate(predicted_root_cause, confidence)
