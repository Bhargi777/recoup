"""Deterministic holdout assignment (15% control), uplift calculation + Wilson CI.

Public surface: ``assign_group`` (holdout.py), ``simulated_outcome`` (an
explicitly labeled simulation - see its module docstring before using it),
``wilson_score_interval`` (stats.py), and ``compute_uplift`` (uplift.py).
"""

from core.experiment.holdout import CONTROL, TREATMENT, Group, assign_group
from core.experiment.simulated_outcome import (
    BASELINE_RECOVERY_RATE,
    TREATMENT_UPLIFT_PP,
    simulated_outcome,
)
from core.experiment.stats import WilsonInterval, wilson_score_interval
from core.experiment.uplift import UpliftReport, compute_uplift

__all__ = [
    "BASELINE_RECOVERY_RATE",
    "CONTROL",
    "TREATMENT",
    "TREATMENT_UPLIFT_PP",
    "Group",
    "UpliftReport",
    "WilsonInterval",
    "assign_group",
    "compute_uplift",
    "simulated_outcome",
    "wilson_score_interval",
]
