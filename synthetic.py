"""Synthetic classroom footage for tests (no real people, so detector counts are not meaningful;
used to verify the integrity checks, hashing and plumbing end to end)."""
import cv2
import numpy as np


def make_classroom_video(path, seconds=60, fps=10, w=640, h=360, seed=1):
    rng = np.random.default_rng(seed)
    bg = np.full((h, w, 3), 170, np.uint8)
    for _ in range(60):  # desks, posters, windows: texture for ORB
        x, y = int(rng.integers(0, w - 60)), int(rng.integers(0, h - 40))
        cv2.rectangle(bg, (x, y), (x + int(rng.integers(20, 80)), y + int(rng.integers(15, 50))),
                      tuple(int(c) for c in rng.integers(40, 230, 3)), -1)
    cv2.putText(bg, "SKILL CENTRE LAB 2", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (30, 30, 30), 2)
    movers = [dict(x=float(rng.integers(50, w - 50)), y=float(rng.integers(120, h - 60)),
                   vx=float(rng.normal(0, 3)), vy=float(rng.normal(0, 1.5))) for _ in range(6)]
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for _ in range(seconds * fps):
        f = bg.copy()
        for m in movers:
            m["x"] = (m["x"] + m["vx"]) % (w - 40)
            m["y"] = min(max(100, m["y"] + m["vy"]), h - 50)
            cv2.ellipse(f, (int(m["x"]), int(m["y"])), (14, 28), 0, 0, 360, (60, 40, 30), -1)
        noise = rng.normal(0, 3, f.shape)
        vw.write(np.clip(f.astype(np.float32) + noise, 0, 255).astype(np.uint8))
    vw.release()
