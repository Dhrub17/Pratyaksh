from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Detection:
    label: str            # normalised label, e.g. "person", "computer", "seating"
    raw_label: str        # label from the model, e.g. "tv", "chair"
    conf: float
    box: tuple            # (x1, y1, x2, y2) in pixels

    @property
    def center(self):
        x1, y1, x2, y2 = self.box
        return (x1 + x2) / 2, (y1 + y2) / 2

    @property
    def area(self) -> float:
        x1, y1, x2, y2 = self.box
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)


@dataclass
class TamperEvent:
    type: str              # COVERED | BLURRED | SHIFTED | FROZEN | REPLAY
    start_ts: float        # seconds from session start
    end_ts: float
    confidence: float
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "start_s": round(self.start_ts, 1),
            "duration_s": round(max(0.0, self.end_ts - self.start_ts), 1),
            "confidence": round(self.confidence, 2),
            "detail": self.detail,
        }


@dataclass
class SessionResult:
    attendance: dict
    infrastructure: list
    tamper: list
    camera_health: dict
    evidence: list = field(default_factory=list)
    flags: list = field(default_factory=list)
