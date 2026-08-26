from core.ledger.hashing import canonicalize_payload, compute_hash


def test_canonicalize_payload_sorts_keys_and_strips_whitespace() -> None:
    payload = {"b": 2, "a": 1, "nested": {"z": 1, "y": 2}}
    assert canonicalize_payload(payload) == '{"a":1,"b":2,"nested":{"y":2,"z":1}}'


def test_compute_hash_is_deterministic() -> None:
    args = (1, "2026-08-22T08:30:00.000000Z", "pay_risk_1", "EVENT", {"x": 1}, "0" * 64)
    assert compute_hash(*args) == compute_hash(*args)


def test_compute_hash_changes_with_any_field() -> None:
    base = compute_hash(1, "t", "agg", "EVENT", {"x": 1}, "0" * 64)
    assert compute_hash(2, "t", "agg", "EVENT", {"x": 1}, "0" * 64) != base
    assert compute_hash(1, "t2", "agg", "EVENT", {"x": 1}, "0" * 64) != base
    assert compute_hash(1, "t", "agg2", "EVENT", {"x": 1}, "0" * 64) != base
    assert compute_hash(1, "t", "agg", "EVENT2", {"x": 1}, "0" * 64) != base
    assert compute_hash(1, "t", "agg", "EVENT", {"x": 2}, "0" * 64) != base
    assert compute_hash(1, "t", "agg", "EVENT", {"x": 1}, "f" * 64) != base
