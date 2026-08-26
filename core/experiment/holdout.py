"""Deterministic randomized holdout assignment.

``assign_group`` is a PURE function of ``(customer_id, seed)`` - no
randomness, no database read, no clock. The same customer always lands in
the same group for a given seed, forever; re-running a batch never
reshuffles who is in treatment vs. control. This is what makes the holdout
usable as a real randomized-control comparison (honest-metrics SKILL.md
SS3): every action-or-no-action decision for a customer is fixed the moment
the seed is fixed, not re-rolled per run.

Mechanism: hash ``f"{seed}:{customer_id}"`` with SHA-256, take the first 8
hex digits as a uniform 32-bit integer, and scale to a float in [0, 100).
Customers whose scaled value falls below ``holdout_percent`` are control;
everyone else is treatment. SHA-256 output is uniformly distributed, so this
reproduces an (approximately, not exactly) ``holdout_percent``-sized control
arm without needing to know the full customer population up front - unlike
``core.ingest.synthetic.assign_holdout_ids``, which partitions a known,
fixed set of ids exactly. The two are different mechanisms for different
purposes and are not expected to agree.

The control group NEVER receives an intervention - full stop. That
invariant is enforced by the batch orchestrator (``core.eval.batch_runner``),
not here; this module only computes which group a customer is in.
"""

from __future__ import annotations

import hashlib
from typing import Literal

Group = Literal["treatment", "control"]

TREATMENT: Group = "treatment"
CONTROL: Group = "control"


def assign_group(customer_id: str, holdout_percent: float, seed: int) -> Group:
    """Deterministically assign one customer to "treatment" or "control".

    Pure function of (customer_id, holdout_percent, seed) - no I/O, no
    mutable state, no dependence on call order or how many times it has been
    called before for this or any other customer.
    """
    if not (0.0 <= holdout_percent <= 100.0):
        raise ValueError(f"holdout_percent must be within [0, 100], got {holdout_percent!r}")
    if not customer_id:
        raise ValueError("customer_id must be non-empty")

    digest = hashlib.sha256(f"{seed}:{customer_id}".encode("utf-8")).hexdigest()
    bucket = (int(digest[:8], 16) / 0xFFFFFFFF) * 100.0
    return CONTROL if bucket < holdout_percent else TREATMENT
