"""Exponential backoff with full jitter, per .claude/skills/razorpay-testmode/SKILL.md §9.

backoff = min(cap, base * 2^attempt) + uniform(0, 1)
"""

import random


def compute_backoff_seconds(
    attempt: int, base: float = 0.5, cap: float = 30.0, rng: random.Random | None = None
) -> float:
    rng = rng or random
    return min(cap, base * (2**attempt)) + rng.uniform(0, 1)


def retry_after_or_backoff(
    attempt: int, retry_after_header: str | None, rng: random.Random | None = None
) -> float:
    """Honor a server-supplied Retry-After (seconds) if present and well-formed,
    else fall back to exponential backoff with jitter."""
    if retry_after_header is not None:
        try:
            return max(0.0, float(retry_after_header))
        except ValueError:
            pass
    return compute_backoff_seconds(attempt, rng=rng)
