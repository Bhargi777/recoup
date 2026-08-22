---
name: audit-ledger
description: Specification for the hash-chained, append-only immutable audit ledger and deterministic replay engine.
---

# Audit Ledger Skill & Specification

The audit ledger is the source of truth for all events, decisions, guardrail checks, and financial actions in `recoup`.

## 1. Schema Specification

Each event in the ledger adheres to the following immutable structure:

```json
{
  "event_id": "evt_01HXYZ...",
  "sequence_num": 1042,
  "timestamp_utc": "2026-08-22T08:30:00.123456Z",
  "aggregate_id": "pay_risk_98765",
  "event_type": "POLICY_GATE_EVALUATED",
  "payload": {
    "decision_id": "dec_456",
    "rule_name": "quiet_hours_check",
    "status": "BLOCKED",
    "reason": "Target time 22:15 IST violates DND window (21:00-09:00)",
    "metadata": {}
  },
  "previous_hash": "a3b1c9...",
  "current_hash": "f7e2d1..."
}
```

## 2. Hash-Chain Construction
- **Genesis Block**: Sequence 0 has `previous_hash = "0" * 64`.
- **Hash Algorithm**: SHA-256 over canonicalized representation:
  ```python
  payload_canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'))
  data_to_hash = f"{sequence_num}|{timestamp_utc}|{aggregate_id}|{event_type}|{payload_canonical}|{previous_hash}"
  current_hash = hashlib.sha256(data_to_hash.encode('utf-8')).hexdigest()
  ```

## 3. Tamper-Detection & Verification Contract
- The command `recoup verify-chain` iterates sequentially through all ledger entries:
  1. Verifies `entry[i].previous_hash == entry[i-1].current_hash`.
  2. Recomputes `SHA-256` of entry contents and asserts equality with `entry[i].current_hash`.
  3. Ensures monotonically increasing `sequence_num` and ascending `timestamp_utc`.
- Any mutation of past rows instantly breaks the hash chain, identifying the exact corrupted sequence number.

## 4. State Replay Contract
- Complete system state (customer cooldowns, cumulative budget spend, retry counts, open exception queues) can be deterministically reconstructed solely by replaying ledger events from sequence 0 to HEAD.
- Replay must be side-effect-free: it reads the ledger and rebuilds projections; it never re-executes external API calls.
- Any state query answered by the application must be reproducible via replay; divergence between live state and replayed state is a P0 bug.
