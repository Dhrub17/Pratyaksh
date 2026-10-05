"""Integrity Guard: detects attempts to defeat the camera.

COVERED  lens covered / camera in darkness       (very low brightness and contrast)
BLURRED  lens smeared, defocused, obstructed      (very low Laplacian variance)
SHIFTED  camera pointed away from the classroom   (ORB feature match vs Golden Frame fails)
FROZEN   still image injected / stream frozen     (consecutive samples are pixel-identical;
                                                    a live sensor always has noise)
REPLAY   old footage looped into the camera line  (a *dynamic* stretch of frames reappears
                                                    later with near-identical pixels, i.e.
                                                    the same sensor noise, which never
                                                    happens with a live camera)

All checks are cheap (tens of milliseconds on a Raspberry Pi) and run on the sampled frames.
Thresholds live in the centre config so they can be calibrated per camera.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .types import TamperEvent


@dataclass
class TamperConfig:
    dark_brightness: float = 28.0
    dark_contrast: float = 10.0
    blur_laplacian: float = 12.0
    shift_min_inlier_ratio: float = 0.18
    shift_check_every: int = 5
    frozen_mad: float = 0.25          # mean abs diff (0-255) on a 64x64 thumbnail
    frozen_min_samples: int = 3
    replay_match_mad: float = 2.5     # 32x32 fingerprint distance for "same frame"
    replay_dynamic_mad: float = 2.0   # the matched stretch must itself contain motion
    replay_min_run: int = 3           # consecutive samples with a consistent time offset
    replay_min_gap_s: float = 15.0    # only look for matches older than this
    replay_offset_tol_s: float = 0.6
    dense_fps: float = 10.0           # fingerprint rate (cheap 32x32 thumbnails)
    dense_window_s: float = 5400.0


class TamperGuard:
    def __init__(self, baseline: np.ndarray | None = None, cfg: TamperConfig | None = None):
        self.cfg = cfg or TamperConfig()
        self.baseline = baseline
        self._orb = cv2.ORB_create(800)
        self._bfm = cv2.BFMatcher(cv2.NORM_HAMMING)
        self._base_kp = self._base_des = None
        if baseline is not None:
            g = cv2.cvtColor(baseline, cv2.COLOR_BGR2GRAY)
            self._base_kp, self._base_des = self._orb.detectAndCompute(g, None)
            self._base_shape = g.shape
        self.events: list[TamperEvent] = []
        self._open: dict[str, TamperEvent] = {}
        self._thumbs: list[np.ndarray] = []
        self._ts: list[float] = []
        self._fp: list[np.ndarray] = []      # dense fingerprints (uint8 32x32 flattened)
        self._fp_ts: list[float] = []
        self._fp_mat = None
        self._offsets: list = []             # per sample: matched time offset or None
        self._last_sample_fp = None
        self._frozen_run = 0
        self._n = 0
        self.last_quality = {"brightness": 0.0, "contrast": 0.0, "sharpness": 0.0}
        self._q_hist = []

    # --------------------------------------------------------------
    def _set(self, kind: str, active: bool, ts: float, conf: float, detail: str = "") -> None:
        if active:
            ev = self._open.get(kind)
            if ev is None:
                self._open[kind] = TamperEvent(kind, ts, ts, conf, detail)
            else:
                ev.end_ts, ev.confidence = ts, max(ev.confidence, conf)
        elif kind in self._open:
            self.events.append(self._open.pop(kind))

    def check(self, frame: np.ndarray, ts: float) -> set[str]:
        """Returns the set of active tamper states for this frame."""
        self._n += 1
        cfg = self.cfg
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        bright, contrast = float(gray.mean()), float(gray.std())
        sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        self.last_quality = {"brightness": bright, "contrast": contrast, "sharpness": sharp}
        self._q_hist.append((bright, contrast, sharp))
        active: set[str] = set()

        covered = (bright < cfg.dark_brightness and contrast < cfg.dark_contrast * 2) or contrast < cfg.dark_contrast * 0.5
        self._set("COVERED", covered, ts, 0.95 if covered else 0)
        if covered:
            active.add("COVERED")
        blurred = (not covered) and sharp < cfg.blur_laplacian
        self._set("BLURRED", blurred, ts, 0.8)
        if blurred:
            active.add("BLURRED")

        # Frozen / replay operate on tiny thumbnails (cheap, and robust to compression).
        thumb = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA).astype(np.float32)
        frozen = False
        if self._thumbs:
            mad = float(np.abs(thumb - self._thumbs[-1]).mean())
            self._frozen_run = self._frozen_run + 1 if mad < cfg.frozen_mad else 0
            frozen = self._frozen_run + 1 >= cfg.frozen_min_samples and not covered
        self._set("FROZEN", frozen, ts, 0.9, "identical frames: no sensor noise")
        if frozen:
            active.add("FROZEN")

        self._thumbs.append(thumb)
        self._ts.append(ts)
        if len(self._thumbs) > 8:
            self._thumbs.pop(0)
            self._ts.pop(0)
        replay = None if (frozen or covered) else self._replay_check(gray, ts)
        self._set("REPLAY", bool(replay), ts, 0.85, replay or "")
        if replay:
            active.add("REPLAY")

        if self._base_des is not None and not covered and self._n % cfg.shift_check_every == 1:
            shifted, ratio = self._shift_check(gray)
            self._set("SHIFTED", shifted, ts, 0.8, f"baseline match {ratio:.0%}")
        if "SHIFTED" in self._open:
            active.add("SHIFTED")
        return active

    @staticmethod
    def fingerprint(gray: np.ndarray) -> np.ndarray:
        return cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).reshape(-1)

    def observe_dense(self, frame_or_gray: np.ndarray, ts: float) -> None:
        """Called for frames between samples (~10 fps). Keeps a cheap fingerprint history so
        replayed footage is found even when sampling phase differs from the original."""
        g = frame_or_gray if frame_or_gray.ndim == 2 else cv2.cvtColor(frame_or_gray, cv2.COLOR_BGR2GRAY)
        if self._fp_ts and ts - self._fp_ts[-1] < 1.0 / self.cfg.dense_fps - 1e-6:
            return
        self._fp.append(self.fingerprint(g))
        self._fp_ts.append(ts)
        self._fp_mat = None
        while self._fp_ts and ts - self._fp_ts[0] > self.cfg.dense_window_s:
            self._fp.pop(0)
            self._fp_ts.pop(0)

    def _replay_check(self, gray, ts):
        cfg = self.cfg
        fp = self.fingerprint(gray).astype(np.int16)
        self.observe_dense(gray, ts)
        dynamic = self._last_sample_fp is not None and float(np.abs(fp - self._last_sample_fp).mean()) >= cfg.replay_dynamic_mad
        self._last_sample_fp = fp
        old = [i for i, t in enumerate(self._fp_ts) if ts - t >= cfg.replay_min_gap_s]
        offset = None
        if dynamic and old:
            if self._fp_mat is None:
                self._fp_mat = np.asarray(self._fp, dtype=np.int16)
            mat = self._fp_mat[: old[-1] + 1]
            d = np.abs(mat - fp).mean(axis=1)
            j = int(np.argmin(d))
            if float(d[j]) <= cfg.replay_match_mad:
                offset = ts - self._fp_ts[j]
        self._offsets.append(offset)
        recent = self._offsets[-cfg.replay_min_run:]
        if len(recent) == cfg.replay_min_run and all(o is not None for o in recent):
            if max(recent) - min(recent) <= cfg.replay_offset_tol_s:
                return f"footage from ~{recent[-1]:.0f}s earlier is being replayed"
        return None

    def _shift_check(self, gray):
        if gray.shape != self._base_shape:
            gray = cv2.resize(gray, (self._base_shape[1], self._base_shape[0]))
        kp, des = self._orb.detectAndCompute(gray, None)
        if des is None or len(kp) < 20 or len(self._base_kp) < 20:
            return False, 1.0
        matches = self._bfm.knnMatch(self._base_des, des, k=2)
        good = [m for m, *rest in matches if rest and m.distance < 0.75 * rest[0].distance]
        if len(good) < 8:
            return True, 0.0
        src = np.float32([self._base_kp[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([kp[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
        ratio = float(mask.sum()) / max(1, len(self._base_kp)) if mask is not None else 0.0
        if H is not None:
            # large translation of the image centre = camera moved
            c = np.array([[[self._base_shape[1] / 2, self._base_shape[0] / 2]]], dtype=np.float32)
            moved = cv2.perspectiveTransform(c, H)[0][0] - c[0][0]
            if np.hypot(*moved) > 0.15 * self._base_shape[1]:
                return True, ratio
        return ratio < self.cfg.shift_min_inlier_ratio, ratio

    # --------------------------------------------------------------
    def close(self, ts: float) -> list[dict]:
        for k in list(self._open):
            ev = self._open.pop(k)
            ev.end_ts = ts
            self.events.append(ev)
        return [e.to_dict() for e in sorted(self.events, key=lambda e: e.start_ts)]

    def health(self) -> dict:
        if not self._q_hist:
            return {"brightness": 0, "contrast": 0, "sharpness": 0}
        q = np.asarray(self._q_hist)
        return {
            "brightness": round(float(np.median(q[:, 0])), 1),
            "contrast": round(float(np.median(q[:, 1])), 1),
            "sharpness": round(float(np.median(q[:, 2])), 1),
        }
