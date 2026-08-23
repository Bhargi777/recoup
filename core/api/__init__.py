"""Read-only JSON API for the Phase 8 operator dashboard.

Mounted onto the existing FastAPI app (``core.ingest.webhook_app.app``) via
``core.api.router`` - this module deliberately does NOT stand up a second
FastAPI application; the ingest webhook receiver and the dashboard API are
one process, one set of settings, one lifespan.

Every route here is read-only against already-persisted state, with exactly
one exception: ``POST /api/kill-switch`` - which itself only calls the real
``core.policy.activate_kill_switch``/``deactivate_kill_switch`` (append-only
ledger events), never a mutable row. No route here computes or fabricates a
number; every response is built from a real query against
``core.ledger``/``core.ingest.synthetic``/``core.eval``/``core.experiment``.

Sub-modules, one per dashboard page:
  - ``pipeline``   -> /api/pipeline
  - ``decisions``  -> /api/decisions
  - ``ledger``     -> /api/ledger, /api/ledger/verify
  - ``guardrails`` -> /api/guardrails
  - ``metrics``    -> /api/metrics
  - ``kill_switch``-> /api/kill-switch (GET/POST)
"""

from core.api.router import api_router

__all__ = ["api_router"]
