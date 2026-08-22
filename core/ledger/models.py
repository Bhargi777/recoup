"""SQLModel schema for the append-only, hash-chained audit ledger.

Every event that observes or changes system state - ingestion, diagnosis,
policy gate decisions (allow AND deny), and money actions - is recorded here
before any side effect is considered complete. See
``.claude/skills/audit-ledger/SKILL.md`` for the full specification.
"""

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel

GENESIS_HASH = "0" * 64


class LedgerEvent(SQLModel, table=True):
    __tablename__ = "ledger_events"

    sequence_num: int = Field(primary_key=True)
    event_id: str = Field(index=True, unique=True)
    timestamp_utc: str
    aggregate_id: str = Field(index=True)
    event_type: str = Field(index=True)
    payload_json: str
    previous_hash: str
    current_hash: str = Field(index=True, unique=True)


def utc_now_iso() -> str:
    """Microsecond-precision UTC timestamp matching the ledger spec format."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
