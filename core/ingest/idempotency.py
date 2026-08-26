"""Idempotency key derivation, per .claude/skills/razorpay-testmode/SKILL.md §3.

idempotency_key = sha256(f"{action_type}:{entity_id}:{attempt_num}")
"""

import hashlib


def compute_idempotency_key(action_type: str, entity_id: str, attempt_num: int) -> str:
    raw = f"{action_type}:{entity_id}:{attempt_num}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
