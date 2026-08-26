"""Held-out evaluation for the Phase 4 diagnosis pipeline.

Per ``.claude/skills/honest-metrics/SKILL.md`` SS2 ("Held-Out Evaluation
Protocol"): loads the 200 records the Phase 3 generator sealed as
``held_out: true`` (a pure function of the committed ``split_seed``, never
re-split here), runs the real ``diagnose()`` orchestrator against each
record's ``error_code``/``error_reason``/``cohort`` (never ``true_root_cause``
- that is the label being predicted, not an input), and scores the
predictions against ``true_root_cause``.

Reports, per SS2, exactly the four required elements:
  - Macro precision / recall / F1 across all diagnosis categories.
  - Confusion matrix: full true-vs-predicted root-cause breakdown.
  - Abstain rate: share routed to the human exception queue for low confidence.
  - Coverage: proportion resolved deterministically vs. LLM vs. abstained.

No number here is estimated. This module only reports metrics computed from
an actual run of ``diagnose()`` against the actual persisted holdout rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlmodel import Session, select

from core.diagnose.diagnose import METHOD_ABSTAIN, METHOD_DETERMINISTIC, METHOD_LLM, diagnose
from core.ingest.synthetic import AtRiskRecord

ABSTAIN_LABEL = "ABSTAIN"


@dataclass
class DiagnosisEvalReport:
    total: int
    macro_precision: float
    macro_recall: float
    macro_f1: float
    abstain_rate: float
    per_class: dict[str, dict[str, float]]  # label -> {precision, recall, f1, support}
    confusion_matrix: dict[str, dict[str, int]]  # true_label -> {pred_label_or_ABSTAIN: count}
    coverage: dict[str, int] = field(default_factory=dict)  # method -> count

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "macro_precision": self.macro_precision,
            "macro_recall": self.macro_recall,
            "macro_f1": self.macro_f1,
            "abstain_rate": self.abstain_rate,
            "per_class": self.per_class,
            "confusion_matrix": self.confusion_matrix,
            "coverage": self.coverage,
        }


def load_holdout_records(session: Session) -> list[AtRiskRecord]:
    statement = select(AtRiskRecord).where(AtRiskRecord.held_out == True)  # noqa: E712
    return list(session.exec(statement).all())


def _macro_prf1(
    confusion_matrix: dict[str, dict[str, int]], labels: list[str]
) -> tuple[float, float, float, dict[str, dict[str, float]]]:
    """Standard multi-class macro precision/recall/F1 from a true-label-keyed
    confusion matrix. ABSTAIN predictions count against recall for their true
    class but never contribute a false positive to any real class (an
    abstain is not a claim about the label)."""
    per_class: dict[str, dict[str, float]] = {}
    precisions: list[float] = []
    recalls: list[float] = []
    f1s: list[float] = []

    for label in labels:
        tp = confusion_matrix.get(label, {}).get(label, 0)
        support = sum(confusion_matrix.get(label, {}).values())
        fn = support - tp

        fp = 0
        for true_label, preds in confusion_matrix.items():
            if true_label == label:
                continue
            fp += preds.get(label, 0)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)

    macro_precision = sum(precisions) / len(precisions) if precisions else 0.0
    macro_recall = sum(recalls) / len(recalls) if recalls else 0.0
    macro_f1 = sum(f1s) / len(f1s) if f1s else 0.0
    return macro_precision, macro_recall, macro_f1, per_class


def evaluate_holdout(
    session: Session, records: list[AtRiskRecord] | None = None, classify_fn=None
) -> DiagnosisEvalReport:
    """Run diagnose() on every held-out record and score against true_root_cause.

    ``records`` defaults to loading held_out=True rows from ``session``.
    ``classify_fn`` is forwarded to ``diagnose()`` (defaults to the real LLM
    path, which will honestly ABSTAIN in an environment with no
    ANTHROPIC_API_KEY rather than fabricate a result).
    """
    if records is None:
        records = load_holdout_records(session)

    confusion_matrix: dict[str, dict[str, int]] = {}
    coverage = {METHOD_DETERMINISTIC: 0, METHOD_LLM: 0, METHOD_ABSTAIN: 0}
    abstain_count = 0
    labels: set[str] = set()

    for record in records:
        true_label = record.true_root_cause
        labels.add(true_label)

        result = diagnose(session, record, classify_fn=classify_fn)
        coverage[result.method] = coverage.get(result.method, 0) + 1

        pred_label = result.predicted_root_cause if result.predicted_root_cause else ABSTAIN_LABEL
        if result.method == METHOD_ABSTAIN:
            abstain_count += 1

        confusion_matrix.setdefault(true_label, {})
        bucket = confusion_matrix[true_label]
        bucket[pred_label] = bucket.get(pred_label, 0) + 1

    sorted_labels = sorted(labels)
    macro_precision, macro_recall, macro_f1, per_class = _macro_prf1(
        confusion_matrix, sorted_labels
    )
    abstain_rate = abstain_count / len(records) if records else 0.0

    return DiagnosisEvalReport(
        total=len(records),
        macro_precision=macro_precision,
        macro_recall=macro_recall,
        macro_f1=macro_f1,
        abstain_rate=abstain_rate,
        per_class=per_class,
        confusion_matrix=confusion_matrix,
        coverage=coverage,
    )
