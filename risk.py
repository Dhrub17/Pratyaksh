"""Centre Trust Score (0-100): an explainable, rolling risk score.

Every point deducted is tied to a named factor with a plain-language reason, so a monitoring
officer (or the centre itself) can see exactly why a score is low. Weights are deliberately
simple and documented so they can be tuned by the scheme, not hidden in a model.

  Factor                      Max penalty  Signal
  attendance_overstatement    40           average % by which register exceeds observed count
  mismatch_frequency          20           share of sessions flagged as mismatched
  missing_equipment           30           worst-affected item: share of its sanctioned units not visible
  idle_equipment               5           share of items with low utilisation
  camera_integrity            15           tamper events (covered, frozen, replay, shifted)
  log_integrity               10           broken hash chain (edited / deleted events)
  reporting_gaps               5           unverifiable sessions, registers never submitted
  device_offline              10           no events for more than 48 hours (store-and-forward backlog)

Integrity override: deliberate tampering (replayed or frozen footage, broken hash chain) caps
the score at 55, so such a centre is always at least "high" risk no matter how clean the rest
of its data looks. Clean-looking numbers from a manipulated feed are not evidence of compliance.
"""
from __future__ import annotations

from statistics import mean

WEIGHTS = {
    "attendance_overstatement": 40,
    "mismatch_frequency": 20,
    "missing_equipment": 30,
    "idle_equipment": 5,
    "camera_integrity": 15,
    "log_integrity": 10,
    "reporting_gaps": 5,
    "device_offline": 10,
}

LABELS = {
    "attendance_overstatement": "Attendance overstatement",
    "mismatch_frequency": "Frequent mismatches",
    "missing_equipment": "Missing equipment",
    "idle_equipment": "Idle equipment",
    "camera_integrity": "Camera tampering",
    "log_integrity": "Event log integrity",
    "reporting_gaps": "Reporting gaps",
    "integrity_override": "Integrity override",
    "device_offline": "Device offline",
}
INTEGRITY_CAP = 55.0


def risk_level(score: float) -> str:
    if score >= 80:
        return "low"
    if score >= 60:
        return "medium"
    if score >= 40:
        return "high"
    return "critical"


def compute(sessions: list[dict], silent_hours: float | None = None) -> tuple[float, str, list[dict]]:
    """sessions: rows from the scoring window, newest last. silent_hours: time since the device last reported."""
    br = []
    if silent_hours is not None and silent_hours > 48:
        br.append(_f("device_offline", min(1.0, silent_hours / 168), f"no events received for {silent_hours / 24:.1f} days"))
    if not sessions:
        score = round(100.0 - sum(b["penalty"] for b in br), 1)
        return score, risk_level(score), br

    verified = [s for s in sessions if s.get("attendance_status") in ("ok", "mismatch")]
    over = [max(0.0, s["gap_pct"] or 0.0) if s["attendance_status"] == "mismatch" else 0.0 for s in verified]
    if over and max(over) > 0:
        mism_only = [o for o in over if o > 0]
        avg_over = mean(over)
        frac = min(1.0, avg_over * 2.5)        # 40% average overstatement => full penalty
        br.append(_f("attendance_overstatement", frac,
                     f"register exceeds camera count by {mean(mism_only):.0%} in flagged sessions ({avg_over:.0%} across all)"))
    if verified:
        mm = sum(1 for s in verified if s["attendance_status"] == "mismatch") / len(verified)
        br.append(_f("mismatch_frequency", mm, f"{mm:.0%} of verified sessions mismatched"))

    recent = sessions[-6:]
    miss_fracs, idle_fracs = [], []
    for s in recent:
        items = s.get("infrastructure") or []
        fr = [max(0, i["sanctioned"] - i.get("detected", 0)) / i["sanctioned"]
              for i in items if i.get("sanctioned") and i.get("status") in ("missing", "partial")]
        if items:
            miss_fracs.append(max(fr) if fr else 0.0)
        if items:
            idle_fracs.append(sum(1 for i in items if i.get("status") == "idle") / len(items))
    if miss_fracs:
        mf = mean(miss_fracs)
        if mf > 0:
            worst = max(((i["item"], i["sanctioned"] - i.get("detected", 0), i["sanctioned"]) for i in recent[-1].get("infrastructure") or []
                         if i.get("status") in ("missing", "partial")), key=lambda x: x[1] / x[2], default=None)
            what = f"; latest: {worst[1]} of {worst[2]} {worst[0].replace('_', ' ')} not visible" if worst else ""
            br.append(_f("missing_equipment", min(1.0, mf * 2), f"up to {mf:.0%} of an item's sanctioned units missing recently{what}"))
    if idle_fracs:
        idf = mean(idle_fracs)
        br.append(_f("idle_equipment", idf, f"{idf:.0%} of item types rarely used"))

    tamper = [t for s in sessions for t in (s.get("tamper") or [])]
    if tamper:
        sev = sum(2 if t["type"] in ("REPLAY", "FROZEN") else 1 for t in tamper)
        kinds = sorted({t["type"].lower() for t in tamper})
        br.append(_f("camera_integrity", min(1.0, sev / 4), f"{len(tamper)} tamper event(s): {', '.join(kinds)}"))
    breaks = sum(1 for s in sessions if s.get("chain_ok") == 0)
    if breaks:
        br.append(_f("log_integrity", min(1.0, breaks / 2), f"{breaks} event(s) failed hash-chain verification"))
    gaps = sum(1 for s in sessions if s.get("attendance_status") in ("unverifiable", "pending_register"))
    if gaps:
        g = gaps / len(sessions)
        br.append(_f("reporting_gaps", g, f"{gaps} session(s) unverifiable or without a register"))

    br = [b for b in br if b["penalty"] > 0.05]
    br.sort(key=lambda b: b["penalty"], reverse=True)
    score = round(max(0.0, 100.0 - sum(b["penalty"] for b in br)), 1)
    deliberate = [t["type"].lower() for t in tamper if t["type"] in ("REPLAY", "FROZEN")] + (["hash-chain break"] if breaks else [])
    if deliberate and score > INTEGRITY_CAP:
        br.insert(0, {"factor": "integrity_override", "label": LABELS["integrity_override"], "penalty": round(score - INTEGRITY_CAP, 1),
                      "max": None, "detail": f"deliberate manipulation detected ({', '.join(sorted(set(deliberate)))}): score capped at {INTEGRITY_CAP:.0f}"})
        score = INTEGRITY_CAP
    return score, risk_level(score), br


def _f(key: str, frac: float, detail: str) -> dict:
    frac = max(0.0, min(1.0, frac))
    return {"factor": key, "label": LABELS[key], "penalty": round(WEIGHTS[key] * frac, 1),
            "max": WEIGHTS[key], "detail": detail}
