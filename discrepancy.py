"""Attendance discrepancy: compare the centre's claim with what the camera observed.

The tolerance widens when the camera estimate is less certain, so low-quality footage
produces fewer false alarms rather than more. Sessions where most of the footage failed the
integrity checks are marked 'unverifiable' rather than guessed.
"""
from __future__ import annotations


def evaluate(observed: int | None, reported: int | None, confidence: float | None, valid_pct: float | None) -> dict:
    if observed is None:
        return {"status": "pending_footage", "gap": None, "gap_pct": None, "tolerance": None, "severity": None}
    if reported is None:
        return {"status": "pending_register", "gap": None, "gap_pct": None, "tolerance": None, "severity": None}
    conf = 0.5 if confidence is None else max(0.0, min(1.0, confidence))
    if valid_pct is not None and valid_pct < 50:
        return {"status": "unverifiable", "gap": reported - observed, "gap_pct": None, "tolerance": None, "severity": "medium"}
    tolerance = max(2.0, 0.10 * reported) * (1.0 + (1.0 - conf))
    gap = reported - observed
    gap_pct = gap / reported if reported > 0 else 0.0
    if gap > tolerance:
        sev = "high" if gap_pct >= 0.30 else "medium" if gap_pct >= 0.15 else "low"
        return {"status": "mismatch", "gap": gap, "gap_pct": round(gap_pct, 3), "tolerance": round(tolerance, 1), "severity": sev}
    return {"status": "ok", "gap": gap, "gap_pct": round(gap_pct, 3), "tolerance": round(tolerance, 1), "severity": None}
