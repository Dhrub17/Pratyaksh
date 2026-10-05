# PRATYAKSH privacy design note

**Principle: privacy by architecture, not by policy.** The system is built so that it *cannot* identify trainees in normal operation, rather than promising not to.

## What is and isn't identified

| Compliance check | Method | Identifies an individual? |
|---|---|---|
| Headcount | Head / person detection; only the number is kept | No |
| Sustained presence | Anonymous track numbers (1, 2, 3…) that reset every session and are never stored | No |
| Equipment presence | Object detection and comparison with the empanelment "Golden Frame" | Not applicable |
| Equipment use | Motion inside the item's zone, screen-on check, a person near the item | No |
| Camera tampering | Brightness, sharpness, feature matching, 32×32 frame fingerprints | Not applicable |
| Evidence thumbnails | Created only when a flag fires; every detected person is pixelated and faces are blurred on the device before encoding | No |
| Individual verification | Not done by PRATYAKSH. If a case is escalated, the officer uses the scheme's existing biometric attendance records | Only by exception, with a human in the loop |

## Data flow

1. Video is read from the centre's NVR/camera by the edge box **inside the centre**.
2. Frames are analysed in memory. Raw frames are never written to disk by PRATYAKSH.
3. One JSON event per session (about 1–3 KB) leaves the centre. It contains counts, item statuses, tamper events and camera-health numbers.
4. In `full` and `lite` modes, a flagged session may include 1–3 anonymised thumbnails (240–320 px). In `ultra` mode no image ever leaves the centre.

## Safeguards in the code

- No face-recognition or re-identification model is included or downloadable by the pipeline.
- `edge/pratyaksh_edge/privacy.py` pixelates person boxes and blurs any face found by a second, independent detector, so a missed person box is still covered.
- Every event declares `"privacy": {"faces_identified": false, "video_uploaded": false, "evidence_anonymised": true}`. The backend rejects any event that claims otherwise (HTTP 422).
- Track IDs are random integers scoped to one session and are not sent to the server.

## Retention and access

- Session events: kept for the scheme's audit period.
- Evidence thumbnails: deleted after 30 days (`PRATYAKSH_EVIDENCE_RETENTION_DAYS`) unless linked to an open case.
- In production, dashboard access should be role-based (state monitoring unit, inspector, ministry) and every alert action should record the officer who took it. The prototype records the status and a note.

## Alignment with the Digital Personal Data Protection Act, 2023

- **Purpose limitation:** data is used only to verify scheme compliance.
- **Data minimisation:** counts instead of identities; events instead of video.
- **Storage limitation:** short retention for images.
- **Transparency:** centres display a notice that cameras are used for anonymous compliance monitoring; trainees are informed at enrolment.

## What we are honest about

A pixelated thumbnail of a small classroom could still let someone who knows the room guess who was present. That is why `ultra` mode exists, why thumbnails are created only on flags, and why they expire.
