"""Privacy layer. Runs on-device, before anything is written to disk or sent.

Policy (see docs/PRIVACY_DESIGN.md):
* No facial recognition model exists anywhere in this codebase.
* Evidence thumbnails are only created when a flag fires, and only in FULL/LITE modes.
* Every person region is pixelated, and faces are additionally blurred as a second line of
  defence (in case the person detector missed someone).
"""
from __future__ import annotations

import cv2
import numpy as np

_face = None


def _face_detector():
    global _face
    if _face is None:
        _face = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    return _face


def pixelate(region: np.ndarray, blocks: int = 8) -> np.ndarray:
    h, w = region.shape[:2]
    if h < 2 or w < 2:
        return region
    small = cv2.resize(region, (blocks, max(1, int(blocks * h / w))), interpolation=cv2.INTER_LINEAR)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


def anonymise(frame: np.ndarray, person_boxes=()) -> np.ndarray:
    out = frame.copy()
    h, w = out.shape[:2]
    for (x1, y1, x2, y2) in person_boxes:
        x1, y1, x2, y2 = max(0, int(x1)), max(0, int(y1)), min(w, int(x2)), min(h, int(y2))
        if x2 > x1 and y2 > y1:
            out[y1:y2, x1:x2] = pixelate(out[y1:y2, x1:x2])
    gray = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    for (x, y, fw, fh) in _face_detector().detectMultiScale(gray, 1.1, 4, minSize=(16, 16)):
        roi = out[y:y + fh, x:x + fw]
        out[y:y + fh, x:x + fw] = cv2.GaussianBlur(roi, (0, 0), sigmaX=max(4, fw // 4))
    return out
