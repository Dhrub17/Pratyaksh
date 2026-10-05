"""Anonymous presence estimation.

Why not just count people in one frame? A single snapshot is easy to game (people walk in
for the photo) and noisy (occlusion, someone bending down). We sample the session every
few seconds and combine two independent estimates:

1. Robust per-sample count: the median of head/person counts across the session core.
2. Sustained tracks: anonymous track IDs that were visible for at least `sustained_ratio`
   of the session. Track IDs are random integers, reset every session, and never linked
   to faces or identities.

The reported `observed_count` is the median-based estimate; the sustained-track count is
exposed as a cross-check, and their agreement feeds the confidence score.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .geometry import iou, point_in_polygon
from .types import Detection


@dataclass
class Track:
    tid: int
    box: tuple
    hits: int = 1
    misses: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0
    confs: list = field(default_factory=list)


class IoUTracker:
    """Small greedy IoU tracker (SORT-style without a Kalman filter).

    Trainees in a classroom are mostly seated, so displacement between samples a few
    seconds apart is small and IoU association works well. If `supervision` is installed
    you can swap in ByteTrack; the interface is the same (update -> list of tracks).
    """

    def __init__(self, iou_thr: float = 0.25, max_misses: int = 4):
        self.iou_thr = iou_thr
        self.max_misses = max_misses
        self.tracks: list[Track] = []
        self.finished: list[Track] = []
        self._next = 1

    def update(self, dets: list[Detection], ts: float) -> list[Track]:
        unmatched = list(range(len(dets)))
        pairs = []
        for ti, t in enumerate(self.tracks):
            for di in unmatched:
                pairs.append((iou(t.box, dets[di].box), ti, di))
        pairs.sort(reverse=True)
        used_t, used_d = set(), set()
        for score, ti, di in pairs:
            if score < self.iou_thr or ti in used_t or di in used_d:
                continue
            t = self.tracks[ti]
            t.box, t.hits, t.misses, t.last_seen = dets[di].box, t.hits + 1, 0, ts
            t.confs.append(dets[di].conf)
            used_t.add(ti)
            used_d.add(di)
        for ti, t in enumerate(self.tracks):
            if ti not in used_t:
                t.misses += 1
        for di in range(len(dets)):
            if di not in used_d:
                self.tracks.append(Track(self._next, dets[di].box, first_seen=ts, last_seen=ts, confs=[dets[di].conf]))
                self._next += 1
        alive = []
        for t in self.tracks:
            (alive if t.misses <= self.max_misses else self.finished).append(t)
        self.tracks = alive
        return [t for t in self.tracks if t.misses == 0]

    def all_tracks(self) -> list[Track]:
        return self.finished + self.tracks


class PresenceAggregator:
    def __init__(self, roi=None, sustained_ratio: float = 0.6, trim_frac: float = 0.1):
        self.roi = roi                       # polygon in pixels, None = whole frame
        self.sustained_ratio = sustained_ratio
        self.trim_frac = trim_frac           # ignore arrival/departure edges of the session
        self.tracker = IoUTracker()
        self.samples: list[tuple[float, int]] = []
        self.confs: list[float] = []
        self.valid_samples = 0

    def update(self, dets: list[Detection], ts: float, frame_valid: bool = True) -> int:
        """frame_valid=False when the frame is covered/frozen: we do not count it."""
        if not frame_valid:
            return -1
        people = [d for d in dets if d.label == "person" and point_in_polygon(d.center, self.roi)]
        self.tracker.update(people, ts)
        self.samples.append((ts, len(people)))
        self.confs.extend(d.conf for d in people)
        self.valid_samples += 1
        return len(people)

    def summary(self, total_samples: int) -> dict:
        if not self.samples:
            return {
                "observed_count": 0, "peak_count": 0, "median_count": 0.0, "sustained_tracks": 0,
                "confidence": 0.0, "samples": 0, "coverage_pct": 0.0, "timeline": [],
            }
        counts = [c for _, c in self.samples]
        n = len(counts)
        k = int(n * self.trim_frac)
        core = counts[k: n - k] if n - 2 * k >= 3 else counts
        median = float(np.median(core))
        peak = int(max(counts))
        span = (self.samples[-1][0] - self.samples[0][0]) or 1.0
        sustained = 0
        for t in self.tracker.all_tracks():
            if (t.last_seen - t.first_seen) / span >= self.sustained_ratio and t.hits >= 3:
                sustained += 1

        # Confidence: detector certainty x count stability x sampling coverage x agreement.
        det_conf = float(np.mean(self.confs)) if self.confs else 0.5
        stability = 1.0 - min(1.0, float(np.std(core)) / (median + 1.0))
        coverage = self.valid_samples / max(1, total_samples)
        agreement = 1.0 - min(1.0, abs(sustained - median) / (median + 2.0))
        confidence = 0.35 * det_conf + 0.25 * stability + 0.25 * coverage + 0.15 * agreement

        # Downsample timeline to <= 24 points to keep the event payload tiny.
        step = max(1, n // 24)
        timeline = [int(round(np.median(counts[i:i + step]))) for i in range(0, n, step)][:24]
        return {
            "observed_count": int(round(median)),
            "peak_count": peak,
            "median_count": round(median, 1),
            "sustained_tracks": sustained,
            "confidence": round(float(np.clip(confidence, 0, 1)), 2),
            "samples": n,
            "coverage_pct": round(coverage * 100, 1),
            "timeline": timeline,
        }
