"""FastAPI app exposing the Razorpay webhook receiver.

Run with: uvicorn core.ingest.webhook_app:app
"""

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session

from core.api import api_router
from core.config import get_settings
from core.ingest.synthetic import init_synthetic_schema
from core.ingest.webhooks import SIGNATURE_HEADER, handle_webhook_event, verify_signature
from core.ledger import get_engine, init_ledger_schema


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    engine = get_engine(settings.database_url)
    init_ledger_schema(engine)
    # The dashboard's pipeline/metrics endpoints read core.ingest.synthetic's
    # AtRiskRecord table directly - create its schema up front so a fresh
    # database doesn't 500 before `recoup generate-synthetic-data` has run.
    init_synthetic_schema(engine)
    app.state.engine = engine
    yield


app = FastAPI(title="recoup ingest", version="0.1.0", lifespan=_lifespan)

# The Phase 8 operator dashboard (dashboard/, Vite dev server) runs on a
# different origin/port than this API in local/demo use (e.g. 5173 vs 8000).
# This is a hackathon/demo deployment with no real users or production
# traffic - permissive localhost CORS is a deliberate, disclosed choice here,
# NOT a production posture. A real deployment would restrict this to the
# dashboard's actual deployed origin.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(api_router)


def get_session() -> Generator[Session, None, None]:
    with Session(app.state.engine) as session:
        yield session


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request, session: Session = Depends(get_session)
) -> Response:
    settings = get_settings()
    raw_body = await request.body()
    signature = request.headers.get(SIGNATURE_HEADER, "")

    if not verify_signature(raw_body, signature, settings.razorpay_webhook_secret):
        return Response(status_code=400, content="invalid signature")

    handle_webhook_event(session, raw_body, dict(request.headers))
    # Always 200 on a verified, processed delivery - including duplicates -
    # so Razorpay does not retry an event we have already recorded.
    return Response(status_code=200)
