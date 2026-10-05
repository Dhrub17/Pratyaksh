from __future__ import annotations
import numpy as np


def iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def point_in_polygon(pt, poly) -> bool:
    """Ray casting. poly: list of [x, y] in pixels. Empty/None polygon = whole frame."""
    if not poly:
        return True
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi:
            inside = not inside
        j = i
    return inside


def scale_polygon(poly_norm, w: int, h: int):
    """Config polygons are stored normalised (0..1) so they survive resolution changes."""
    if not poly_norm:
        return None
    return [[p[0] * w, p[1] * h] for p in poly_norm]


def expand_box(box, frac: float, w: int, h: int):
    x1, y1, x2, y2 = box
    dx, dy = (x2 - x1) * frac, (y2 - y1) * frac
    return (max(0, x1 - dx), max(0, y1 - dy), min(w, x2 + dx), min(h, y2 + dy))


def robust_count(samples) -> float:
    if not samples:
        return 0.0
    return float(np.median(np.asarray(samples)))
