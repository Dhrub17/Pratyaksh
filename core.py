"""Business logic. Pure functions over a sqlite3 connection, so they are testable without a
web server and reusable by the simulator and by future workers (e.g. a nightly rescoring job)."""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .. import db
from ..config import SCORE_WINDOW_DAYS
from . import discrepancy, risk
from .chain import GENESIS, compute_hash

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class ServiceError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def to_utc(ts: str) -> str:
    """Normalise any ISO timestamp to UTC so string comparison and sorting are safe."""
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------- centres
def get_centre(con: sqlite3.Connection, centre_id: str) -> dict:
    c = db.row(con.execute("SELECT * FROM centres WHERE id=?", (centre_id,)).fetchone())
    if not c:
        raise ServiceError(404, f"Unknown centre {centre_id}")
    return c


def check_device(con, centre_id: str, key: str | None, admin_key: str | None = None) -> dict:
    c = get_centre(con, centre_id)
    if key and (key == c["device_key"] or (admin_key and key == admin_key)):
        return c
    raise ServiceError(401, "Invalid or missing X-Device-Key for this centre")


def create_centre(con, data: dict) -> dict:
    if con.execute("SELECT 1 FROM centres WHERE id=?", (data["id"],)).fetchone():
        raise ServiceError(409, f"Centre {data['id']} already exists")
    con.execute(
        "INSERT INTO centres (id,name,state,district,lat,lng,scheme,trades,capacity,sanctioned_inventory,device_key,bandwidth_mode,chain_head) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (data["id"], data["name"], data["state"], data.get("district", ""), data["lat"], data["lng"],
         data.get("scheme", "PMKVY 4.0"), db.dumps(data.get("trades", [])), data.get("capacity", 30),
         db.dumps(data.get("sanctioned_inventory", {})), data["device_key"], data.get("bandwidth_mode", "lite"), GENESIS),
    )
    con.commit()
    return get_centre(con, data["id"])


def _public_centre(c: dict) -> dict:
    c = dict(c)
    c.pop("device_key", None)
    return c


# ---------------------------------------------------------------------------- ingest
def ingest_event(con, event: dict, device_key: str | None, admin_key: str | None = None) -> dict:
    centre = check_device(con, event["centre_id"], device_key, admin_key)
    priv = event.get("privacy") or {}
    if priv.get("faces_identified") or priv.get("video_uploaded"):
        raise ServiceError(422, "Rejected: events must not contain identified faces or uploaded video (privacy policy)")
    sid = event["session_id"]
    if con.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone():
        return {"status": "duplicate", "session_id": sid}

    hash_valid = compute_hash(event) == event.get("hash")
    link_valid = event.get("prev_hash") == (centre["chain_head"] or GENESIS)
    chain_ok = 1 if (hash_valid and link_valid) else 0

    att = event.get("attendance", {})
    health = event.get("camera_health", {})
    start = event["window"]["start"]
    reg = con.execute("SELECT reported_count FROM registers WHERE session_id=?", (sid,)).fetchone()
    reported = reg[0] if reg else None
    ev = discrepancy.evaluate(att.get("observed_count"), reported, att.get("confidence"), health.get("valid_pct"))
    payload_bytes = len(json.dumps(event, separators=(",", ":")).encode())

    con.execute(
        "INSERT INTO sessions (id,centre_id,batch_id,camera_id,date,start,end,duration_s,observed_count,peak_count,"
        "sustained_tracks,confidence,valid_pct,reported_count,gap,gap_pct,attendance_status,infrastructure,tamper,flags,"
        "camera_health,timeline,evidence,payload_bytes,mode,detector,hash,prev_hash,chain_ok,received_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (sid, centre["id"], event.get("batch_id"), event.get("camera_id"), start[:10], start, event["window"]["end"],
         event["window"].get("duration_s"), att.get("observed_count"), att.get("peak_count"), att.get("sustained_tracks"),
         att.get("confidence"), health.get("valid_pct"), reported, ev["gap"], ev["gap_pct"], ev["status"],
         db.dumps(event.get("infrastructure", [])), db.dumps(event.get("tamper", [])), db.dumps(event.get("flags", [])),
         db.dumps(health), db.dumps(att.get("timeline", [])), db.dumps(event.get("evidence", [])),
         payload_bytes, event.get("mode"), event.get("detector"), event.get("hash"), event.get("prev_hash"), chain_ok, now_iso()),
    )
    # Advance the head only when the hash itself is valid, so a forged event cannot reset the chain.
    new_head = event["hash"] if hash_valid else centre["chain_head"]
    con.execute("UPDATE centres SET chain_head=?, last_seen=?, bandwidth_mode=? WHERE id=?",
                (new_head, max(to_utc(event["window"]["end"]), centre["last_seen"] or ""), event.get("mode", centre["bandwidth_mode"]), centre["id"]))

    session = db.row(con.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone())
    created = _alerts_for_session(con, session, ev)
    if not chain_ok:
        reason = "hash does not match contents" if not hash_valid else "previous-hash link does not match last accepted event"
        created += _alert(con, centre["id"], sid, "CHAIN_BREAK", "", "critical", "Event log integrity check failed",
                          f"Session {sid}: {reason}. Events may have been edited, deleted or replayed on the device.", start)
    rescore(con, centre["id"])
    con.commit()
    return {"status": "accepted", "session_id": sid, "chain_ok": bool(chain_ok), "attendance_status": ev["status"],
            "alerts_created": created}


