#!/usr/bin/env python3
"""Turn one honest recording into a labelled test set for the accuracy assessment.

  python tools/make_test_clips.py demo/classroom.mp4 --out eval/clips --true-count 12

Creates:
  honest.mp4                  unchanged (control)
  covered.mp4                 lens covered for the middle third
  frozen.mp4                  stream frozen on one frame for the middle third
  replay.mp4                  first 30% of footage looped back in later (replay attack)
  shifted.mp4                 camera rotated/translated away for the second half
  deg_360p.mp4                downscaled to 360p (rural camera)
  deg_jpeg15.mp4              heavy compression artefacts
  deg_lowlight.mp4            exposure reduced (evening / poor lighting)
and writes labels.json describing the ground truth for each clip.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def read_all(path, max_frames=6000):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    frames = []
    while len(frames) < max_frames:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    return frames, fps


def write(path, frames, fps):
    h, w = frames[0].shape[:2]
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for f in frames:
        if f.shape[:2] != (h, w):
            f = cv2.resize(f, (w, h))
        vw.write(f)
    vw.release()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--out", default="eval/clips")
    ap.add_argument("--true-count", type=int, required=True, help="people actually present (count it yourself)")
    ap.add_argument("--equipment", default="{}", help='JSON, e.g. {"computer": 10}')
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    frames, fps = read_all(a.video)
    n = len(frames)
    if n < 60:
        raise SystemExit("Need at least a few seconds of video")
    eq = json.loads(a.equipment)
    labels = []

    def add(name, fr, tamper=None, count=a.true_count, degr=None):
        write(out / f"{name}.mp4", fr, fps)
        labels.append({"clip": f"{name}.mp4", "true_count": count, "tamper": tamper or [],
                       "equipment": eq, "degradation": degr})

    add("honest", frames)
    t1, t2 = n // 3, 2 * n // 3
    rng = np.random.default_rng(7)
    covered = [f if not (t1 <= i < t2) else np.clip(rng.normal(8, 2, f.shape), 0, 255).astype(np.uint8)
               for i, f in enumerate(frames)]
    add("covered", covered, ["COVERED"])
    add("frozen", [f if not (t1 <= i < t2) else frames[t1] for i, f in enumerate(frames)], ["FROZEN"])
    seg = frames[: int(n * 0.3)]
    add("replay", frames[: int(n * 0.5)] + seg + frames[int(n * 0.5):int(n * 0.7)], ["REPLAY"])
    h, w = frames[0].shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), 25, 1.3)
    M[0, 2] += w * 0.25
    add("shifted", [f if i < n // 2 else cv2.warpAffine(f, M, (w, h)) for i, f in enumerate(frames)], ["SHIFTED"])
    add("deg_360p", [cv2.resize(cv2.resize(f, (int(w * 360 / h), 360)), (w, h)) for f in frames], degr="360p")
    add("deg_jpeg15", [cv2.imdecode(cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 15])[1], 1) for f in frames], degr="jpeg_q15")
    add("deg_lowlight", [cv2.convertScaleAbs(f, alpha=0.35, beta=0) for f in frames], degr="low_light")
    (out / "labels.json").write_text(json.dumps(labels, indent=2))
    print(f"Wrote {len(labels)} clips + labels.json to {out}")


if __name__ == "__main__":
    main()
