"""Session pipeline: frames in -> one compact, explainable JSON event out.

    sample frame -> Integrity Guard -> detector -> presence + inventory -> event (+ evidence)

Frames that fail the integrity checks (covered, frozen, replayed, shifted, blurred) are not
counted: we never estimate attendance from footage we cannot trust, and the event records
how much of the session was trustworthy (camera_health.valid_pct).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

from . import __version__
from .detector import Detector
from .events import SCHEMA
from .geometry import scale_polygon
from .inventory import InventoryChecker
from .presence import PresenceAggregator
from .privacy import anonymise
from .tamper import TamperConfig, TamperGuard
from .uplink import MODES, encode_thumb

log = logging.getLogger(__name__)
MAX_W = 960
COLORS = {"person": (80, 220, 140), "default": (255, 180, 60), "flag": (60, 60, 240)}


def _resize(frame):
    h, w = frame.shape[:2]
    if w <= MAX_W:
        return frame
    return cv2.resize(frame, (MAX_W, int(h * MAX_W / w)), interpolation=cv2.INTER_AREA)


def load_baseline(cfg: dict, base_dir: Path):
    p = cfg.get("baseline_image")
    if not p:
        return None
    path = Path(p) if Path(p).is_absolute() else base_dir / p
    img = cv2.imread(str(path))
    if img is None:
        log.warning("Baseline image %s not found; SHIFTED and Golden-Frame checks disabled.", path)
        return None
    return _resize(img)


class SessionPipeline:
    def __init__(self, cfg: dict, base_dir: Path | str = ".", detector: Detector | None = None, mode: str = "lite"):
        self.cfg = cfg
        self.base_dir = Path(base_dir)
        self.mode = mode if mode in MODES else "lite"
        dcfg = cfg.get("detector", {})
        self.detector = detector or Detector(
            weights=dcfg.get("weights", "yolo11n.pt"), conf=dcfg.get("conf", 0.35),
            imgsz=dcfg.get("imgsz", 640), class_map=cfg.get("class_map"), force_backend=dcfg.get("backend"),
        )
        self.baseline = load_baseline(cfg, self.base_dir)

    # ------------------------------------------------------------------
    def run(self, source, session_id: str, batch_id: str = "B1", start: datetime | None = None,
            max_seconds: float | None = None, annotate_path: str | None = None, show: bool = False) -> dict:
        cap = cv2.VideoCapture(int(source) if str(source).isdigit() else str(source))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video source: {source}")
        is_file = Path(str(source)).exists()
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        if fps <= 1 or fps > 120:
            fps = 25.0
        every_s = float(self.cfg.get("sampling", {}).get("every_s", 3.0))
        step = max(1, int(round(fps * every_s)))

        tamper = TamperGuard(self.baseline, TamperConfig(**self.cfg.get("tamper", {})))
        presence = inventory = None
        writer = None
        evidence_candidates: dict[str, tuple] = {}
        count_frames: list[tuple[int, np.ndarray, list]] = []
        frame_idx, samples, valid = 0, 0, 0
        wall_start = time.time()
        ts = 0.0

        dense_step = max(1, int(round(fps / tamper.cfg.dense_fps)))
        while True:
            if is_file:
                ok = cap.grab()
                if not ok:
                    break
                is_sample = frame_idx % step == 0
                if not is_sample:
                    if frame_idx % dense_step == 0:
                        ok, f = cap.retrieve()
                        if ok:
                            tamper.observe_dense(_resize(f), frame_idx / fps)
                    frame_idx += 1
                    continue
                ok, frame = cap.retrieve()
                ts = frame_idx / fps
                frame_idx += 1
            else:  # live stream: sample by wall clock, fingerprint in between
                ok, frame = cap.read()
                if not ok:
                    break
                ts = time.time() - wall_start
                if ts < samples * every_s:
                    tamper.observe_dense(_resize(frame), ts)
                    continue
            if not ok or frame is None:
                break
            if max_seconds and ts > max_seconds:
                break

            frame = _resize(frame)
            h, w = frame.shape[:2]
            if presence is None:
                presence = PresenceAggregator(scale_polygon(self.cfg.get("roi"), w, h),
                                              self.cfg.get("presence", {}).get("sustained_ratio", 0.6))
                inventory = InventoryChecker(self.cfg.get("sanctioned_inventory", {}), self.cfg.get("zones"),
                                             self.baseline, **self.cfg.get("inventory", {}))
            samples += 1
            flags_now = tamper.check(frame, ts)
            frame_valid = not flags_now
            dets = self.detector.detect(frame) if frame_valid else []
            n = presence.update(dets, ts, frame_valid)
            inventory.update(frame, dets, frame_valid)
            if frame_valid:
                valid += 1
                if len(count_frames) < 400:
                    count_frames.append((n, frame, [d.box for d in dets if d.label == "person"]))
            for f in flags_now:
                evidence_candidates.setdefault(f, (ts, frame.copy()))

            if annotate_path or show:
                vis = self._annotate(frame, dets, n, flags_now, ts)
                if annotate_path:
                    if writer is None:
                        writer = cv2.VideoWriter(annotate_path, cv2.VideoWriter_fourcc(*"mp4v"), 4, (w, h))
                    writer.write(vis)
                if show:
                    cv2.imshow("PRATYAKSH edge", vis)
                    if cv2.waitKey(1) & 0xFF == 27:
                        break

        cap.release()
        if writer:
            writer.release()
        if show:
            cv2.destroyAllWindows()
        if presence is None:
            raise RuntimeError("No frames could be read from the source.")

        duration = ts
        att = presence.summary(samples)
        infra = inventory.summary(trainees_present=att["observed_count"] > 0)
        tamper_events = tamper.close(ts)
        health = tamper.health()
        health.update({"valid_pct": round(100 * valid / max(1, samples), 1), "samples": samples,
                       "resolution": f"{w}x{h}"})

        flags = sorted({f"TAMPER_{t['type']}" for t in tamper_events})
        flags += [f"EQUIPMENT_{i['status'].upper()}" for i in infra if i["status"] in ("missing", "partial", "idle")]
        enrolled = self.cfg.get("enrolled_batch_size")
        if enrolled and att["observed_count"] < 0.8 * enrolled:
            flags.append("LOW_PRESENCE_VS_ENROLLED")
        flags = sorted(set(flags))

        evidence = self._evidence(flags, evidence_candidates, count_frames, att)
        start = start or (datetime.now(timezone.utc) - timedelta(seconds=duration))
        event = {
            "schema": SCHEMA,
            "edge_version": __version__,
            "centre_id": self.cfg["centre_id"],
            "camera_id": self.cfg.get("camera_id", "CAM-01"),
            "session_id": session_id,
            "batch_id": batch_id,
            "window": {
                "start": start.isoformat(timespec="seconds"),
                "end": (start + timedelta(seconds=duration)).isoformat(timespec="seconds"),
                "duration_s": round(duration, 1),
            },
            "attendance": att,
            "infrastructure": infra,
            "tamper": tamper_events,
            "camera_health": health,
            "flags": flags,
            "evidence": evidence,
            "mode": self.mode,
            "detector": self.detector.backend,
            "privacy": {"faces_identified": False, "video_uploaded": False, "evidence_anonymised": True},
        }
        return event

    # ------------------------------------------------------------------
    def _evidence(self, flags, candidates, count_frames, att):
        limit = MODES[self.mode]["thumbs"]
        if limit == 0 or not flags:
            return []
        out = []
        for kind, (ts, frame) in candidates.items():
            if len(out) >= limit:
                break
            b64 = encode_thumb(anonymise(frame), self.mode)
            if b64:
                out.append({"reason": f"TAMPER_{kind}", "t_s": round(ts, 1), "jpeg_b64": b64})
        if len(out) < limit and count_frames:
            target = att["observed_count"]
            n, frame, boxes = min(count_frames, key=lambda c: abs(c[0] - target))
            b64 = encode_thumb(anonymise(frame, boxes), self.mode)
            if b64:
                out.append({"reason": "ATTENDANCE_SNAPSHOT", "count_in_frame": n, "jpeg_b64": b64})
        return out

    def _annotate(self, frame, dets, n, flags, ts):
        vis = anonymise(frame, [d.box for d in dets if d.label == "person"])
        roi = scale_polygon(self.cfg.get("roi"), vis.shape[1], vis.shape[0])
        if roi:
            cv2.polylines(vis, [np.int32(roi)], True, (200, 200, 200), 1)
        for d in dets:
            c = COLORS.get(d.label, COLORS["default"])
            x1, y1, x2, y2 = [int(v) for v in d.box]
            cv2.rectangle(vis, (x1, y1), (x2, y2), c, 2)
            cv2.putText(vis, f"{d.label} {d.conf:.2f}", (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, c, 1)
        cv2.rectangle(vis, (0, 0), (vis.shape[1], 34), (30, 20, 10), -1)
        label = f"PRATYAKSH  t={ts:6.1f}s  present={max(n, 0)}"
        cv2.putText(vis, label, (10, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (140, 255, 200), 2)
        if flags:
            cv2.putText(vis, "FLAG: " + ",".join(sorted(flags)), (vis.shape[1] - 330, 23),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLORS["flag"], 2)
        return vis
