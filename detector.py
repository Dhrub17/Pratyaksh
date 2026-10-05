"""Object / person detection.

Primary backend: Ultralytics YOLO (YOLO11n by default, ~2.6M params, runs on Pi 5 + Hailo,
Jetson, or a laptop CPU at sampling rates of one frame every few seconds).

Fallback backend: OpenCV HOG people detector. It needs no downloads, so the pipeline
always runs, but it only detects people and is less accurate. Use it for smoke tests,
never for accuracy numbers.

Label normalisation: models speak in their own class names ("tv", "chair", "dining table").
The centre config maps those to scheme inventory items ("computer", "seating", "workbench"),
so a custom-trained model (e.g. with a "sewing_machine" class) drops in without code changes.
"""
from __future__ import annotations

import logging
from typing import Iterable

import cv2
import numpy as np

from .types import Detection

log = logging.getLogger(__name__)

# Sensible defaults for COCO-trained weights. Extend per trade in the centre config.
DEFAULT_CLASS_MAP: dict[str, list[str]] = {
    "person": ["person", "head"],
    "computer": ["tv", "laptop"],
    "seating": ["chair", "bench", "couch"],
    "workbench": ["dining table"],
    "keyboard": ["keyboard"],
}


class Detector:
    def __init__(
        self,
        weights: str = "yolo11n.pt",
        conf: float = 0.35,
        imgsz: int = 640,
        class_map: dict[str, list[str]] | None = None,
        force_backend: str | None = None,
    ):
        self.conf = conf
        self.imgsz = imgsz
        self.class_map = class_map or DEFAULT_CLASS_MAP
        self._reverse = {raw: norm for norm, raws in self.class_map.items() for raw in raws}
        self.backend = "none"
        self.model = None

        if force_backend != "hog":
            try:
                from ultralytics import YOLO  # type: ignore

                self.model = YOLO(weights)
                self.backend = "yolo"
                log.info("Detector: Ultralytics YOLO (%s)", weights)
            except Exception as exc:  # pragma: no cover - depends on environment
                log.warning("YOLO unavailable (%s). Falling back to OpenCV HOG (people only).", exc)

        if self.backend == "none":
            self.hog = cv2.HOGDescriptor()
            self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            self.backend = "hog"

    # ------------------------------------------------------------------
    def normalise(self, raw_label: str) -> str | None:
        return self._reverse.get(raw_label)

    def detect(self, frame: np.ndarray) -> list[Detection]:
        if self.backend == "yolo":
            return self._detect_yolo(frame)
        return self._detect_hog(frame)

    def _detect_yolo(self, frame: np.ndarray) -> list[Detection]:
        res = self.model.predict(frame, conf=self.conf, imgsz=self.imgsz, verbose=False)[0]
        names = res.names
        out: list[Detection] = []
        if res.boxes is None:
            return out
        for xyxy, conf, cls in zip(
            res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy(), res.boxes.cls.cpu().numpy()
        ):
            raw = names[int(cls)]
            norm = self.normalise(raw)
            if norm is None:
                continue
            out.append(Detection(norm, raw, float(conf), tuple(float(v) for v in xyxy)))
        return out

    def _detect_hog(self, frame: np.ndarray) -> list[Detection]:
        h, w = frame.shape[:2]
        scale = 640 / max(h, w) if max(h, w) > 640 else 1.0
        small = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale != 1.0 else frame
        rects, weights = self.hog.detectMultiScale(small, winStride=(8, 8), padding=(8, 8), scale=1.05)
        out = []
        for (x, y, rw, rh), wt in zip(rects, np.ravel(weights) if len(rects) else []):
            conf = float(min(1.0, max(0.0, wt / 2.0)))
            if conf < self.conf * 0.5:
                continue
            box = (x / scale, y / scale, (x + rw) / scale, (y + rh) / scale)
            out.append(Detection("person", "person", conf, box))
        return _nms(out, 0.45)


def _nms(dets: Iterable[Detection], thr: float) -> list[Detection]:
    from .geometry import iou

    dets = sorted(dets, key=lambda d: d.conf, reverse=True)
    keep: list[Detection] = []
    for d in dets:
        if all(iou(d.box, k.box) < thr for k in keep):
            keep.append(d)
    return keep
