"""Wilson score confidence interval - the single source of truth referenced
by ``.claude/skills/honest-metrics/SKILL.md`` SS3.

The Wilson score interval (Wilson, 1927) for a binomial proportion, at
confidence level given by ``z`` (1.96 => 95%)::

    p_hat = k / n
    denom = 1 + z**2 / n
    center = (p_hat + z**2 / (2 * n)) / denom
    spread = z * sqrt(p_hat * (1 - p_hat) / n + z**2 / (4 * n**2)) / denom
    wilson_ci = (center - spread, center + spread)

Used instead of the normal (Wald) approximation because Wilson stays inside
[0, 1] and remains well-behaved at small n or extreme p - exactly the
regime a 15% holdout control arm sits in. honest-metrics SKILL.md is
explicit that this is the required formula; nothing here approximates it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Z_95 = 1.96


@dataclass(frozen=True)
class WilsonInterval:
    point_estimate: float
    lower: float
    upper: float
    n: int
    k: int
    z: float = Z_95

    def as_dict(self) -> dict:
        return {
            "point_estimate": self.point_estimate,
            "lower": self.lower,
            "upper": self.upper,
            "n": self.n,
            "k": self.k,
            "z": self.z,
        }


def wilson_score_interval(k: int, n: int, z: float = Z_95) -> WilsonInterval:
    """95% (or z-specified) Wilson score confidence interval for k successes
    out of n trials. n == 0 is a real, valid input (an empty arm) - it
    returns the maximally uninformative interval [0, 1] rather than raising,
    since honest-metrics SKILL.md SS3 requires callers to say "the CI is
    wide" for zero-conversion arms rather than crash or divide by zero.
    """
    if n < 0 or k < 0:
        raise ValueError("k and n must be non-negative")
    if k > n:
        raise ValueError(f"k ({k}) cannot exceed n ({n})")

    if n == 0:
        return WilsonInterval(point_estimate=0.0, lower=0.0, upper=1.0, n=0, k=0, z=z)

    p_hat = k / n
    denom = 1 + z**2 / n
    center = (p_hat + z**2 / (2 * n)) / denom
    spread = z * math.sqrt(p_hat * (1 - p_hat) / n + z**2 / (4 * n**2)) / denom
    lower = max(0.0, center - spread)
    upper = min(1.0, center + spread)
    return WilsonInterval(point_estimate=p_hat, lower=lower, upper=upper, n=n, k=k, z=z)
