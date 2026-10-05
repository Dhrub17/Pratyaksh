# Demo script (about 3 minutes)

Before you start: backend running with simulated history, dashboard open on Overview, a terminal ready in `edge/`, and a short recorded clip of your team (for example 8 people in a lab).

1. **The problem (20 s).** "Between inspections, nobody knows whether the 30 trainees on the register are actually in the room, or whether the sanctioned machines are still there."

2. **Overview (30 s).** Point at the KPIs: 40 centres, average Trust Score, trainee-sessions overstated this week, and *2.5 KB per centre per day*: no video leaves the centre. Hover the red dots on the risk view.

3. **Inspection queue (30 s).** Open rank 1. Read the reasons aloud. Click *Inspection brief*, then *Print*. "This is what the inspector carries."

4. **Evidence drawer (40 s).** On a ghost-attendance centre: red bars under the yellow claim line, every session. On Ludhiana: both lathes missing for the last week. On Gaya: replayed footage, so the Trust Score is capped. On Varanasi: a deleted event broke the hash chain.

5. **Live edge run (40 s).**
   ```bash
   python run_edge.py --config config/TC-KA-001.json --source demo/team.mp4 --api http://localhost:8000 --reported 30 --annotate out/team.mp4
   ```
   Show the terminal output (observed 8 vs claimed 30, payload size, hash), refresh the dashboard, and open TC-KA-001: a new high-severity attendance alert. Play the anonymised annotated video: boxes and counts, faces blurred.

6. **Privacy and bandwidth (20 s).** Privacy page: what is and isn't identified. Edge devices page: modes and KB/day.

Close: "We don't replace inspections. We make every inspection count."
