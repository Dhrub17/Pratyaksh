"""Event payloads and the tamper-evident hash chain.

Each session event carries `prev_hash` (hash of the previous event from this device) and
`hash` = SHA-256(prev_hash + canonical_json(event without "hash")). If anyone edits,
deletes or reorders events in the local outbox, the backend sees the chain break.

IMPORTANT: canonical_json must stay byte-identical to backend/app/services/chain.py.
"""
from __future__ import annotations

import hashlib
import json

GENESIS = "0" * 64
SCHEMA = "pratyaksh.session.v1"


def canonical_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(event: dict) -> str:
    body = {k: v for k, v in event.items() if k != "hash"}
    return hashlib.sha256((event.get("prev_hash", GENESIS) + canonical_json(body)).encode("utf-8")).hexdigest()


def seal(event: dict, prev_hash: str) -> dict:
    event = dict(event)
    event["prev_hash"] = prev_hash
    event["hash"] = compute_hash(event)
    return event


def verify_chain(events: list[dict]) -> tuple[bool, int]:
    """Returns (ok, index_of_first_bad_event or -1)."""
    prev = events[0].get("prev_hash", GENESIS) if events else GENESIS
    for i, ev in enumerate(events):
        if ev.get("prev_hash") != prev or compute_hash(ev) != ev.get("hash"):
            return False, i
        prev = ev["hash"]
    return True, -1
