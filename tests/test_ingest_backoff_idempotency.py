import random

from core.ingest.backoff import compute_backoff_seconds, retry_after_or_backoff
from core.ingest.idempotency import compute_idempotency_key


def test_backoff_grows_exponentially_and_respects_cap() -> None:
    rng = random.Random(0)
    b0 = compute_backoff_seconds(0, base=1.0, cap=100.0, rng=rng)
    b1 = compute_backoff_seconds(1, base=1.0, cap=100.0, rng=rng)
    b2 = compute_backoff_seconds(2, base=1.0, cap=100.0, rng=rng)
    assert 1.0 <= b0 < 2.0
    assert 2.0 <= b1 < 3.0
    assert 4.0 <= b2 < 5.0

    capped = compute_backoff_seconds(20, base=1.0, cap=5.0, rng=rng)
    assert 5.0 <= capped < 6.0


def test_retry_after_header_takes_precedence() -> None:
    assert retry_after_or_backoff(3, "7") == 7.0


def test_retry_after_falls_back_on_malformed_header() -> None:
    rng = random.Random(0)
    fallback = retry_after_or_backoff(0, "not-a-number", rng=rng)
    direct = compute_backoff_seconds(0, rng=random.Random(0))
    assert fallback == direct


def test_retry_after_falls_back_when_absent() -> None:
    rng = random.Random(0)
    fallback = retry_after_or_backoff(1, None, rng=rng)
    direct = compute_backoff_seconds(1, rng=random.Random(0))
    assert fallback == direct


def test_idempotency_key_is_deterministic_and_scoped() -> None:
    k1 = compute_idempotency_key("create_payment_link", "invoice_1", 0)
    k2 = compute_idempotency_key("create_payment_link", "invoice_1", 0)
    assert k1 == k2
    assert len(k1) == 64

    assert compute_idempotency_key("create_payment_link", "invoice_1", 1) != k1
    assert compute_idempotency_key("create_payment_link", "invoice_2", 0) != k1
    assert compute_idempotency_key("create_order", "invoice_1", 0) != k1
