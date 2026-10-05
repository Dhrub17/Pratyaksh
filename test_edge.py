"""Run: python -m pytest tests -q   (or: python tests/test_edge.py)"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from pratyaksh_edge.events import seal, verify_chain, GENESIS  # noqa: E402
from pratyaksh_edge.pipeline import SessionPipeline  # noqa: E402
from pratyaksh_edge.presence import PresenceAggregator  # noqa: E402
from pratyaksh_edge.types import Detection  # noqa: E402
from pratyaksh_edge.uplink import Outbox  # noqa: E402
from synthetic import make_classroom_video  # noqa: E402


def test_hash_chain_detects_tampering():
    evs, prev = [], GENESIS
    for i in range(5):
        e = seal({"centre_id": "X", "n": i}, prev)
        evs.append(e)
        prev = e["hash"]
    assert verify_chain(evs) == (True, -1)
    evs[2]["n"] = 99
    assert verify_chain(evs) == (False, 2)


def test_presence_counts_sustained_people():
    agg = PresenceAggregator()
    boxes = [(10 + 60 * i, 100, 50 + 60 * i, 200) for i in range(8)]
    for s in range(40):
        dets = [Detection("person", "person", 0.8, b) for b in boxes]
        if s < 5:  # two people walk in briefly for the "photo"
            dets += [Detection("person", "person", 0.8, (600, 100, 640, 200)), Detection("person", "person", 0.8, (700, 100, 740, 200))]
        agg.update(dets, s * 3.0)
    out = agg.summary(40)
    assert out["observed_count"] == 8, out
    assert out["peak_count"] == 10
    assert out["sustained_tracks"] == 8
    assert out["confidence"] > 0.7


def test_outbox_store_and_forward(tmp_path=None):
    tmp = Path(tmp_path or tempfile.mkdtemp())
    ob = Outbox(tmp / "o.db", api_url="http://127.0.0.1:9", device_key="k", mode="lite")
    a = ob.enqueue({"centre_id": "C1", "x": 1})
    b = ob.enqueue({"centre_id": "C1", "x": 2})
    assert b["prev_hash"] == a["hash"]
    st = ob.flush(timeout=0.5)  # nothing listening -> stays queued
    assert st["sent"] == 0 and st["pending"] == 2


def _run_clip(pipe, path):
    return pipe.run(str(path), session_id=path.stem)


def test_tamper_detection_on_synthetic_clips():
    tmp = Path(tempfile.mkdtemp())
    src = tmp / "honest_src.mp4"
    make_classroom_video(src, seconds=90)
    subprocess.check_call([sys.executable, str(ROOT / "tools/make_test_clips.py"), str(src), "--out", str(tmp / "clips"),
                           "--true-count", "6"], stdout=subprocess.DEVNULL)
    cap = cv2.VideoCapture(str(src))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 5)
    ok, frame = cap.read()
    (tmp / "config" / "baselines").mkdir(parents=True)
    cv2.imwrite(str(tmp / "config/baselines/base.jpg"), frame)
    cfg = json.loads((ROOT / "config/TC-KA-001.json").read_text())
    cfg.update(baseline_image="config/baselines/base.jpg", detector={"backend": "hog"}, sampling={"every_s": 2})
    pipe = SessionPipeline(cfg, base_dir=tmp, mode="lite")
    expect = {"honest": set(), "covered": {"COVERED"}, "frozen": {"FROZEN"}, "replay": {"REPLAY"},
              "shifted": {"SHIFTED"}, "deg_jpeg15": set(), "deg_360p": set()}
    got = {}
    for name in expect:
        ev = _run_clip(pipe, tmp / "clips" / f"{name}.mp4")
        got[name] = {t["type"] for t in ev["tamper"]}
        assert ev["privacy"]["faces_identified"] is False
    print(json.dumps({k: sorted(v) for k, v in got.items()}, indent=1))
    for name, exp in expect.items():
        assert exp <= got[name], (name, got[name])
        assert not (got[name] - exp - {"BLURRED"}), (name, got[name])


if __name__ == "__main__":
    for fn in [test_hash_chain_detects_tampering, test_presence_counts_sustained_people,
               test_outbox_store_and_forward, test_tamper_detection_on_synthetic_clips]:
        fn()
        print("PASS", fn.__name__)
