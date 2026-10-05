#!/usr/bin/env python3
"""PRATYAKSH edge runner.

Examples
  # analyse a recorded session and send the event to the backend
  python run_edge.py --config config/TC-KA-001.json --source demo/classroom.mp4 \
      --api http://localhost:8000 --reported 30 --annotate out/annotated.mp4

  # live RTSP camera, 60-minute sessions, ultra-low-bandwidth mode
  python run_edge.py --config config/TC-KA-001.json --source rtsp://user:pass@192.168.1.20/stream1 \
      --live --session-minutes 60 --mode ultra --api https://monitor.example.gov.in

  # no backend at all: just write the JSON event to disk
  python run_edge.py --config config/TC-KA-001.json --source demo/classroom.mp4 --out out/
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from pratyaksh_edge.pipeline import SessionPipeline
from pratyaksh_edge.uplink import Outbox

HERE = Path(__file__).resolve().parent


def post_register(api: str, centre_id: str, session_id: str, batch_id: str, reported: int, key: str, start: str):
    """Demo helper: in production the attendance register comes from the scheme MIS, not the edge box."""
    import requests

    r = requests.post(f"{api.rstrip('/')}/api/v1/centres/{centre_id}/attendance",
                      json={"session_id": session_id, "batch_id": batch_id, "reported_count": reported, "date": start[:10]},
                      headers={"X-Device-Key": key}, timeout=10)
    r.raise_for_status()


def main(argv=None):
    ap = argparse.ArgumentParser(description="PRATYAKSH edge analytics")
    ap.add_argument("--config", required=True)
    ap.add_argument("--source", required=True, help="video file, RTSP URL, or webcam index")
    ap.add_argument("--api", default=None, help="backend base URL, e.g. http://localhost:8000")
    ap.add_argument("--mode", default="lite", choices=["full", "lite", "ultra", "offline"])
    ap.add_argument("--batch", default="B1")
    ap.add_argument("--session-id", default=None)
    ap.add_argument("--reported", type=int, default=None, help="demo: post the centre's claimed attendance")
    ap.add_argument("--annotate", default=None, help="write an annotated (anonymised) preview video")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--out", default=None, help="directory to also write event JSON")
    ap.add_argument("--max-seconds", type=float, default=None)
    ap.add_argument("--live", action="store_true", help="loop forever in fixed-length sessions")
    ap.add_argument("--session-minutes", type=float, default=60)
    ap.add_argument("--outbox", default=str(HERE / "outbox.db"))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")

    cfg_path = Path(args.config).resolve()
    cfg = json.loads(cfg_path.read_text())
    pipe = SessionPipeline(cfg, base_dir=cfg_path.parent.parent, mode=args.mode)
    outbox = Outbox(args.outbox, args.api, cfg.get("device_key"), args.mode)
    logging.info("Detector backend: %s | mode: %s | pending events: %d", pipe.detector.backend, args.mode, outbox.pending())

    while True:
        start = datetime.now(timezone.utc)
        sid = args.session_id or f"{cfg['centre_id']}-{start.strftime('%Y%m%d-%H%M%S')}-{args.batch}"
        max_s = args.session_minutes * 60 if args.live else args.max_seconds
        event = pipe.run(args.source, sid, args.batch, start=None if not args.live else start,
                         max_seconds=max_s, annotate_path=args.annotate, show=args.show)
        sealed = outbox.enqueue(event)

        att = event["attendance"]
        print(f"\nSession {sid}")
        print(f"  observed {att['observed_count']} (peak {att['peak_count']}, sustained tracks {att['sustained_tracks']}, "
              f"confidence {att['confidence']:.2f})")
        for it in event["infrastructure"]:
            print(f"  {it['item']:<14} sanctioned {it['sanctioned']:>3} detected {it['detected']:>3} "
                  f"util {it['utilization_pct']:>5}%  -> {it['status']}")
        for t in event["tamper"]:
            print(f"  TAMPER {t['type']} at {t['start_s']}s for {t['duration_s']}s ({t['detail']})")
        print(f"  flags: {', '.join(event['flags']) or 'none'} | payload {Outbox.payload_size(sealed)/1024:.1f} KB | hash {sealed['hash'][:12]}…")

        if args.out:
            Path(args.out).mkdir(parents=True, exist_ok=True)
            (Path(args.out) / f"{sid}.json").write_text(json.dumps(sealed, indent=2))
        if args.api and args.reported is not None:
            try:
                post_register(args.api, cfg["centre_id"], sid, args.batch, args.reported, cfg.get("device_key", ""), event["window"]["start"])
            except Exception as exc:
                logging.warning("Could not post register: %s", exc)
        stats = outbox.flush()
        print(f"  uplink: sent {stats['sent']} ({stats['bytes']/1024:.1f} KB), pending {stats['pending']}"
              + (f", error: {stats['error']}" if stats["error"] else ""))
        if not args.live:
            break
        time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
