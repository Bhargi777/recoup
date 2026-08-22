"""Canonical payload serialization and SHA-256 hash-chain construction.

Algorithm is fixed by ``.claude/skills/audit-ledger/SKILL.md`` - do not change
field order or separators, or every historical hash becomes unverifiable.
"""

import hashlib
import json
from typing import Any


def canonicalize_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_hash(
    sequence_num: int,
    timestamp_utc: str,
    aggregate_id: str,
    event_type: str,
    payload: dict[str, Any],
    previous_hash: str,
) -> str:
    payload_canonical = canonicalize_payload(payload)
    data_to_hash = (
        f"{sequence_num}|{timestamp_utc}|{aggregate_id}|{event_type}|"
        f"{payload_canonical}|{previous_hash}"
    )
    return hashlib.sha256(data_to_hash.encode("utf-8")).hexdigest()