def submit_register(con, centre_id: str, data: dict, key: str | None, admin_key: str | None = None) -> dict:
    check_device(con, centre_id, key, admin_key)
    sid = data["session_id"]
    con.execute("INSERT OR REPLACE INTO registers (session_id,centre_id,batch_id,date,reported_count,submitted_at) VALUES (?,?,?,?,?,?)",
                (sid, centre_id, data.get("batch_id"), data.get("date"), int(data["reported_count"]), now_iso()))
    s = db.row(con.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone())
    result = {"status": "stored", "session_id": sid, "attendance_status": "pending_footage", "alerts_created": 0}
    if s:
        ev = discrepancy.evaluate(s["observed_count"], int(data["reported_count"]), s["confidence"], s["valid_pct"])
        con.execute("UPDATE sessions SET reported_count=?, gap=?, gap_pct=?, attendance_status=? WHERE id=?",
                    (int(data["reported_count"]), ev["gap"], ev["gap_pct"], ev["status"], sid))
        s.update(reported_count=int(data["reported_count"]), gap=ev["gap"], gap_pct=ev["gap_pct"], attendance_status=ev["status"])
        result.update(attendance_status=ev["status"], alerts_created=_attendance_alert(con, s, ev))
        rescore(con, centre_id)
    con.commit()
    return result


# ---------------------------------------------------------------------------- alerts
def _alert(con, centre_id, session_id, typ, subject, severity, title, detail, created) -> int:
    cur = con.execute(
        "INSERT OR IGNORE INTO alerts (centre_id,session_id,type,subject,severity,title,detail,status,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,'open',?,?)", (centre_id, session_id, typ, subject, severity, title, detail, created, now_iso()))
    return cur.rowcount


def _attendance_alert(con, s: dict, ev: dict) -> int:
    if ev["status"] == "mismatch":
        return _alert(con, s["centre_id"], s["id"], "ATTENDANCE_GAP", "", ev["severity"],
                      f"Attendance overstated by {ev['gap']} ({ev['gap_pct']:.0%})",
                      f"Register claims {s['reported_count']} trainees; camera observed {s['observed_count']} "
                      f"(peak {s['peak_count']}, confidence {s['confidence']:.2f}, tolerance ±{ev['tolerance']}).", s["start"])
    if ev["status"] == "unverifiable":
        return _alert(con, s["centre_id"], s["id"], "ATTENDANCE_UNVERIFIABLE", "", "medium",
                      "Attendance could not be verified",
                      f"Only {s['valid_pct']:.0f}% of the session footage passed integrity checks; register claims {s['reported_count']}.", s["start"])
    return 0


TAMPER_TEXT = {
    "COVERED": ("high", "Camera covered or in darkness"),
    "BLURRED": ("medium", "Camera view obstructed or out of focus"),
    "SHIFTED": ("high", "Camera pointed away from the approved view"),
    "FROZEN": ("critical", "Frozen feed: a still image replaced live video"),
    "REPLAY": ("critical", "Recorded footage replayed into the camera feed"),
}


