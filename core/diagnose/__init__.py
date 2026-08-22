"""Deterministic error-code mapper with LLM fallback and explicit ABSTAIN."""

from core.diagnose.mapper import (
    BANNED_ERROR_REASONS,
    ERROR_REASON_TO_ROOT_CAUSE,
    deterministic_diagnose,
)

__all__ = [
    "BANNED_ERROR_REASONS",
    "ERROR_REASON_TO_ROOT_CAUSE",
    "deterministic_diagnose",
]
