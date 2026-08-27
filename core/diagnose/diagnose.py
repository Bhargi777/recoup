"""Diagnosis orchestrator: deterministic mapper first, LLM fallback second,
explicit ABSTAIN otherwise. Every call emits exactly one ledger event -
CLAUDE.md's Definition of Done ("Any state mutation or decision emits a
verified audit event") applies to a *decision* like a diagnosis, not just to
a database write.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlmodel import Session

from core.diagnose.llm_classifier import ClassificationResult, LLMUnavailableError, classify
from core.diagnose.mapper import deterministic_diagnose
from core.ledger import append_event

DIAGNOSIS_COMPLETED = "DIAGNOSIS_COMPLETED"
DIAGNOSIS_ABSTAINED = "DIAGNOSIS_ABSTAINED"

METHOD_DETERMINISTIC = "deterministic"
METHOD_LLM = "llm"
METHOD_ABSTAIN = "abstain"


class DiagnosableRecord(Protocol):
    """Structural type for anything diagnose() can run against.

    ``core.ingest.synthetic.AtRiskRecord`` satisfies this by field name; this
    Protocol just documents/enforces the shape without diagnose.py depending
    on the concrete synthetic-data table type.
    """

    id: str
    cohort: str | None
    error_code: str | None
    error_reason: str | None
    notes: str | None


ClassifyFn = Any  # Callable[[str], ClassificationResult] - kept loose for easy DI in tests


@dataclass(frozen=True)
class DiagnosisResult:
    record_id: str
    predicted_root_cause: str | None
    method: str  # "deterministic" | "llm" | "abstain"
    confidence: float | None


def diagnose(
    session: Session,
    record: DiagnosableRecord,
    classify_fn: ClassifyFn | None = None,
    persist: bool = True,
) -> DiagnosisResult:
    """Diagnose one record's root cause and emit exactly one ledger event.

    ``persist=False`` skips the ledger append and just returns the result -
    for held-out evaluation (``core.eval.diagnosis_eval.evaluate_holdout``),
    which scores predictions against already-known labels and is re-run on
    every metrics read; that is measurement, not a real diagnosis decision,
    and must not grow the audit chain. Real diagnosis of records under
    active processing (``core.eval.batch_runner.run_batch``) always persists.

    Order of resolution:
      1. Deterministic mapper (cohort rule, then error-reason lookup). This
         resolves the overwhelming majority of records given Phase 3's
         records are themselves drawn from the same verified catalog.
      2. LLM fallback - only attempted if the deterministic mapper found no
         match AND the record carries free text (``notes``) worth
         classifying. On this synthetic dataset every record has non-empty
         notes, but the deterministic mapper is expected to resolve ~100% of
         them (per taxonomy construction), so this branch is exercised in
         unit tests via dependency injection rather than in the real
         held-out eval run.
      3. ABSTAIN - no deterministic match, no free text, LLM unavailable, or
         LLM confidence below threshold. Always a labeled, ledgered state,
         never a silent failure.

    ``classify_fn`` defaults to ``core.diagnose.llm_classifier.classify`` but
    can be swapped for a fake in tests so no network call or API key is ever
    required to exercise this path.
    """
    root_cause = deterministic_diagnose(record.cohort, record.error_code, record.error_reason)
    if root_cause is not None:
        if persist:
            append_event(
                session,
                record.id,
                DIAGNOSIS_COMPLETED,
                {
                    "predicted_root_cause": root_cause,
                    "method": METHOD_DETERMINISTIC,
                    "confidence": None,
                },
            )
        return DiagnosisResult(
            record_id=record.id,
            predicted_root_cause=root_cause,
            method=METHOD_DETERMINISTIC,
            confidence=None,
        )

    free_text = getattr(record, "notes", None)
    if not free_text:
        if persist:
            append_event(
                session,
                record.id,
                DIAGNOSIS_ABSTAINED,
                {
                    "predicted_root_cause": None,
                    "method": METHOD_ABSTAIN,
                    "confidence": None,
                    "reason": "no_deterministic_match_no_free_text",
                },
            )
        return DiagnosisResult(
            record_id=record.id, predicted_root_cause=None, method=METHOD_ABSTAIN, confidence=None
        )

    active_classify_fn = classify_fn or classify
    try:
        result: ClassificationResult = active_classify_fn(free_text)
    except LLMUnavailableError:
        if persist:
            append_event(
                session,
                record.id,
                DIAGNOSIS_ABSTAINED,
                {
                    "predicted_root_cause": None,
                    "method": METHOD_ABSTAIN,
                    "confidence": None,
                    "reason": "llm_unavailable",
                },
            )
        return DiagnosisResult(
            record_id=record.id, predicted_root_cause=None, method=METHOD_ABSTAIN, confidence=None
        )

    if result.abstained:
        if persist:
            append_event(
                session,
                record.id,
                DIAGNOSIS_ABSTAINED,
                {
                    "predicted_root_cause": None,
                    "method": METHOD_ABSTAIN,
                    "confidence": result.confidence,
                    "reason": "llm_confidence_below_threshold",
                },
            )
        return DiagnosisResult(
            record_id=record.id,
            predicted_root_cause=None,
            method=METHOD_ABSTAIN,
            confidence=result.confidence,
        )

    if persist:
        append_event(
            session,
            record.id,
            DIAGNOSIS_COMPLETED,
            {
                "predicted_root_cause": result.predicted_root_cause,
                "method": METHOD_LLM,
                "confidence": result.confidence,
            },
        )
    return DiagnosisResult(
        record_id=record.id,
        predicted_root_cause=result.predicted_root_cause,
        method=METHOD_LLM,
        confidence=result.confidence,
    )
