"""Shared FastAPI dependencies for core/api routers.

Reuses the SAME SQLAlchemy engine the ingest webhook app's lifespan already
created on ``app.state.engine`` (see ``core.ingest.webhook_app._lifespan``) -
routers here never open a second connection pool or a second app.
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlmodel import Session


def get_session(request: Request) -> Generator[Session, None, None]:
    with Session(request.app.state.engine) as session:
        yield session
