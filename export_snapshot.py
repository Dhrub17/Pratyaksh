#!/usr/bin/env python3
"""Export the current database as a static JSON snapshot for the dashboard's offline demo mode.

  python scripts/export_snapshot.py --out ../frontend/src/demo-snapshot.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db  # noqa: E402
from app.services import core  # noqa: E402

KEEP = ("id", "batch_id", "date", "start", "observed_count", "peak_count", "confidence", "valid_pct", "reported_count",
        "gap", "gap_pct", "attendance_status", "infrastructure", "tamper", "timeline", "payload_bytes", "chain_ok", "hash", "mode")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "frontend/src/demo-snapshot.json"))
    ap.add_argument("--sessions", type=int, default=24)
    a = ap.parse_args()
    con = db.connect()
    centres = core.list_centres(con)
    details, briefs = {}, {}
    for c in centres:
        d = core.centre_detail(con, c["id"])
        d["sessions"] = [{k: s.get(k) for k in KEEP} for s in d["sessions"][: a.sessions]]
        d["alerts"] = d["alerts"][:40]
        details[c["id"]] = d
        briefs[c["id"]] = core.brief(con, c["id"])
    snap = {"summary": core.dashboard_summary(con), "centres": centres, "details": details, "briefs": briefs,
            "alerts": core.list_alerts(con, limit=400), "queue": core.inspection_queue(con, 25), "fleet": core.fleet(con)}
    Path(a.out).write_text(json.dumps(snap, separators=(",", ":")))
    print(f"Wrote {a.out} ({Path(a.out).stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
