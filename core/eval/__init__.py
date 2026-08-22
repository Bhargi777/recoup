"""Batch runner, held-out evaluation suite, metrics report generator."""

from core.eval.diagnosis_eval import DiagnosisEvalReport, evaluate_holdout, load_holdout_records

__all__ = ["DiagnosisEvalReport", "evaluate_holdout", "load_holdout_records"]