def _alerts_for_session(con, s: dict, ev: dict) -> int:
    n = _attendance_alert(con, s, ev)
    for t in s.get("tamper") or []:
        sev, title = TAMPER_TEXT.get(t["type"], ("medium", t["type"].title()))
        mins = t.get("duration_s", 0) / 60
        n += _alert(con, s["centre_id"], s["id"], f"TAMPER_{t['type']}", f"{t.get('start_s', 0)}", sev,
                    f"{title} for {mins:.0f} min" if mins >= 1 else title,
                    f"Detected {t.get('start_s', 0):.0f}s into the session (confidence {t.get('confidence', 0):.2f}). {t.get('detail', '')}".strip(),
                    s["start"])
    for it in s.get("infrastructure") or []:
        st = it.get("status")
        name = it["item"].replace("_", " ")
        if st in ("missing", "partial"):
            short = it["sanctioned"] - it.get("detected", 0)
            n += _alert(con, s["centre_id"], s["id"], "EQUIPMENT_MISSING", it["item"], "high" if st == "missing" else "medium",
                        f"{short} of {it['sanctioned']} {name} not visible",
                        f"Sanctioned {it['sanctioned']}, detected {it.get('detected', 0)} (source: {it.get('source', 'detector')}).", s["start"])
        elif st == "idle":
            n += _alert(con, s["centre_id"], s["id"], "EQUIPMENT_IDLE", it["item"], "low",
                        f"{name.capitalize()} present but rarely used",
                        f"Utilisation {it.get('utilization_pct', 0):.0f}% while trainees were present.", s["start"])
    return n


def list_alerts(con, status: str | None = None, severity: str | None = None, centre_id: str | None = None,
                limit: int = 200) -> list[dict]:
    q, args = "SELECT a.*, c.name AS centre_name, c.state FROM alerts a JOIN centres c ON c.id=a.centre_id WHERE 1=1", []
    if status:
        q += " AND a.status=?"
        args.append(status)
    if severity:
        q += " AND a.severity=?"
        args.append(severity)
    if centre_id:
        q += " AND a.centre_id=?"
        args.append(centre_id)
    q += " ORDER BY a.created_at DESC LIMIT ?"
    args.append(limit)
    out = db.rows(con.execute(q, args).fetchall())
    out.sort(key=lambda a: a["created_at"] or "", reverse=True)
    out.sort(key=lambda a: (a["status"] != "open", SEV_ORDER.get(a["severity"], 9)))
    return out


def update_alert(con, alert_id: int, status: str, note: str = "") -> dict:
    if status not in ("open", "acknowledged", "resolved", "escalated", "dismissed"):
        raise ServiceError(422, "Invalid status")
    cur = con.execute("UPDATE alerts SET status=?, note=?, updated_at=? WHERE id=?", (status, note, now_iso(), alert_id))
    if cur.rowcount == 0:
        raise ServiceError(404, "Alert not found")
    con.commit()
    return db.row(con.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone())


# ---------------------------------------------------------------------------- scoring
def _window_sessions(con, centre_id: str, days: int = SCORE_WINDOW_DAYS) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    return db.rows(con.execute("SELECT * FROM sessions WHERE centre_id=? AND date>=? ORDER BY start", (centre_id, since)).fetchall())


def rescore(con, centre_id: str) -> dict:
    last = con.execute("SELECT last_seen FROM centres WHERE id=?", (centre_id,)).fetchone()
    silent = None
    if last and last[0]:
        silent = (datetime.now(timezone.utc) - datetime.fromisoformat(last[0])).total_seconds() / 3600
    score, level, breakdown = risk.compute(_window_sessions(con, centre_id), silent)
    con.execute("UPDATE centres SET trust_score=?, risk_level=?, score_breakdown=? WHERE id=?",
                (score, level, db.dumps(breakdown), centre_id))
    return {"trust_score": score, "risk_level": level, "breakdown": breakdown}


def rescore_all(con) -> None:
    for (cid,) in con.execute("SELECT id FROM centres").fetchall():
        rescore(con, cid)
    con.commit()


