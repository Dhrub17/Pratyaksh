"""SQLite storage (stdlib only). Swap for PostgreSQL + TimescaleDB in production; the SQL is
plain and the service layer is the only place that touches it."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS centres (
  id TEXT PRIMARY KEY, name TEXT, state TEXT, district TEXT, lat REAL, lng REAL,
  scheme TEXT, trades TEXT, capacity INTEGER, sanctioned_inventory TEXT,
  device_key TEXT, bandwidth_mode TEXT DEFAULT 'lite', chain_head TEXT,
  last_seen TEXT, trust_score REAL DEFAULT 100, risk_level TEXT DEFAULT 'low',
  score_breakdown TEXT DEFAULT '[]', created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, centre_id TEXT REFERENCES centres(id), batch_id TEXT, camera_id TEXT,
  date TEXT, start TEXT, end TEXT, duration_s REAL,
  observed_count INTEGER, peak_count INTEGER, sustained_tracks INTEGER, confidence REAL, valid_pct REAL,
  reported_count INTEGER, gap INTEGER, gap_pct REAL, attendance_status TEXT,
  infrastructure TEXT, tamper TEXT, flags TEXT, camera_health TEXT, timeline TEXT, evidence TEXT,
  payload_bytes INTEGER, mode TEXT, detector TEXT, hash TEXT, prev_hash TEXT, chain_ok INTEGER,
  received_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_sessions_centre_date ON sessions(centre_id, date);
CREATE TABLE IF NOT EXISTS registers (
  session_id TEXT PRIMARY KEY, centre_id TEXT, batch_id TEXT, date TEXT, reported_count INTEGER,
  submitted_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, centre_id TEXT, session_id TEXT, type TEXT, subject TEXT DEFAULT '',
  severity TEXT, title TEXT, detail TEXT, status TEXT DEFAULT 'open', note TEXT DEFAULT '',
  created_at TEXT, updated_at TEXT, UNIQUE(session_id, type, subject)
);
CREATE INDEX IF NOT EXISTS ix_alerts_centre ON alerts(centre_id, status);
"""

JSON_COLS = {"trades", "sanctioned_inventory", "score_breakdown", "infrastructure", "tamper", "flags",
             "camera_health", "timeline", "evidence"}


def connect(path=None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or DB_PATH), check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    con.commit()


def row(r) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in JSON_COLS & d.keys():
        if isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except json.JSONDecodeError:
                pass
    return d


def rows(rs) -> list[dict]:
    return [row(r) for r in rs]


def dumps(v) -> str:
    return json.dumps(v, separators=(",", ":"))


@contextmanager
def session_scope(path=None):
    con = connect(path)
    try:
        yield con
        con.commit()
    finally:
        con.close()
