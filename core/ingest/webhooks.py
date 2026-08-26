"""Webhook signature verification and dedupe/routing.

Verified against Razorpay's docs (fetched 2026-08-22,
https://razorpay.com/docs/webhooks/validate-test/):
- Signature header: ``X-Razorpay-Signature``, HMAC-SHA256 over the raw
  request body bytes, keyed by the webhook secret. Never re-serialize the
  body before verifying.
- Dedup header: ``x-razorpay-event-id`` - "unique per event" per Razorpay.

A duplicate event must be a no-op: it gets HTTP 200 and never re-triggers a
downstream action. See .claude/skills/razorpay-testmode/SKILL.md §4.
"""

import hashlib
import hmac
import json
from typing import Any

from sqlmodel import Session

from core.ledger import append_event, list_events

SIGNATURE_HEADER = "x-razorpay-signature"
EVENT_ID_HEADER = "x-razorpay-event-id"

PAYMENT_FAILED = "PAYMENT_FAILED"
PAYMENT_LINK_PAID = "PAYMENT_LINK_PAID"
SUBSCRIPTION_CHARGED = "SUBSCRIPTION_CHARGED"
SUBSCRIPTION_HALTED = "SUBSCRIPTION_HALTED"

# Events this phase records into the ledger. Action-taking on these events is
# the executor layer's job (core/act, Phase 6) - Phase 2 only ingests and logs.
KNOWN_EVENTS = {
    "payment.failed": PAYMENT_FAILED,
    "payment_link.paid": PAYMENT_LINK_PAID,
    "subscription.charged": SUBSCRIPTION_CHARGED,
    "subscription.halted": SUBSCRIPTION_HALTED,
}


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    if not signature:
        return False
    computed = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)


def _fallback_event_id(raw_body: bytes) -> str:
    """Used only when x-razorpay-event-id is absent (should not happen in
    practice per Razorpay's docs); keeps dedup well-defined regardless."""
    return "body_sha256_" + hashlib.sha256(raw_body).hexdigest()


def _is_duplicate(session: Session, event_id: str) -> bool:
    for event in list_events(session):
        if event.event_type == "WEBHOOK_RECEIVED":
            payload = json.loads(event.payload_json)
            if payload.get("event_id") == event_id:
                return True
    return False


def _extract_aggregate_id(event_name: str, payload: dict[str, Any]) -> str:
    entity = payload.get("payload", {})
    if event_name.startswith("payment_link"):
        link = entity.get("payment_link", {}).get("entity", {})
        return link.get("id", "unknown")
    if event_name.startswith("subscription"):
        sub = entity.get("subscription", {}).get("entity", {})
        return sub.get("id", "unknown")
    payment = entity.get("payment", {}).get("entity", {})
    return payment.get("id", "unknown")


def handle_webhook_event(
    session: Session, raw_body: bytes, headers: dict[str, str]
) -> dict[str, Any]:
    """Verify, dedupe, and record one webhook delivery. Caller has already
    resolved the secret; this only orchestrates dedupe + ledger recording."""
    event_id = headers.get(EVENT_ID_HEADER) or _fallback_event_id(raw_body)

    if _is_duplicate(session, event_id):
        append_event(session, event_id, "WEBHOOK_DEDUPED", {"event_id": event_id})
        return {"status": "duplicate", "event_id": event_id}

    body = json.loads(raw_body)
    event_name = body.get("event", "unknown")

    append_event(
        session,
        event_id,
        "WEBHOOK_RECEIVED",
        {"event_id": event_id, "event_name": event_name},
    )

    domain_event_type = KNOWN_EVENTS.get(event_name)
    if domain_event_type is None:
        append_event(
            session,
            event_id,
            "WEBHOOK_UNRECOGNIZED",
            {"event_id": event_id, "event_name": event_name},
        )
        return {"status": "unrecognized", "event_name": event_name}

    aggregate_id = _extract_aggregate_id(event_name, body)
    append_event(session, aggregate_id, domain_event_type, {"event_id": event_id, "raw": body})
    return {"status": "recorded", "event_name": event_name, "aggregate_id": aggregate_id}
