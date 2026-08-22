import time

from core.ingest.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


def test_starts_closed() -> None:
    cb = CircuitBreaker()
    assert cb.state == CircuitState.CLOSED
    cb.before_call()  # does not raise


def test_opens_after_threshold_consecutive_failures() -> None:
    cb = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=60)
    for _ in range(3):
        cb.before_call()
        cb.record_failure()
    assert cb.state == CircuitState.OPEN
    try:
        cb.before_call()
        raise AssertionError("expected CircuitOpenError")
    except CircuitOpenError:
        pass


def test_success_resets_failure_count() -> None:
    cb = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=60)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED  # only 2 consecutive since the success


def test_half_open_after_reset_timeout_and_closes_on_success() -> None:
    cb = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=0.05)
    cb.before_call()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    time.sleep(0.06)
    assert cb.state == CircuitState.HALF_OPEN
    cb.before_call()  # the one allowed probe
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_half_open_probe_failure_reopens_circuit() -> None:
    cb = CircuitBreaker(failure_threshold=1, reset_timeout_seconds=0.05)
    cb.before_call()
    cb.record_failure()
    time.sleep(0.06)
    assert cb.state == CircuitState.HALF_OPEN
    cb.before_call()
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
