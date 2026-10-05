"""Must stay byte-identical with edge/pratyaksh_edge/events.py."""
import hashlib
import json

GENESIS = "0" * 64


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
