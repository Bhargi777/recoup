"""Aggregates every core/api sub-router into one ``api_router`` that
``core.ingest.webhook_app`` mounts with a single ``include_router`` call."""

from __future__ import annotations

from fastapi import APIRouter

from core.api.decisions import router as decisions_router
from core.api.guardrails import router as guardrails_router
from core.api.kill_switch import router as kill_switch_router
from core.api.ledger import router as ledger_router
from core.api.metrics import router as metrics_router
from core.api.pipeline import router as pipeline_router

api_router = APIRouter()
api_router.include_router(pipeline_router)
api_router.include_router(decisions_router)
api_router.include_router(ledger_router)
api_router.include_router(guardrails_router)
api_router.include_router(metrics_router)
api_router.include_router(kill_switch_router)
