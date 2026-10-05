# Accuracy assessment method

The problem statement asks for a false-positive / false-negative assessment on the demonstration dataset. This is how to produce numbers you can defend in front of judges.

## 1. Build the dataset

Record 5–10 clips of 3–5 minutes each (see `edge/demo/README.md`). Vary:
- number of people (5, 10, 20+), seating density, people arriving late / leaving early
- lighting (daylight, tube light, evening)
- camera height and angle

For each clip, write down the true number of people present for most of the session and the number of each equipment item visible.

## 2. Generate tampered and degraded variants

```bash
python tools/make_test_clips.py demo/clip1.mp4 --out eval/clips_clip1 --true-count 12 --equipment '{"computer": 10}'
```

Each source clip becomes 8 labelled clips: honest, covered, frozen, replay, shifted, 360p, JPEG quality 15, low light.

## 3. Run the evaluation

```bash
python eval/evaluate.py --config config/TC-KA-001.json --clips eval/clips_clip1 --labels eval/clips_clip1/labels.json
```

Merge several `labels.json` files if you want one combined report.

## 4. Metrics reported

| Metric | Meaning | Why it matters |
|---|---|---|
| Attendance MAE | Average absolute difference between camera count and true count | Size of a typical counting error |
| Mean signed error | Positive = over-counting | Under-counting would create false fraud alerts, so check the sign |
| Within tolerance | Share of sessions within max(1 person, 10%) | Matches the backend's alert tolerance |
| Tamper precision / recall / F1 | Per tamper type, over all clips | Recall = attacks caught; precision = alarms that were real |
| False-positive rate | Honest clips wrongly flagged | The number monitoring units care about most |
| Robustness MAE | Attendance error per degradation | Shows behaviour on rural-quality cameras |

## 5. How alert-level false positives are controlled

Even with a perfect counter, a raw mismatch alert would be noisy. The backend only raises an attendance alert when the gap exceeds a tolerance of max(2 people, 10% of the claim), and the tolerance widens as camera confidence drops (`backend/app/services/discrepancy.py`). Sessions where under half of the footage was usable are marked *unverifiable*, not mismatched. Report both the raw counting error and the alert-level false-positive rate.

## 6. Results table template for the PPT

| Condition | Clips | Attendance MAE | Within tolerance | Tamper recall | Honest-clip false alarms |
|---|---|---|---|---|---|
| Clean 720p | | | | | |
| 360p | | | | | |
| Heavy compression | | | | | |
| Low light | | | | | |

Our automated tests on synthetic footage detect all four tamper attacks (covered, frozen, replayed, shifted) with no false alarms on the honest, 360p and compressed control clips. Synthetic footage says nothing about counting accuracy on real people, so fill this table from your own recordings.
