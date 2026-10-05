"""Service-layer tests (no web server needed).  Run: python tests/test_backend.py"""
import copy
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["PRATYAKSH_DB"] = str(Path(tempfile.mkdtemp()) / "t.db")
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.seed import seed_if_empty  # noqa: E402
from app.services import core, discrepancy  # noqa: E402
from app.services.chain import GENESIS, seal  # noqa: E402


def fresh():
    con = db.connect(os.environ["PRATYAKSH_DB"] + str(datetime.now().timestamp()))
    db.init(con)
    seed_if_empty(con)
    return con


def event(sid, observed=25, infra=None, tamper=None, start=None):
    start = start or datetime.now(timezone.utc) - timedelta(hours=4)
    return {"schema": "pratyaksh.session.v1", "centre_id": "TC-KA-001", "camera_id": "CAM-01", "session_id": sid,
            "batch_id": "B1", "window": {"start": start.isoformat(), "end": (start + timedelta(hours=3)).isoformat(), "duration_s": 10800},
            "attendance": {"observed_count": observed, "peak_count": observed + 2, "confidence": 0.9, "timeline": [observed] * 5},
            "infrastructure": infra or [{"item": "computer", "sanctioned": 20, "detected": 20, "utilization_pct": 70, "status": "ok"}],
            "tamper": tamper or [], "camera_health": {"valid_pct": 99}, "flags": [], "evidence": [], "mode": "lite"}


def test_discrepancy_rules():
    assert discrepancy.evaluate(25, 26, 0.9, 99)["status"] == "ok"
    r = discrepancy.evaluate(18, 30, 0.9, 99)
    assert r["status"] == "mismatch" and r["severity"] == "high"
    assert discrepancy.evaluate(10, 30, 0.9, 30)["status"] == "unverifiable"
    assert discrepancy.evaluate(25, None, 0.9, 99)["status"] == "pending_register"


def test_ingest_register_and_chain():
    con = fresh()
    k = "dev-TC-KA-001"
    e1 = seal(event("S1", observed=18), GENESIS)
    r = core.ingest_event(con, e1, k)
    assert r["chain_ok"] and r["attendance_status"] == "pending_register"
    r = core.submit_register(con, "TC-KA-001", {"session_id": "S1", "reported_count": 30}, k)
    assert r["attendance_status"] == "mismatch" and r["alerts_created"] == 1
    e2 = seal(event("S2", infra=[{"item": "computer", "sanctioned": 20, "detected": 8, "utilization_pct": 60, "status": "missing"}],
                    tamper=[{"type": "REPLAY", "start_s": 100, "duration_s": 900, "confidence": 0.86}]), e1["hash"])
    r = core.ingest_event(con, e2, k)
    assert r["chain_ok"] and r["alerts_created"] == 2
    # forged event: contents edited after sealing
    e3 = seal(event("S3"), e2["hash"])
    e3["attendance"]["observed_count"] = 30
    r = core.ingest_event(con, e3, k)
    assert not r["chain_ok"]
    # deleted event: S5 links to S4 which never arrived
    e4 = seal(event("S4"), e2["hash"])
    e5 = seal(event("S5"), e4["hash"])
    assert not core.ingest_event(con, e5, k)["chain_ok"]
    c = core.get_centre(con, "TC-KA-001")
    assert c["risk_level"] in ("high", "critical"), c["trust_score"]
    types = {a["type"] for a in core.list_alerts(con, centre_id="TC-KA-001")}
    assert {"ATTENDANCE_GAP", "EQUIPMENT_MISSING", "TAMPER_REPLAY", "CHAIN_BREAK"} <= types, types
    b = core.brief(con, "TC-KA-001")
    assert "Findings" in b["text"] and b["suggested_checks"]
    assert core.ingest_event(con, e1, k)["status"] == "duplicate"


def test_auth():
    con = fresh()
    try:
        core.ingest_event(con, seal(event("X"), GENESIS), "wrong-key")
    except core.ServiceError as e:
        assert e.status == 401
    else:
        raise AssertionError("expected 401")


def test_edge_event_is_accepted():
    """An event produced by the real edge code must verify on the backend."""
    sys.path.insert(0, str(ROOT.parent / "edge"))
    from pratyaksh_edge.events import seal as edge_seal
    con = fresh()
    ev = event("EDGE-1")
    ev["attendance"]["confidence"] = 0.873
    ev["window"]["duration_s"] = 10799.9
    sealed = edge_seal(copy.deepcopy(ev), GENESIS)
    assert core.ingest_event(con, sealed, "dev-TC-KA-001")["chain_ok"]


if __name__ == "__main__":
    for fn in [test_discrepancy_rules, test_ingest_register_and_chain, test_auth, test_edge_event_is_accepted]:
        fn()
        print("PASS", fn.__name__)
