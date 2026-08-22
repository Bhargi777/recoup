"""Circuit breaker for the Razorpay HTTP client.

CLOSED -> OPEN after `failure_threshold` consecutive failures. OPEN blocks all
calls until `reset_timeout_seconds` has elapsed, then allows exactly one probe
in HALF_OPEN; that probe's outcome decides CLOSED (success) or back to OPEN
(failure). See .claude/skills/razorpay-testmode/SKILL.md §9.
"""

import time
from enum import Enum


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(RuntimeError):
    """Raised when a call is attempted while the breaker is OPEN."""


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_timeout_seconds: float = 30.0):
        self.failure_threshold = failure_threshold
        self.reset_timeout_seconds = reset_timeout_seconds
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._half_open_probe_in_flight = False

    @property
    def state(self) -> CircuitState:
        if self._opened_at is None:
            return CircuitState.CLOSED
        if self._half_open_probe_in_flight:
            return CircuitState.HALF_OPEN
        if time.monotonic() - self._opened_at >= self.reset_timeout_seconds:
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    def before_call(self) -> None:
        state = self.state
        if state == CircuitState.OPEN:
            raise CircuitOpenError(
                f"circuit OPEN: {self._consecutive_failures} consecutive failures, "
                f"retry after {self.reset_timeout_seconds}s from last failure"
            )
        if state == CircuitState.HALF_OPEN:
            # Single-process, synchronous assumption: only one caller reaches
            # here at a time, so no concurrent-probe race to guard against.
            self._half_open_probe_in_flight = True

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._opened_at = None
        self._half_open_probe_in_flight = False

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        self._half_open_probe_in_flight = False
        if self._consecutive_failures >= self.failure_threshold:
            self._opened_at = time.monotonic()
