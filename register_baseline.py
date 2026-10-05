#!/usr/bin/env python3
"""Capture the Golden Frame for a camera at empanelment.

  python register_baseline.py --config config/TC-KA-001.json --source rtsp://... --at 5

Saves config/baselines/<centre>_<camera>.jpg and updates `baseline_image` in the config.
Mark item zones afterwards (normalised polygons) in the config's "zones" list, or use
--pick-zones to draw rectangles interactively (needs a display).
"""
import argparse
import json
from pathlib import Path

import cv2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--at", type=float, default=2.0, help="seconds into the video to grab")
    ap.add_argument("--pick-zones", action="store_true")
    a = ap.parse_args()
    cfg_path = Path(a.config).resolve()
    cfg = json.loads(cfg_path.read_text())
    cap = cv2.VideoCapture(int(a.source) if a.source.isdigit() else a.source)
    cap.set(cv2.CAP_PROP_POS_MSEC, a.at * 1000)
    ok, frame = cap.read()
    if not ok:
        raise SystemExit("Could not read a frame from the source")
    out_dir = cfg_path.parent / "baselines"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{cfg['centre_id']}_{cfg.get('camera_id', 'CAM-01')}.jpg"
    cv2.imwrite(str(out), frame)
    cfg["baseline_image"] = str(out.relative_to(cfg_path.parent.parent))
    if a.pick_zones:
        h, w = frame.shape[:2]
        zones = cfg.get("zones", [])
        print("Draw a box around each fixed item, press ENTER to confirm, ESC when done.")
        while True:
            r = cv2.selectROI("Mark item zone (ESC to finish)", frame, showCrosshair=False)
            if r[2] == 0 or r[3] == 0:
                break
            item = input("Item name for this zone (e.g. lathe): ").strip()
            x, y, rw, rh = r
            zones.append({"id": f"{item}-{len([z for z in zones if z['item']==item])+1}", "item": item,
                          "polygon": [[x / w, y / h], [(x + rw) / w, y / h], [(x + rw) / w, (y + rh) / h], [x / w, (y + rh) / h]]})
        cv2.destroyAllWindows()
        cfg["zones"] = zones
    cfg_path.write_text(json.dumps(cfg, indent=2))
    print(f"Saved baseline {out} and updated {cfg_path}")


if __name__ == "__main__":
    main()
