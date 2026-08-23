"""GET/POST /api/kill-switch - real state via replay, real toggle.

GET replays the ledger the same way ``recoup kill-switch status`` does
(``core.policy.is_kill_switch_active``) - there is no mutable "is_active"
row anywhere (see ``core.policy.kill_switch`` module docstring).

POST calls the real ``activate_kill_switch``/``deactivate_kill_switch``,
which append ``KILL_SWITCH_ACTIVATED``/``KILL_SWITCH_DEACTIVATED`` ledger
events - the identical functions the CLI's ``recoup kill-switch on|off``
command calls. This is the one mutating route in ``core/api`` and it only
ever does what the CLI equivalent already does.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from core.api.deps import get_session
from core.policy import activate_kill_switch, deactivate_kill_switch, is_kill_switch_active

router = APIRouter(prefix="/api/kill-switch", tags=["kill-switch"])


class KillSwitchToggleRequest(BaseModel):
    action: str  # "on" | "off"
    reason: str = ""


@router.get("")
def get_kill_switch(session: Session = Depends(get_session)) -> dict:
    active = is_kill_switch_active(session)
    return {"active": active}


@router.post("")
def post_kill_switch(
    body: KillSwitchToggleRequest, session: Session = Depends(get_session)
) -> dict:
    action = body.action.lower()
    if action not in {"on", "off"}:
        raise HTTPException(
            status_code=400, detail=f"action must be 'on' or 'off', got {body.action!r}"
        )

    reason = body.reason or "toggled from operator dashboard"
    if action == "on":
        activate_kill_switch(session, reason)
    else:
        deactivate_kill_switch(session, reason)

    active = is_kill_switch_active(session)
    return {"active": active}