# ---------------------------------------------------------------------------- read models
def list_centres(con, state: str | None = None, risk_level: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM centres WHERE 1=1", []
    if state:
        q += " AND state=?"
        args.append(state)
    if risk_level:
        q += " AND risk_level=?"
        args.append(risk_level)
    centres = [_public_centre(c) for c in db.rows(con.execute(q, args).fetchall())]
    open_counts = defaultdict(lambda: defaultdict(int))
    for cid, sev, n in con.execute("SELECT centre_id, severity, COUNT(*) FROM alerts WHERE status='open' GROUP BY centre_id, severity"):
        open_counts[cid][sev] = n
    since = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    agg = {r[0]: r for r in con.execute(
        "SELECT centre_id, SUM(reported_count), SUM(CASE WHEN reported_count IS NOT NULL THEN observed_count END), COUNT(*) "
        "FROM sessions WHERE date>=? GROUP BY centre_id", (since,))}
    for c in centres:
        oc = open_counts.get(c["id"], {})
        c["open_alerts"] = {k: oc.get(k, 0) for k in SEV_ORDER}
        c["open_alerts_total"] = sum(oc.values())
        a = agg.get(c["id"])
        c["reported_7d"] = (a[1] or 0) if a else 0
        c["observed_7d"] = (a[2] or 0) if a else 0
        c["sessions_7d"] = a[3] if a else 0
    centres.sort(key=lambda c: c["trust_score"])
    return centres


def centre_detail(con, centre_id: str) -> dict:
    c = _public_centre(get_centre(con, centre_id))
    sessions = db.rows(con.execute("SELECT * FROM sessions WHERE centre_id=? ORDER BY start DESC LIMIT 60", (centre_id,)).fetchall())
    for s in sessions:
        s["evidence_count"] = len(s.pop("evidence") or [])
    latest_infra = next((s["infrastructure"] for s in sessions if s.get("infrastructure")), [])
    alerts = list_alerts(con, centre_id=centre_id, limit=100)
    tamper = [dict(t, session_id=s["id"], date=s["date"]) for s in sessions for t in (s.get("tamper") or [])]
    chain_breaks = sum(1 for s in sessions if s["chain_ok"] == 0)
    util = defaultdict(list)
    for s in sessions[:14]:
        for it in s.get("infrastructure") or []:
            util[it["item"]].append(it.get("utilization_pct", 0))
    return {
        "centre": c,
        "sessions": sessions,
        "inventory": latest_infra,
        "utilization": {k: round(sum(v) / len(v), 1) for k, v in util.items()},
        "alerts": alerts,
        "tamper_events": tamper[:50],
        "chain": {"verified_events": sum(1 for s in sessions if s["chain_ok"] == 1), "breaks": chain_breaks,
                  "head": (c.get("chain_head") or "")[:16]},
    }


def session_detail(con, session_id: str) -> dict:
    s = db.row(con.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone())
    if not s:
        raise ServiceError(404, "Session not found")
    return s


def dashboard_summary(con) -> dict:
    centres = list_centres(con)
    today = datetime.now(timezone.utc).date()
    since7 = (today - timedelta(days=6)).isoformat()
    since14 = (today - timedelta(days=13)).isoformat()
    by_risk = defaultdict(int)
    for c in centres:
        by_risk[c["risk_level"]] += 1
    sev = defaultdict(int)
    for s, n in con.execute("SELECT severity, COUNT(*) FROM alerts WHERE status='open' GROUP BY severity"):
        sev[s] = n
    rep, obs, n_mm, n_ver = con.execute(
        "SELECT SUM(reported_count), SUM(observed_count), SUM(attendance_status='mismatch'), SUM(attendance_status IN ('ok','mismatch')) "
        "FROM sessions WHERE date>=? AND reported_count IS NOT NULL AND attendance_status IN ('ok','mismatch')", (since7,)).fetchone()
    trend = [dict(date=r[0], reported=r[1] or 0, observed=r[2] or 0, sessions=r[3]) for r in con.execute(
        "SELECT date, SUM(reported_count), SUM(CASE WHEN reported_count IS NOT NULL THEN observed_count END), COUNT(*) "
        "FROM sessions WHERE date>=? GROUP BY date ORDER BY date", (since14,))]
    tamper7 = 0
    for (t,) in con.execute("SELECT tamper FROM sessions WHERE date>=?", (since7,)):
        tamper7 += len(json.loads(t or "[]"))
    bw = con.execute("SELECT AVG(day_bytes) FROM (SELECT centre_id, date, SUM(payload_bytes) AS day_bytes FROM sessions "
                     "WHERE date>=? GROUP BY centre_id, date)", (since7,)).fetchone()[0]
    online_cut = (datetime.now(timezone.utc) - timedelta(hours=26)).isoformat(timespec="seconds")
    online = sum(1 for c in centres if (c.get("last_seen") or "") >= online_cut)
    states = defaultdict(lambda: {"centres": 0, "score_sum": 0.0, "at_risk": 0})
    for c in centres:
        st = states[c["state"]]
        st["centres"] += 1
        st["score_sum"] += c["trust_score"]
        st["at_risk"] += c["risk_level"] in ("high", "critical")
    return {
        "generated_at": now_iso(),
        "centres_total": len(centres),
        "devices_online": online,
        "avg_trust_score": round(sum(c["trust_score"] for c in centres) / max(1, len(centres)), 1),
        "centres_by_risk": {k: by_risk.get(k, 0) for k in RISK_ORDER},
        "open_alerts": {k: sev.get(k, 0) for k in SEV_ORDER},
        "attendance_7d": {"reported": rep or 0, "observed": obs or 0,
                          "overstated": max(0, (rep or 0) - (obs or 0)),
                          "mismatch_rate": round((n_mm or 0) / max(1, n_ver or 0), 3)},
        "tamper_events_7d": tamper7,
        "avg_kb_per_centre_day": round((bw or 0) / 1024, 1),
        "trend": trend,
        "states": sorted([{"state": k, "centres": v["centres"], "avg_score": round(v["score_sum"] / v["centres"], 1),
                           "at_risk": v["at_risk"]} for k, v in states.items()], key=lambda x: x["avg_score"]),
    }


CHECKS = {
    "ATTENDANCE_GAP": "Do a surprise headcount at the start and middle of a batch; compare with the biometric log.",
    "ATTENDANCE_UNVERIFIABLE": "Verify camera placement and lighting; request the batch's biometric records.",
    "EQUIPMENT_MISSING": "Physically verify sanctioned equipment against the empanelment inventory and asset tags.",
    "EQUIPMENT_IDLE": "Ask trainees to demonstrate practical work on the flagged equipment.",
    "TAMPER_COVERED": "Inspect the camera mounting; ask why the view was blocked during training hours.",
    "TAMPER_BLURRED": "Clean / refocus the lens and check for deliberate obstruction.",
    "TAMPER_SHIFTED": "Restore the approved camera angle and re-register the Golden Frame.",
    "TAMPER_FROZEN": "Inspect the NVR / cabling for devices injecting still images.",
    "TAMPER_REPLAY": "Inspect NVR wiring and recording settings for a playback device on the camera line.",
    "CHAIN_BREAK": "Seize the edge device logs; check for tampering with the local event store.",
}


def inspection_queue(con, limit: int = 25) -> list[dict]:
    out = []
    for c in list_centres(con):
        if c["risk_level"] == "low" and c["open_alerts_total"] == 0:
            continue
        types = [r[0] for r in con.execute("SELECT DISTINCT type FROM alerts WHERE centre_id=? AND status='open'", (c["id"],))]
        priority = (RISK_ORDER[c["risk_level"]] * 100 + c["trust_score"]
                    - 10 * c["open_alerts"]["critical"] - 4 * c["open_alerts"]["high"])
        out.append({
            "centre_id": c["id"], "name": c["name"], "state": c["state"], "district": c["district"],
            "trust_score": c["trust_score"], "risk_level": c["risk_level"], "open_alerts": c["open_alerts"],
            "priority": round(priority, 1),
            "reasons": [b["detail"] for b in (c.get("score_breakdown") or [])[:3]],
            "suggested_checks": [CHECKS[t] for t in sorted(set(types)) if t in CHECKS][:4],
        })
    out.sort(key=lambda x: x["priority"])
    for i, q in enumerate(out, 1):
        q["rank"] = i
    return out[:limit]


def fleet(con) -> list[dict]:
    since7 = (datetime.now(timezone.utc).date() - timedelta(days=6)).isoformat()
    stats = {r[0]: r for r in con.execute(
        "SELECT centre_id, SUM(payload_bytes), COUNT(DISTINCT date), AVG(valid_pct), COUNT(*), SUM(chain_ok=0) "
        "FROM sessions WHERE date>=? GROUP BY centre_id", (since7,))}
    out = []
    for c in db.rows(con.execute("SELECT id,name,state,bandwidth_mode,last_seen,chain_head FROM centres ORDER BY id")):
        r = stats.get(c["id"])
        health = con.execute("SELECT camera_health FROM sessions WHERE centre_id=? ORDER BY start DESC LIMIT 1", (c["id"],)).fetchone()
        out.append({
            "centre_id": c["id"], "name": c["name"], "state": c["state"], "mode": c["bandwidth_mode"],
            "last_seen": c["last_seen"], "kb_per_day": round((r[1] or 0) / 1024 / max(1, r[2] or 1), 1) if r else 0,
            "sessions_7d": r[4] if r else 0, "valid_pct": round(r[3] or 0, 1) if r else None,
            "chain_breaks_7d": (r[5] or 0) if r else 0,
            "camera_health": json.loads(health[0]) if health else None,
        })
    return out


def brief(con, centre_id: str) -> dict:
    d = centre_detail(con, centre_id)
    c = d["centre"]
    open_alerts = [a for a in d["alerts"] if a["status"] == "open"]
    verified = [s for s in d["sessions"] if s["attendance_status"] in ("ok", "mismatch")]
    mism = [s for s in verified if s["attendance_status"] == "mismatch"]
    lines = [f"Inspection brief: {c['name']} ({c['id']}), {c['district']}, {c['state']}",
             f"Trust Score {c['trust_score']:.0f}/100 ({c['risk_level']} risk). Scheme: {c['scheme']}.", ""]
    findings = []
    if mism:
        avg = sum(s["gap_pct"] for s in mism) / len(mism)
        findings.append(f"Attendance overstated in {len(mism)} of {len(verified)} verified sessions (average {avg:.0%}). "
                        f"Largest gap: {max(s['gap'] for s in mism)} trainees on {max(mism, key=lambda s: s['gap'])['date']}.")
    for it in d["inventory"]:
        if it["status"] in ("missing", "partial"):
            findings.append(f"{it['item'].replace('_', ' ').capitalize()}: {it['detected']} of {it['sanctioned']} sanctioned units visible in the latest session.")
        elif it["status"] == "idle":
            findings.append(f"{it['item'].replace('_', ' ').capitalize()} present but utilisation only {it['utilization_pct']:.0f}%.")
    tcount = defaultdict(int)
    for t in d["tamper_events"]:
        tcount[t["type"]] += 1
    for k, n in tcount.items():
        findings.append(f"{TAMPER_TEXT.get(k, ('', k))[1]}: {n} occurrence(s).")
    if d["chain"]["breaks"]:
        findings.append(f"{d['chain']['breaks']} event(s) failed hash-chain verification.")
    if not findings:
        findings.append("No compliance issues detected in the scoring window.")
    checks = [CHECKS[t] for t in sorted({a["type"] for a in open_alerts}) if t in CHECKS]
    lines += ["Findings:"] + [f"  - {f}" for f in findings] + ["", "Suggested on-site checks:"]
    lines += [f"  - {x}" for x in (checks or ["Routine inspection only."])]
    lines += ["", "Privacy: findings are based on anonymous counts and object detection. No individual was identified."]
    return {"centre_id": c["id"], "generated_at": now_iso(), "trust_score": c["trust_score"], "risk_level": c["risk_level"],
            "findings": findings, "suggested_checks": checks, "score_breakdown": c.get("score_breakdown") or [],
            "open_alert_ids": [a["id"] for a in open_alerts], "text": "\n".join(lines)}
