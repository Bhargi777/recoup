"""Razorpay Test Mode HTTP client.

Every mutating call is idempotency-gated against the ledger BEFORE dispatch
(.claude/skills/razorpay-testmode/SKILL.md §3): if a prior call with the same
idempotency key already succeeded, the recorded result is returned and no
second HTTP request is made. Every call - mutating or read-only - emits a
ledger event; nothing bypasses the audit trail.

Retries: 429 honors Retry-After; 5xx and network errors retry with full-jitter
exponential backoff, gated by a circuit breaker that opens after repeated
consecutive failures (§9). A failed dispatch is always safely retryable via
the same idempotency key.
"""

import json
import time
from typing import Any

import httpx
from sqlmodel import Session

from core.ingest.backoff import retry_after_or_backoff
from core.ingest.circuit_breaker import CircuitBreaker
from core.ingest.idempotency import compute_idempotency_key
from core.ledger import append_event, list_events

RAZORPAY_BASE_URL = "https://api.razorpay.com/v1"


class RazorpayAPIError(RuntimeError):
    """Raised when Razorpay returns a non-2xx response with an error body."""

    def __init__(
        self,
        status_code: int,
        code: str,
        description: str,
        source: str | None,
        step: str | None,
        reason: str | None,
        metadata: dict | None = None,
    ):
        self.status_code = status_code
        self.code = code
        self.description = description
        self.source = source
        self.step = step
        self.reason = reason
        self.metadata = metadata or {}
        super().__init__(f"{code} ({reason}): {description}")


def _find_cached_success(
    session: Session, event_type: str, idempotency_key: str
) -> dict[str, Any] | None:
    """O(n) scan over the ledger for a prior success with this idempotency key.

    Fine at current data volumes (hundreds of records); revisit with a
    dedicated lookup index if aggregate ledger size grows into the millions.
    """
    for event in list_events(session):
        if event.event_type != event_type:
            continue
        payload = json.loads(event.payload_json)
        if payload.get("idempotency_key") == idempotency_key:
            return payload.get("response")
    return None


class RazorpayClient:
    def __init__(
        self,
        key_id: str,
        key_secret: str,
        session: Session,
        base_url: str = RAZORPAY_BASE_URL,
        transport: httpx.BaseTransport | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        max_retries: int = 3,
    ):
        self._session = session
        self._client = httpx.Client(
            base_url=base_url, auth=(key_id, key_secret), transport=transport, timeout=30.0
        )
        self._breaker = circuit_breaker or CircuitBreaker()
        self._max_retries = max_retries

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "RazorpayClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- mutating calls (idempotency-gated) ---------------------------------

    def create_order(
        self,
        amount_paise: int,
        currency: str,
        receipt: str,
        notes: dict[str, str] | None = None,
        attempt_num: int = 0,
    ) -> dict[str, Any]:
        return self._dispatch_idempotent(
            action_type="create_order",
            entity_id=receipt,
            attempt_num=attempt_num,
            method="POST",
            path="/orders",
            json_body={
                "amount": amount_paise,
                "currency": currency,
                "receipt": receipt,
                "notes": notes or {},
            },
        )

    def create_payment_link(
        self,
        amount_paise: int,
        currency: str,
        description: str,
        reference_id: str,
        customer: dict[str, str] | None = None,
        attempt_num: int = 0,
    ) -> dict[str, Any]:
        return self._dispatch_idempotent(
            action_type="create_payment_link",
            entity_id=reference_id,
            attempt_num=attempt_num,
            method="POST",
            path="/payment_links",
            json_body={
                "amount": amount_paise,
                "currency": currency,
                "description": description,
                "reference_id": reference_id,
                "customer": customer or {},
            },
        )

    # -- read-only calls (always dispatched, always logged) -----------------

    def fetch_payment(self, payment_id: str) -> dict[str, Any]:
        return self._dispatch_readonly(
            "fetch_payment", payment_id, "GET", f"/payments/{payment_id}"
        )

    def fetch_subscription(self, subscription_id: str) -> dict[str, Any]:
        return self._dispatch_readonly(
            "fetch_subscription", subscription_id, "GET", f"/subscriptions/{subscription_id}"
        )

    # -- internals ------------------------------------------------------------

    def _dispatch_idempotent(
        self,
        action_type: str,
        entity_id: str,
        attempt_num: int,
        method: str,
        path: str,
        json_body: dict[str, Any],
    ) -> dict[str, Any]:
        idempotency_key = compute_idempotency_key(action_type, entity_id, attempt_num)
        succeeded_event_type = f"RAZORPAY_{action_type.upper()}_SUCCEEDED"

        cached = _find_cached_success(self._session, succeeded_event_type, idempotency_key)
        if cached is not None:
            append_event(
                self._session,
                entity_id,
                f"RAZORPAY_{action_type.upper()}_DEDUPED",
                {"idempotency_key": idempotency_key},
            )
            return cached

        append_event(
            self._session,
            entity_id,
            f"RAZORPAY_{action_type.upper()}_INTENT",
            {"idempotency_key": idempotency_key, "request": json_body},
        )

        response = self._request_with_retries(method, path, json_body)

        append_event(
            self._session,
            entity_id,
            succeeded_event_type,
            {"idempotency_key": idempotency_key, "response": response},
        )
        return response

    def _dispatch_readonly(
        self, action_type: str, entity_id: str, method: str, path: str
    ) -> dict[str, Any]:
        response = self._request_with_retries(method, path, None)
        append_event(
            self._session,
            entity_id,
            f"RAZORPAY_{action_type.upper()}",
            {"response": response},
        )
        return response

    def _request_with_retries(
        self, method: str, path: str, json_body: dict[str, Any] | None
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            self._breaker.before_call()
            try:
                http_response = self._client.request(method, path, json=json_body)
            except httpx.TransportError as exc:
                self._breaker.record_failure()
                last_error = exc
                if attempt < self._max_retries:
                    time.sleep(retry_after_or_backoff(attempt, None))
                    continue
                raise

            if http_response.status_code == 429 or http_response.status_code >= 500:
                self._breaker.record_failure()
                last_error = RazorpayAPIError(
                    http_response.status_code,
                    "TRANSIENT_ERROR",
                    http_response.text,
                    None,
                    None,
                    None,
                )
                if attempt < self._max_retries:
                    retry_after = http_response.headers.get("Retry-After")
                    time.sleep(retry_after_or_backoff(attempt, retry_after))
                    continue
                raise last_error

            if http_response.status_code >= 400:
                self._breaker.record_failure()
                body = http_response.json().get("error", {})
                raise RazorpayAPIError(
                    http_response.status_code,
                    body.get("code", "UNKNOWN_ERROR"),
                    body.get("description", http_response.text),
                    body.get("source"),
                    body.get("step"),
                    body.get("reason"),
                    body.get("metadata"),
                )

            self._breaker.record_success()
            return http_response.json()

        assert last_error is not None
        raise last_error
