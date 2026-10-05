"""Store-and-forward uplink with bandwidth modes.

Modes
  full     events + up to 3 blurred evidence thumbnails per flagged session (320 px, q60)
  lite     events + 1 blurred thumbnail per flagged session (240 px, q40)   <- default
  ultra    events only, no images
  offline  queue only; flush when connectivity returns

The outbox is a local SQLite file, so a power cut or network outage never loses events,
and ordering (which the hash chain depends on) is preserved.
"""
from __future__ import annotations

import base64
import json
import logging
import sqlite3
import time
from pathlib import Path

import cv2
import numpy as np

from .events import GENESIS, canonical_json, seal

log = logging.getLogger(__name__)

MODES = {
    "full": {"thumbs": 3, "width": 320, "quality": 60},
    "lite": {"thumbs": 1, "width": 240, "quality": 40},
    "ultra": {"thumbs": 0, "width": 0, "quality": 0},
    "offline": {"thumbs": 1, "width": 240, "quality": 40},
}


def encode_thumb(img: np.ndarray, mode: str) -> str | None:
    spec = MODES[mode]
    if spec["thumbs"] == 0:
        return None
    h, w = img.shape[:2]
    nw = spec["width"]
    small = cv2.resize(img, (nw, int(h * nw / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, spec["quality"]])
    return base64.b64encode(buf.tobytes()).decode("ascii") if ok else None


class Outbox:
    def __init__(self, path: str | Path, api_url: str | None, device_key: str | None, mode: str = "lite"):
        self.db = sqlite3.connect(str(path))
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, centre_id TEXT, "
            "payload TEXT, hash TEXT, created REAL, sent REAL, attempts INTEGER DEFAULT 0)"
        )
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
        self.db.commit()
        self.api_url = api_url.rstrip("/") if api_url else None
        self.device_key = device_key
        self.mode = mode

    def chain_head(self, centre_id: str) -> str:
        row = self.db.execute("SELECT v FROM meta WHERE k=?", (f"head:{centre_id}",)).fetchone()
        return row[0] if row else GENESIS

    def enqueue(self, event: dict) -> dict:
        sealed = seal(event, self.chain_head(event["centre_id"]))
        payload = canonical_json(sealed)
        self.db.execute(
            "INSERT INTO outbox (centre_id, payload, hash, created) VALUES (?,?,?,?)",
            (sealed["centre_id"], payload, sealed["hash"], time.time()),
        )
        self.db.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?,?)", (f"head:{sealed['centre_id']}", sealed["hash"]))
        self.db.commit()
        return sealed

    def pending(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM outbox WHERE sent IS NULL").fetchone()[0]

    def flush(self, timeout: float = 10.0) -> dict:
        """Send queued events in order. Stops at the first failure to preserve chain order."""
        stats = {"sent": 0, "bytes": 0, "pending": self.pending(), "error": None}
        if self.mode == "offline" or not self.api_url:
            return stats
        import requests

        rows = self.db.execute("SELECT id, payload FROM outbox WHERE sent IS NULL ORDER BY id").fetchall()
        for rid, payload in rows:
            try:
                r = requests.post(
                    f"{self.api_url}/api/v1/ingest/events",
                    data=payload.encode("utf-8"),
                    headers={"Content-Type": "application/json", "X-Device-Key": self.device_key or ""},
                    timeout=timeout,
                )
                if r.status_code >= 300:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            except Exception as exc:
                self.db.execute("UPDATE outbox SET attempts = attempts + 1 WHERE id=?", (rid,))
                self.db.commit()
                stats["error"] = str(exc)
                log.warning("Uplink failed, will retry later: %s", exc)
                break
            self.db.execute("UPDATE outbox SET sent=? WHERE id=?", (time.time(), rid))
            self.db.commit()
            stats["sent"] += 1
            stats["bytes"] += len(payload)
        stats["pending"] = self.pending()
        return stats

    @staticmethod
    def payload_size(event: dict) -> int:
        return len(json.dumps(event).encode("utf-8"))
