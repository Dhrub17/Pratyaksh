"""Infrastructure compliance: is the sanctioned equipment present, and is it being used?

Two complementary signals:

* Detector counts per item class (e.g. how many computers / chairs / workbenches are visible).
  Equipment gets occluded by people, so we use the 90th percentile of per-sample counts.
* Golden-Frame zones: at empanelment the inspector marks where each heavy item sits
  (lathe, welding set, sewing machine). Every sample, that zone is compared with the baseline
  crop. This catches items that a generic detector has no class for, and it is robust because
  the camera is fixed.

"Operability" cannot be proven from video, so we report observable proxies and call them that:
* computers: screen-on heuristic (bright, textured screen region)
* any item: a person working at it, or motion inside its zone between samples
The output is a utilisation percentage, which is what monitoring units actually need.
"""
from __future__ import annotations

from collections import defaultdict

import cv2
import numpy as np

from .geometry import expand_box, iou, point_in_polygon, scale_polygon
from .types import Detection


def _screen_on(frame: np.ndarray, box) -> bool:
    x1, y1, x2, y2 = [int(v) for v in box]
    crop = frame[max(0, y1):y2, max(0, x1):x2]
    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    v = hsv[..., 2]
    return float(v.mean()) > 90 and float(v.std()) > 18


def _zone_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Normalised cross-correlation of equalised grayscale + edge maps, in [-1, 1]."""
    if a.size == 0 or b.size == 0:
        return 0.0
    a = cv2.resize(a, (96, 96))
    b = cv2.resize(b, (96, 96))
    ga, gb = cv2.equalizeHist(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)), cv2.equalizeHist(cv2.cvtColor(b, cv2.COLOR_BGR2GRAY))
    ea, eb = cv2.Canny(ga, 60, 160), cv2.Canny(gb, 60, 160)
    s1 = float(cv2.matchTemplate(ga, gb, cv2.TM_CCOEFF_NORMED)[0][0])
    s2 = float(cv2.matchTemplate(ea, eb, cv2.TM_CCOEFF_NORMED)[0][0]) if ea.any() and eb.any() else s1
    return 0.5 * s1 + 0.5 * s2


def _poly_bbox(poly):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return (min(xs), min(ys), max(xs), max(ys))


class InventoryChecker:
    def __init__(self, sanctioned: dict, zones: list | None = None, baseline: np.ndarray | None = None,
                 missing_tolerance: float = 0.1, idle_threshold: float = 0.25, zone_similarity_thr: float = 0.35):
        self.sanctioned = sanctioned            # {"computer": 20, "seating": 30, "lathe": 2}
        self.zones_cfg = zones or []            # [{"id": "lathe-1", "item": "lathe", "polygon": [[x,y]...normalised]}]
        self.baseline = baseline
        self.missing_tolerance = missing_tolerance
        self.idle_threshold = idle_threshold
        self.zone_thr = zone_similarity_thr
        self.counts = defaultdict(list)         # item -> per-sample detected counts
        self.active = defaultdict(list)         # item -> per-sample active counts
        self.zone_hits = defaultdict(lambda: [0, 0, 0])  # zone id -> [present, observed, active]
        self._prev_gray = None
        self._zones_px = None

    def _zones(self, w, h):
        if self._zones_px is None:
            self._zones_px = [dict(z, poly=scale_polygon(z["polygon"], w, h)) for z in self.zones_cfg]
        return self._zones_px

    def update(self, frame: np.ndarray, dets: list[Detection], frame_valid: bool = True) -> None:
        if not frame_valid:
            return
        h, w = frame.shape[:2]
        people = [d for d in dets if d.label == "person"]
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        motion = cv2.absdiff(gray, self._prev_gray) if self._prev_gray is not None and self._prev_gray.shape == gray.shape else None
        self._prev_gray = gray

        by_item = defaultdict(list)
        for d in dets:
            if d.label != "person" and d.label in self.sanctioned:
                by_item[d.label].append(d)

        for item in self.sanctioned:
            items = by_item.get(item, [])
            self.counts[item].append(len(items))
            n_active = 0
            for d in items:
                if item == "computer" and _screen_on(frame, d.box):
                    n_active += 1
                    continue
                zone = expand_box(d.box, 0.25, w, h)
                if any(iou(zone, p.box) > 0.05 for p in people):
                    n_active += 1
                    continue
                if motion is not None:
                    x1, y1, x2, y2 = [int(v) for v in d.box]
                    m = motion[y1:y2, x1:x2]
                    if m.size and float((m > 25).mean()) > 0.04:
                        n_active += 1
            self.active[item].append(n_active)

        if self.baseline is not None and self.zones_cfg:
            base = self.baseline if self.baseline.shape[:2] == (h, w) else cv2.resize(self.baseline, (w, h))
            for z in self._zones(w, h):
                bx = [int(v) for v in _poly_bbox(z["poly"])]
                occluded = any(point_in_polygon(p.center, z["poly"]) for p in people)
                rec = self.zone_hits[z["id"]]
                if occluded:
                    rec[2] += 1           # someone working at it counts as activity
                    continue
                rec[1] += 1
                sim = _zone_similarity(frame[bx[1]:bx[3], bx[0]:bx[2]], base[bx[1]:bx[3], bx[0]:bx[2]])
                if sim >= self.zone_thr:
                    rec[0] += 1
                if motion is not None:
                    m = motion[bx[1]:bx[3], bx[0]:bx[2]]
                    if m.size and float((m > 25).mean()) > 0.04:
                        rec[2] += 1

    def summary(self, trainees_present: bool = True) -> list[dict]:
        out = []
        zone_items = defaultdict(list)
        for z in self.zones_cfg:
            zone_items[z["item"]].append(z["id"])

        for item, sanctioned in self.sanctioned.items():
            counts = self.counts.get(item, [])
            detected = int(round(np.percentile(counts, 90))) if counts else 0
            source = "detector"
            zone_ids = zone_items.get(item, [])
            if zone_ids:
                present = 0
                for zid in zone_ids:
                    p, o, _ = self.zone_hits[zid]
                    if o == 0 or p / o >= 0.5:  # never visible unoccluded => assume present (low conf)
                        present += 1
                if detected == 0 or not counts or max(counts) == 0:
                    detected, source = present, "golden_frame"
                else:
                    detected, source = max(detected, present), "detector+golden_frame"

            act = self.active.get(item, [])
            operational = int(round(np.percentile(act, 90))) if act else 0
            ratios = [a / c for a, c in zip(act, counts) if c > 0]
            util = float(np.mean(ratios)) if ratios else 0.0
            if zone_ids:
                zr = []
                for zid in zone_ids:
                    p, o, a = self.zone_hits[zid]
                    zr.append(a / max(1, o + a))
                util = max(util, float(np.mean(zr)) if zr else 0.0)
                operational = max(operational, sum(1 for zid in zone_ids if self.zone_hits[zid][2] > 0))

            if detected < sanctioned * (1 - self.missing_tolerance):
                status = "missing" if detected < sanctioned * 0.5 else "partial"
            elif trainees_present and util < self.idle_threshold:
                status = "idle"
            else:
                status = "ok"
            out.append({
                "item": item,
                "sanctioned": sanctioned,
                "detected": min(detected, sanctioned * 3),
                "operational": min(operational, detected),
                "utilization_pct": round(util * 100, 1),
                "status": status,
                "source": source,
            })
        return out
