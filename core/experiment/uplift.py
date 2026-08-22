"""Recovery uplift: Treatment vs. deterministic holdout Control, with 95%
Wilson confidence intervals on each arm's recovery rate
(``core.experiment.stats.wilson_score_interval`` - the single source of
truth per honest-metrics SKILL.md SS3).

IMPORTANT - read before printing any number this module returns: the
"recovered" counts fed in here are only as real as their source. In this
codebase, the only source of a recovered/not-recovered label is
``core.experiment.simulated_outcome`` - an explicitly labeled SIMULATION
built to demonstrate this statistical pipeline end to end, NOT observed real
Razorpay payment behavior (there are no live test-mode credentials or real
customer traffic in this environment). This module does not itself fabricate
anything or hide that fact, but it also does not restate it - callers
(CLI output, README, PR body) MUST state the "simulated outcome, not real
recovered revenue" qualifier in the same breath as any uplift number printed
from an ``UpliftReport``.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.experiment.stats import WilsonInterval, wilson_score_interval


@dataclass(frozen=True)
class UpliftReport:
    treatment: WilsonInterval
    control: WilsonInterval

    @property
    def uplift(self) -> float:
        """Treatment recovery rate minus control recovery rate (percentage
        points, as a fraction e.g. 0.08 == +8pp)."""
        return self.treatment.point_estimate - self.control.point_estimate

    def as_dict(self) -> dict:
        return {
            "treatment": self.treatment.as_dict(),
            "control": self.control.as_dict(),
            "uplift": self.uplift,
        }


def compute_uplift(
    treatment_recovered: int,
    treatment_total: int,
    control_recovered: int,
    control_total: int,
) -> UpliftReport:
    """Compute the uplift and per-arm Wilson 95% CIs from raw counts.

    Per honest-metrics SKILL.md SS3: always publish n per arm alongside any
    rate (both are carried on the returned WilsonIntervals), and if either
    arm has zero conversions the returned interval is honestly wide (up to
    the theoretical ceiling), never quoted as a precise number or a raw
    multiple.
    """
    treatment = wilson_score_interval(treatment_recovered, treatment_total)
    control = wilson_score_interval(control_recovered, control_total)
    return UpliftReport(treatment=treatment, control=control)
