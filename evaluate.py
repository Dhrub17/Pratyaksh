#!/usr/bin/env python3
"""False-positive / false-negative accuracy assessment on the demonstration dataset.

  python eval/evaluate.py --config config/TC-KA-001.json --clips eval/clips --labels eval/clips/labels.json

labels.json: [{"clip": "honest.mp4", "true_count": 12, "tamper": [], "equipment": {"computer": 10},
               "degradation": null}, ...]

Reports
  * attendance: MAE, mean signed error, within-tolerance rate (|err| <= max(1, 10%))
  * tamper flags: TP/FP/FN/TN, precision, recall, F1, false-positive rate per type
  * equipment: count MAE per item (when labelled)
  * robustness: attendance error per degradation
Writes eval/report.json and eval/REPORT.md
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pratyaksh_edge.pipeline import SessionPipeline  # noqa: E402

TAMPER_TYPES = ["COVERED", "FROZEN", "REPLAY", "SHIFTED", "BLURRED"]


def prf(tp, fp, fn, tn):
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    fpr = fp / (fp + tn) if fp + tn else 0.0
    return round(p, 3), round(r, 3), round(f1, 3), round(fpr, 3)


def evaluate(results: list[dict]) -> dict:
    att = [r for r in results if r["true_count"] is not None and "ATT_SKIP" not in r]
    errs = [r["observed"] - r["true_count"] for r in att]
    within = [abs(e) <= max(1, 0.1 * r["true_count"]) for e, r in zip(errs, att)]
    out = {"n_clips": len(results), "attendance": {
        "mae": round(sum(abs(e) for e in errs) / max(1, len(errs)), 2),
        "mean_signed_error": round(sum(errs) / max(1, len(errs)), 2),
        "within_tolerance_pct": round(100 * sum(within) / max(1, len(within)), 1),
    }, "tamper": {}, "equipment": {}, "robustness": {}}
    for t in TAMPER_TYPES:
        tp = fp = fn = tn = 0
        for r in results:
            truth, pred = t in r["truth_tamper"], t in r["pred_tamper"]
            tp += truth and pred
            fp += (not truth) and pred
            fn += truth and not pred
            tn += (not truth) and not pred
        p, rc, f1, fpr = prf(tp, fp, fn, tn)
        out["tamper"][t] = {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": p, "recall": rc, "f1": f1, "fpr": fpr}
    eq_err = defaultdict(list)
    for r in results:
        for item, true_n in (r.get("equipment") or {}).items():
            eq_err[item].append(abs(r["pred_equipment"].get(item, 0) - true_n))
    out["equipment"] = {k: {"mae": round(sum(v) / len(v), 2), "n": len(v)} for k, v in eq_err.items()}
    by_deg = defaultdict(list)
    for r in att:
        by_deg[r.get("degradation") or "clean"].append(abs(r["observed"] - r["true_count"]))
    out["robustness"] = {k: round(sum(v) / len(v), 2) for k, v in by_deg.items()}
    return out


def to_markdown(rep: dict, results: list[dict]) -> str:
    a = rep["attendance"]
    md = ["# PRATYAKSH accuracy assessment", "",
          f"Clips evaluated: **{rep['n_clips']}**", "", "## Attendance estimation", "",
          "| Metric | Value |", "|---|---|",
          f"| Mean absolute error (people/session) | {a['mae']} |",
          f"| Mean signed error (+ = over-count) | {a['mean_signed_error']} |",
          f"| Sessions within tolerance (max(1, 10%)) | {a['within_tolerance_pct']}% |", "",
          "## Tamper detection (per clip)", "",
          "| Type | TP | FP | FN | TN | Precision | Recall | F1 | False-positive rate |", "|---|---|---|---|---|---|---|---|---|"]
    for t, m in rep["tamper"].items():
        md.append(f"| {t} | {m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} | {m['precision']} | {m['recall']} | {m['f1']} | {m['fpr']} |")
    md += ["", "## Robustness (attendance MAE by condition)", "", "| Condition | MAE |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in rep["robustness"].items()]
    if rep["equipment"]:
        md += ["", "## Equipment count", "", "| Item | MAE | Clips |", "|---|---|---|"]
        md += [f"| {k} | {v['mae']} | {v['n']} |" for k, v in rep["equipment"].items()]
    md += ["", "## Per-clip results", "", "| Clip | True | Observed | Confidence | Tamper truth | Tamper predicted |", "|---|---|---|---|---|---|"]
    for r in results:
        md.append(f"| {r['clip']} | {r['true_count']} | {r['observed']} | {r['confidence']} | "
                  f"{','.join(r['truth_tamper']) or '-'} | {','.join(r['pred_tamper']) or '-'} |")
    md += ["", "Notes: attendance on tampered clips is computed only from frames that passed integrity checks.",
           "Report limitations honestly (dense crowds, heavy occlusion, very dark rooms)."]
    return "\n".join(md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--clips", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent))
    a = ap.parse_args()
    cfg_path = Path(a.config).resolve()
    cfg = json.loads(cfg_path.read_text())
    pipe = SessionPipeline(cfg, base_dir=cfg_path.parent.parent, mode="ultra")
    labels = json.loads(Path(a.labels).read_text())
    results = []
    for lab in labels:
        ev = pipe.run(str(Path(a.clips) / lab["clip"]), session_id=f"eval-{lab['clip']}")
        r = {
            "clip": lab["clip"], "true_count": lab.get("true_count"), "degradation": lab.get("degradation"),
            "observed": ev["attendance"]["observed_count"], "confidence": ev["attendance"]["confidence"],
            "truth_tamper": sorted(lab.get("tamper", [])), "pred_tamper": sorted({t["type"] for t in ev["tamper"]}),
            "equipment": lab.get("equipment") or {}, "pred_equipment": {i["item"]: i["detected"] for i in ev["infrastructure"]},
        }
        print(f"{r['clip']:<20} true {r['true_count']:>3} obs {r['observed']:>3} tamper {r['pred_tamper']}")
        results.append(r)
    rep = evaluate(results)
    Path(a.out, "report.json").write_text(json.dumps({"summary": rep, "results": results}, indent=2))
    Path(a.out, "REPORT.md").write_text(to_markdown(rep, results))
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
