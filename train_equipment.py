#!/usr/bin/env python3
"""Fine-tune a YOLO detector on trade-specific equipment (sewing machines, lathes, welding sets...).

1. Collect 300-800 frames from real or staged centre cameras (vary lighting, angles, occlusion).
2. Label boxes in Roboflow / CVAT / Label Studio and export in YOLO format, e.g.
     datasets/workshop/{images,labels}/{train,val}
3. Edit data.example.yaml, then:
     python training/train_equipment.py --data training/data.example.yaml --epochs 80
4. Point the centre config at the result:  "detector": {"weights": "models/workshop_v1.pt"}
   and map class names in "class_map" (e.g. "lathe": ["lathe"]).

Also export ONNX for edge accelerators:  --export onnx
"""
import argparse
import shutil
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--base", default="yolo11n.pt", help="start from COCO weights (keeps 'person')")
    ap.add_argument("--epochs", type=int, default=80)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--name", default="workshop_v1")
    ap.add_argument("--export", default=None, choices=[None, "onnx", "openvino", "engine"])
    a = ap.parse_args()
    from ultralytics import YOLO

    model = YOLO(a.base)
    model.train(data=a.data, epochs=a.epochs, imgsz=a.imgsz, name=a.name,
                # augmentations that mimic rural CCTV: blur, low light, compression handled by hsv/scale/mosaic
                hsv_v=0.5, degrees=5, scale=0.4, mosaic=1.0, patience=20)
    best = Path(model.trainer.save_dir) / "weights" / "best.pt"
    out = Path(__file__).resolve().parents[1] / "models" / f"{a.name}.pt"
    out.parent.mkdir(exist_ok=True)
    shutil.copy(best, out)
    print(f"Saved {out}")
    metrics = YOLO(str(out)).val(data=a.data)
    print(f"mAP50: {metrics.box.map50:.3f}  mAP50-95: {metrics.box.map:.3f}")
    if a.export:
        print("Exported:", YOLO(str(out)).export(format=a.export))


if __name__ == "__main__":
    main()
