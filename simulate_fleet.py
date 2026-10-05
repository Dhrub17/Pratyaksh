#!/usr/bin/env python3
"""Fleet simulator: generates realistic, hash-chained edge events for every seeded centre so
the dashboard has 2 weeks of history, including staged fraud scenarios.

  # through the running API (exercises ingest end to end)
  python scripts/simulate_fleet.py --api http://localhost:8000 --days 14

  # straight into the database (no server needed)
  python scripts/simulate_fleet.py --direct --reset --days 14

Personas (assigned deterministically, documented so judges can check the system finds them):
  honest           registers match reality
  inflator         claims (almost) the full batch while 55-75% attend
  ghost            claims full batch while 25-45% attend
  missing_equip    sanctioned equipment removed partway through the window
  idle_equip       equipment present but almost never used
  tamperer         covers the lens / replays footage on some days
  log_tamper       deletes an event from the edge device (breaks the hash chain)
  offline          connectivity lost for the last 3 days (store-and-forward pending)

TC-KA-001 is skipped by default: it is reserved for the live edge-device demo, which owns
that centre's hash chain.
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.chain import GENESIS, seal  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
PERSONAS = {
    "TC-BR-022": "ghost", "TC-UP-019": "ghost",
    "TC-RJ-018": "inflator", "TC-JH-004": "inflator", "TC-MP-011": "inflator", "TC-WB-007": "inflator",
    "TC-PB-014": "missing_equip", "TC-GJ-009": "missing_equip", "TC-TS-011": "missing_equip",
    "TC-AP-010": "idle_equip", "TC-CG-002": "idle_equip",
    "TC-BR-014": "tamperer", "TC-MH-021": "tamperer",
    "TC-UP-027": "log_tamper",
    "TC-AS-002": "offline", "TC-JK-004": "offline",
}
HEAVY = ["lathe", "welding_set", "sewing_machine", "computer", "hospital_bed"]


def sessions_for(day: date):
    if day.weekday() == 6:
        return []
    return [("B1", 9, 30, 3.0), ("B2", 14, 0, 3.0)]


def build_event(c: dict, persona: str, day: date, batch: str, h: int, m: int, hours: float, rng: random.Random, day_idx: int, days: int):
    cap = c["capacity"]
    inv = c["sanctioned_inventory"]
    start = datetime(day.year, day.month, day.day, h, m, tzinfo=IST)
    end = start + timedelta(hours=hours)
    if persona == "inflator":
        truth = round(cap * rng.uniform(0.55, 0.75))
        reported = cap - rng.randint(0, 2)
    elif persona == "ghost":
        truth = round(cap * rng.uniform(0.25, 0.45))
        reported = cap
    else:
        truth = round(cap * rng.uniform(0.78, 0.96))
        reported = truth + rng.choice([0, 0, 0, 1, -1])

    tamper, valid_pct = [], round(rng.uniform(96, 100), 1)
    if persona == "tamperer" and day_idx % 4 == 1 and batch == "B1":
        kind = "REPLAY" if day_idx % 8 == 5 else "COVERED"
        dur = rng.randint(1500, 4200) if kind == "COVERED" else rng.randint(1800, 5400)
        tamper.append({"type": kind, "start_s": float(rng.randint(600, 3000)), "duration_s": float(dur),
                       "confidence": 0.93 if kind == "COVERED" else 0.86,
                       "detail": "" if kind == "COVERED" else "footage from ~2400s earlier is being replayed"})
        valid_pct = round(max(5.0, 100 - 100 * dur / (hours * 3600)), 1)
    if persona == "honest" and rng.random() < 0.02:
        tamper.append({"type": "BLURRED", "start_s": 400.0, "duration_s": 240.0, "confidence": 0.8, "detail": ""})
        valid_pct = 97.5

    observed = max(0, round(truth + rng.gauss(0, 0.9)))
    if valid_pct < 50:
        observed = max(0, round(observed * valid_pct / 100))
    conf = round(rng.uniform(0.80, 0.95) if valid_pct > 90 else rng.uniform(0.45, 0.65), 2)

    infra = []
    removal_day = days - 6
    for item, n in inv.items():
        detected = n if item != "seating" else max(n - rng.randint(0, 2), 0)
        util = rng.uniform(45, 88)
        if persona == "missing_equip" and day_idx >= removal_day and item in HEAVY:
            detected = max(0, n - max(1, round(n * 0.45)) if n > 2 else n - n)
        if persona == "idle_equip" and item in HEAVY:
            util = rng.uniform(3, 15)
        if item == "seating":
            util = min(100.0, 100 * truth / max(1, n))
        if detected < n * 0.9:
            status = "missing" if detected < n * 0.5 else "partial"
        elif util < 25:
            status = "idle"
        else:
            status = "ok"
        infra.append({"item": item, "sanctioned": n, "detected": detected, "operational": round(detected * util / 100),
                      "utilization_pct": round(util, 1), "status": status,
                      "source": "golden_frame" if item in ("lathe", "welding_set") else "detector"})

    tl = [max(0, round(observed * (0.6 + 0.4 * min(1, i / 3)) + rng.gauss(0, 0.8))) for i in range(24)]
    flags = sorted({f"TAMPER_{t['type']}" for t in tamper} | {f"EQUIPMENT_{i['status'].upper()}" for i in infra if i["status"] != "ok"})
    ev = {
        "schema": "pratyaksh.session.v1", "edge_version": "0.1.0", "centre_id": c["id"], "camera_id": "CAM-01",
        "session_id": f"{c['id']}-{day.strftime('%Y%m%d')}-{batch}", "batch_id": batch,
        "window": {"start": start.isoformat(), "end": end.isoformat(), "duration_s": hours * 3600},
        "attendance": {"observed_count": observed, "peak_count": max(tl + [observed]) + rng.randint(0, 2),
                       "median_count": float(observed), "sustained_tracks": max(0, observed + rng.choice([-1, 0, 0, 1])),
                       "confidence": conf, "samples": int(hours * 3600 / 3), "coverage_pct": valid_pct, "timeline": tl},
        "infrastructure": infra, "tamper": tamper,
        "camera_health": {"brightness": round(rng.uniform(95, 140), 1), "contrast": round(rng.uniform(38, 60), 1),
                          "sharpness": round(rng.uniform(80, 240), 1), "valid_pct": valid_pct,
                          "samples": int(hours * 1200), "resolution": "1280x720"},
        "flags": flags, "evidence": [], "mode": c.get("bandwidth_mode") or "lite", "detector": "yolo",
        "privacy": {"faces_identified": False, "video_uploaded": False, "evidence_anonymised": True},
    }
    return ev, reported


class Sink:
    def centres(self): ...
    def event(self, c, ev): ...
    def register(self, c, sid, batch, d, reported): ...


class ApiSink(Sink):
    def __init__(self, api):
        import requests
        self.r, self.api = requests, api.rstrip("/")

    def centres(self):
        out = self.r.get(f"{self.api}/api/v1/centres", timeout=20).json()
        return [dict(c, device_key=f"dev-{c['id']}") for c in out]

    def event(self, c, ev):
        resp = self.r.post(f"{self.api}/api/v1/ingest/events", json=ev, headers={"X-Device-Key": c["device_key"]}, timeout=20)
        resp.raise_for_status()

    def register(self, c, sid, batch, d, reported):
        resp = self.r.post(f"{self.api}/api/v1/centres/{c['id']}/attendance", headers={"X-Device-Key": c["device_key"]},
                           json={"session_id": sid, "batch_id": batch, "date": d, "reported_count": reported}, timeout=20)
        resp.raise_for_status()


class DirectSink(Sink):
    def __init__(self, reset: bool):
        from app import db
        from app.config import DB_PATH
        from app.seed import seed_if_empty
        from app.services import core

        if reset and Path(DB_PATH).exists():
            for suffix in ("", "-wal", "-shm"):
                p = Path(str(DB_PATH) + suffix)
                if p.exists():
                    p.unlink()
        self.db, self.core = db, core
        self.con = db.connect()
        db.init(self.con)
        seed_if_empty(self.con)

    def centres(self):
        return self.db.rows(self.con.execute("SELECT * FROM centres").fetchall())

    def event(self, c, ev):
        self.core.ingest_event(self.con, ev, c["device_key"])

    def register(self, c, sid, batch, d, reported):
        self.core.submit_register(self.con, c["id"], {"session_id": sid, "batch_id": batch, "date": d, "reported_count": reported}, c["device_key"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--direct", action="store_true", help="write to the DB directly (no server)")
    ap.add_argument("--reset", action="store_true", help="with --direct: delete the DB first")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip", default="TC-KA-001", help="comma-separated centres reserved for live edge devices")
    a = ap.parse_args()
    sink = DirectSink(a.reset) if a.direct else ApiSink(a.api)
    skip = {s for s in a.skip.split(",") if s}
    today = datetime.now(IST).date()
    total = 0
    for c in sink.centres():
        if c["id"] in skip:
            continue
        persona = PERSONAS.get(c["id"], "honest")
        rng = random.Random(f"{a.seed}-{c['id']}")
        prev = GENESIS
        dropped = False
        for di in range(a.days):
            day = today - timedelta(days=a.days - 1 - di)
            if persona == "offline" and di >= a.days - 3:
                continue
            for batch, h, m, hours in sessions_for(day):
                start = datetime(day.year, day.month, day.day, h, m, tzinfo=IST)
                if start > datetime.now(IST):
                    continue
                ev, reported = build_event(c, persona, day, batch, h, m, hours, rng, di, a.days)
                sealed = seal(ev, prev)
                prev = sealed["hash"]
                if persona == "log_tamper" and not dropped and di == a.days - 5 and batch == "B1":
                    dropped = True          # event deleted on the device: never reaches the server
                    continue
                sink.event(c, sealed)
                if rng.random() > 0.03:      # a few registers are never submitted
                    sink.register(c, sealed["session_id"], batch, day.isoformat(), reported)
                total += 1
        print(f"{c['id']:<10} {persona:<14} done")
    if a.direct:
        sink.core.rescore_all(sink.con)
    print(f"Simulated {total} sessions.")


if __name__ == "__main__":
    main()
