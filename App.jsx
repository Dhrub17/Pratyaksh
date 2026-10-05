// PRATYAKSH monitoring dashboard: built by Team Wandel for Smart India Hackathon 2026.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api, API_BASE, detectSource } from "./api.js";

const RISK = ["critical", "high", "medium", "low"];
const RISK_COLOR = { critical: "var(--critical)", high: "var(--high)", medium: "var(--medium)", low: "var(--low)" };
const fmt = (n, d = 0) => (n === null || n === undefined || Number.isNaN(n) ? "–" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d }));
const pct = (x, d = 0) => (x === null || x === undefined ? "–" : `${fmt(x * 100, d)}%`);
const day = (iso) => (iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "–");
const dt = (iso) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "–");
const ago = (iso) => {
  if (!iso) return "never";
  const h = (Date.now() - new Date(iso).getTime()) / 36e5;
  if (h < 1) return "just now";
  if (h < 24) return `${Math.round(h)} h ago`;
  return `${Math.round(h / 24)} d ago`;
};
const label = (s) => (s || "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

const VIEWS = [
  { id: "overview", name: "Overview", blurb: "Where compliance risk is right now, across every monitored centre." },
  { id: "queue", name: "Inspection queue", blurb: "Centres ranked by risk, with the reasons and what to check on site." },
  { id: "centres", name: "Centres", blurb: "Every empanelled centre with its Trust Score and open findings." },
  { id: "alerts", name: "Alerts", blurb: "Flags raised by the cameras. Acknowledge, escalate or resolve them here." },
  { id: "fleet", name: "Edge devices", blurb: "Camera health, bandwidth use and log integrity for each centre's edge box." },
  { id: "privacy", name: "Privacy", blurb: "What the system does and does not identify from footage." },
];

// ---------------------------------------------------------------- small pieces
function Badge({ level, children }) {
  return <span className={`badge ${level || "neutral"}`}>{children || label(level)}</span>;
}

function ScoreRing({ score, level, size = 92 }) {
  const r = size / 2 - 7;
  const c = 2 * Math.PI * r;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`Trust Score ${score}`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(148,170,230,.15)" strokeWidth="7" />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={RISK_COLOR[level]} strokeWidth="7" strokeLinecap="round"
        strokeDasharray={`${(c * score) / 100} ${c}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      <text x="50%" y="50%" textAnchor="middle" dominantBaseline="central" fill="var(--text)"
        style={{ font: `600 ${size * 0.28}px var(--display)` }}>{Math.round(score)}</text>
    </svg>
  );
}

function Bar({ value, max = 100, color = "var(--emerald)" }) {
  return <div className="bar"><span style={{ width: `${Math.max(0, Math.min(100, (100 * value) / max))}%`, background: color }} /></div>;
}

// ---------------------------------------------------------------- geo view
// Centres plotted by latitude/longitude on a plain graticule. We deliberately do not draw
// state or national boundaries here: official deployments must use Survey of India maps.
function GeoView({ centres, onOpen }) {
  const [tip, setTip] = useState(null);
  const W = 560, H = 560, L0 = 67, L1 = 98, A0 = 6, A1 = 37;
  const x = (lng) => ((lng - L0) / (L1 - L0)) * W;
  const y = (lat) => ((A1 - lat) / (A1 - A0)) * H;
  const sorted = [...centres].sort((a, b) => RISK.indexOf(b.risk_level) - RISK.indexOf(a.risk_level));
  return (
    <div className="geo" onMouseLeave={() => setTip(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Map of monitored centres coloured by risk">
        {[70, 75, 80, 85, 90, 95].map((l) => (
          <g key={`lng${l}`}>
            <line x1={x(l)} x2={x(l)} y1={0} y2={H} stroke="rgba(148,170,230,.08)" />
            <text x={x(l) + 4} y={H - 6} fill="var(--faint)" style={{ font: "10px var(--mono)" }}>{l}°E</text>
          </g>
        ))}
        {[10, 15, 20, 25, 30, 35].map((a) => (
          <g key={`lat${a}`}>
            <line x1={0} x2={W} y1={y(a)} y2={y(a)} stroke="rgba(148,170,230,.08)" />
            <text x={4} y={y(a) - 4} fill="var(--faint)" style={{ font: "10px var(--mono)" }}>{a}°N</text>
          </g>
        ))}
        {sorted.map((c) => {
          const cx = x(c.lng), cy = y(c.lat);
          const r = { critical: 7.5, high: 6.5, medium: 5.5, low: 4.5 }[c.risk_level];
          const hot = c.risk_level === "critical" || c.risk_level === "high";
          return (
            <g key={c.id}>
              {hot && <circle className="pulse" cx={cx} cy={cy} r={6} fill="none" stroke={RISK_COLOR[c.risk_level]} strokeWidth="1.5" />}
              <circle className="pt" cx={cx} cy={cy} r={r} fill={RISK_COLOR[c.risk_level]} fillOpacity={hot ? 0.95 : 0.7}
                tabIndex={0} role="button" aria-label={`${c.name}, Trust Score ${Math.round(c.trust_score)}`}
                onClick={() => onOpen(c.id)} onKeyDown={(e) => e.key === "Enter" && onOpen(c.id)}
                onMouseEnter={() => setTip({ c, left: (cx / W) * 100, top: (cy / H) * 100 })} />
              {hot && <text x={cx + 10} y={cy + 4} fill="var(--text)" style={{ font: "500 11px var(--body)" }}>{c.district}</text>}
            </g>
          );
        })}
      </svg>
      {tip && (
        <div className="tip" style={{ left: `min(calc(${tip.left}% + 14px), calc(100% - 220px))`, top: `calc(${tip.top}% - 10px)` }}>
          <div style={{ fontWeight: 600 }}>{tip.c.name}</div>
          <div className="muted mono">{tip.c.id} · {tip.c.state}</div>
          <div style={{ marginTop: 6, display: "flex", gap: 8, alignItems: "center" }}>
            <Badge level={tip.c.risk_level} /> <span>Trust Score {Math.round(tip.c.trust_score)}</span>
          </div>
          <div className="muted" style={{ marginTop: 4 }}>{tip.c.open_alerts_total} open alerts</div>
        </div>
      )}
      <div className="legend">
        {RISK.map((r) => <span key={r}><i style={{ background: RISK_COLOR[r] }} />{label(r)} risk</span>)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- charts
function TrendChart({ data }) {
  if (!data?.length) return <div className="empty">No sessions in the last 14 days.</div>;
  const W = 640, H = 220, P = { l: 44, r: 12, t: 12, b: 26 };
  // Non-zero baseline so the gap is visible; the axis labels state the range.
  const hi = Math.max(...data.map((d) => Math.max(d.reported, d.observed)));
  const lo = Math.min(...data.map((d) => Math.min(d.reported, d.observed)));
  const pad = Math.max(1, (hi - lo) * 0.25);
  const min = Math.max(0, lo - pad), max = hi + pad;
  const X = (i) => P.l + (i * (W - P.l - P.r)) / Math.max(1, data.length - 1);
  const Y = (v) => P.t + (1 - (v - min) / (max - min || 1)) * (H - P.t - P.b);
  const line = (k) => data.map((d, i) => `${i ? "L" : "M"}${X(i)},${Y(d[k])}`).join("");
  const gap = `${line("reported")} ${[...data].reverse().map((d, i) => `L${X(data.length - 1 - i)},${Y(d.observed)}`).join("")} Z`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Reported versus observed attendance per day">
      {[0, 0.5, 1].map((f) => {
        const v = min + (max - min) * f;
        return (
          <g key={f}>
            <line x1={P.l} x2={W - P.r} y1={Y(v)} y2={Y(v)} stroke="rgba(148,170,230,.1)" />
            <text x={P.l - 6} y={Y(v) + 4} textAnchor="end" fill="var(--faint)" style={{ font: "10px var(--mono)" }}>{fmt(v)}</text>
          </g>
        );
      })}
      <path d={gap} fill="rgba(255,77,109,.14)" />
      <path d={line("observed")} fill="none" stroke="var(--emerald)" strokeWidth="2.5" />
      <path d={line("reported")} fill="none" stroke="var(--claim)" strokeWidth="2" strokeDasharray="5 4" />
      {data.map((d, i) => (i % 2 === 0 || i === data.length - 1) && (
        <text key={d.date} x={X(i)} y={H - 6} textAnchor="middle" fill="var(--faint)" style={{ font: "10px var(--mono)" }}>{day(d.date)}</text>
      ))}
    </svg>
  );
}

function SessionChart({ sessions }) {
  const s = [...sessions].reverse().slice(-24);
  if (!s.length) return <div className="empty">No sessions received from this centre yet.</div>;
  const W = 720, H = 200, P = { l: 34, r: 8, t: 10, b: 24 };
  const max = Math.max(...s.map((x) => Math.max(x.reported_count || 0, x.observed_count || 0))) * 1.15 || 1;
  const bw = (W - P.l - P.r) / s.length;
  const Y = (v) => P.t + (1 - v / max) * (H - P.t - P.b);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Observed and reported attendance per session">
      {[0, 0.5, 1].map((f) => (
        <g key={f}>
          <line x1={P.l} x2={W - P.r} y1={Y(max * f)} y2={Y(max * f)} stroke="rgba(148,170,230,.1)" />
          <text x={P.l - 5} y={Y(max * f) + 4} textAnchor="end" fill="var(--faint)" style={{ font: "10px var(--mono)" }}>{fmt(max * f)}</text>
        </g>
      ))}
      {s.map((x, i) => {
        const bx = P.l + i * bw + bw * 0.18, w = bw * 0.64;
        const mm = x.attendance_status === "mismatch", bad = x.attendance_status === "unverifiable";
        return (
          <g key={x.id}>
            <title>{`${dt(x.start)} ${x.batch_id}: observed ${x.observed_count}, register ${x.reported_count ?? "not submitted"} (${label(x.attendance_status)})`}</title>
            <rect x={bx} y={Y(x.observed_count || 0)} width={w} height={Math.max(1, Y(0) - Y(x.observed_count || 0))} rx="3"
              fill={bad ? "rgba(139,152,189,.35)" : mm ? "rgba(255,77,109,.75)" : "rgba(46,242,160,.7)"} />
            {x.reported_count != null && <line x1={bx - 2} x2={bx + w + 2} y1={Y(x.reported_count)} y2={Y(x.reported_count)} stroke="var(--claim)" strokeWidth="2.5" />}
            {i % 4 === 0 && <text x={bx + w / 2} y={H - 6} textAnchor="middle" fill="var(--faint)" style={{ font: "10px var(--mono)" }}>{day(x.start)}</text>}
          </g>
        );
      })}
    </svg>
  );
}

// ---------------------------------------------------------------- views
function Overview({ summary, centres, alerts, onOpen, go }) {
  const s = summary;
  const atRisk = (s.centres_by_risk.critical || 0) + (s.centres_by_risk.high || 0);
  const kpis = [
    { l: "Centres monitored", v: fmt(s.centres_total), n: `${s.devices_online} edge devices reporting` },
    { l: "Average Trust Score", v: fmt(s.avg_trust_score, 1), n: "rolling 14 days" },
    { l: "Centres at high risk", v: fmt(atRisk), n: `${s.centres_by_risk.critical} critical`, c: atRisk ? "var(--high)" : undefined },
    { l: "Open critical + high alerts", v: fmt((s.open_alerts.critical || 0) + (s.open_alerts.high || 0)), n: `${fmt(Object.values(s.open_alerts).reduce((a, b) => a + b, 0))} open in total` },
    { l: "Trainee-sessions overstated", v: fmt(s.attendance_7d.overstated), n: `last 7 days · ${pct(s.attendance_7d.mismatch_rate)} of sessions`, c: "var(--critical)" },
    { l: "Data sent per centre", v: `${fmt(s.avg_kb_per_centre_day, 1)} KB`, n: "per day · no video uploaded" },
  ];
  const top = centres.slice(0, 7);
  const openAlerts = alerts.filter((a) => a.status === "open").slice(0, 7);
  return (
    <>
      <div className="grid kpis">
        {kpis.map((k) => (
          <div className="panel kpi" key={k.l}>
            <div className="l">{k.l}</div>
            <div className="v" style={{ color: k.c }}>{k.v}</div>
            <div className="n">{k.n}</div>
          </div>
        ))}
      </div>
      <div className="grid two">
        <div className="panel">
          <h3>Risk across the network</h3>
          <p className="sub">Each dot is a training centre. Select one to see its evidence.</p>
          <GeoView centres={centres} onOpen={onOpen} />
        </div>
        <div className="panel">
          <h3>Lowest Trust Scores</h3>
          <p className="sub">Where an inspector's visit is most likely to find a problem.</p>
          {top.map((c) => (
            <div className="list-row" key={c.id} onClick={() => onOpen(c.id)} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onOpen(c.id)}>
              <div className="score-chip" style={{ color: RISK_COLOR[c.risk_level] }}>{Math.round(c.trust_score)}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="t" style={{ fontWeight: 500 }}>{c.name}</div>
                <div className="muted" style={{ fontSize: 12.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {c.score_breakdown?.[0]?.detail || "No issues in the scoring window"}
                </div>
              </div>
              <Badge level={c.risk_level} />
            </div>
          ))}
          <button className="btn" style={{ marginTop: 12, width: "100%" }} onClick={() => go("queue")}>Open inspection queue</button>
        </div>
      </div>
      <div className="grid two-even">
        <div className="panel">
          <h3>Claimed vs. observed attendance</h3>
          <p className="sub">
            <span style={{ color: "var(--claim)" }}>Dashed: register claims</span> · <span style={{ color: "var(--emerald)" }}>solid: camera count</span> · shaded: the gap
          </p>
          <TrendChart data={s.trend} />
        </div>
        <div className="panel">
          <h3>Latest open alerts</h3>
          <p className="sub">Most severe first.</p>
          {openAlerts.length === 0 && <div className="empty">No open alerts.</div>}
          {openAlerts.map((a) => (
            <div className="alert-row" key={a.id}>
              <Badge level={a.severity} />
              <div style={{ minWidth: 0 }}>
                <div className="t">{a.title}</div>
                <div className="d">{a.centre_name} · {dt(a.created_at)}</div>
              </div>
              <button className="btn small" onClick={() => onOpen(a.centre_id)}>View</button>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

function QueueView({ queue, onOpen, onBrief }) {
  if (!queue.length) return <div className="panel empty">No centres need an inspection right now.</div>;
  return queue.map((q) => (
    <div className="panel queue-card" key={q.centre_id}>
      <div className="rank">{q.rank}</div>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <h3 style={{ margin: 0 }}>{q.name}</h3>
          <Badge level={q.risk_level} />
          <span className="mono faint">{q.centre_id}</span>
        </div>
        <div className="muted" style={{ fontSize: 12.5 }}>{q.district}, {q.state}</div>
        <ul>{q.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        {q.suggested_checks.length > 0 && (
          <>
            <div style={{ marginTop: 10, fontSize: 12.5, fontWeight: 600 }}>Check on site</div>
            <ul>{q.suggested_checks.map((r) => <li key={r}>{r}</li>)}</ul>
          </>
        )}
      </div>
      <div style={{ display: "grid", gap: 8, justifyItems: "end" }}>
        <ScoreRing score={q.trust_score} level={q.risk_level} size={78} />
        <div className="muted" style={{ fontSize: 12 }}>{q.open_alerts.critical} critical · {q.open_alerts.high} high</div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn small" onClick={() => onOpen(q.centre_id)}>Evidence</button>
          <button className="btn small primary" onClick={() => onBrief(q.centre_id)}>Inspection brief</button>
        </div>
      </div>
    </div>
  ));
}

function CentresView({ centres, onOpen }) {
  const [q, setQ] = useState("");
  const [state, setState] = useState("");
  const [risk, setRisk] = useState("");
  const states = useMemo(() => [...new Set(centres.map((c) => c.state))].sort(), [centres]);
  const rows = centres.filter((c) => (!state || c.state === state) && (!risk || c.risk_level === risk) &&
    (!q || `${c.name} ${c.id} ${c.district}`.toLowerCase().includes(q.toLowerCase())));
  return (
    <div className="panel">
      <div className="filters">
        <input placeholder="Search by name, ID or district" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search centres" />
        <select value={state} onChange={(e) => setState(e.target.value)} aria-label="Filter by state">
          <option value="">All states</option>{states.map((s) => <option key={s}>{s}</option>)}
        </select>
        <select value={risk} onChange={(e) => setRisk(e.target.value)} aria-label="Filter by risk">
          <option value="">All risk levels</option>{RISK.map((r) => <option key={r} value={r}>{label(r)}</option>)}
        </select>
        <span className="muted" style={{ alignSelf: "center" }}>{rows.length} centres</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Centre</th><th>State</th><th className="num">Trust Score</th><th>Risk</th><th className="num">Claimed (7 d)</th><th className="num">Observed (7 d)</th><th className="num">Open alerts</th><th>Last report</th></tr></thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="clickable" onClick={() => onOpen(c.id)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onOpen(c.id)}>
                <td><div style={{ fontWeight: 500 }}>{c.name}</div><div className="mono faint">{c.id}</div></td>
                <td>{c.state}</td>
                <td className="num" style={{ fontWeight: 600, color: RISK_COLOR[c.risk_level] }}>{fmt(c.trust_score, 1)}</td>
                <td><Badge level={c.risk_level} /></td>
                <td className="num">{fmt(c.reported_7d)}</td>
                <td className="num" style={{ color: c.reported_7d > c.observed_7d * 1.15 ? "var(--critical)" : undefined }}>{fmt(c.observed_7d)}</td>
                <td className="num">{c.open_alerts_total || "–"}</td>
                <td className="muted">{ago(c.last_seen)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <div className="empty">No centres match these filters.</div>}
      </div>
    </div>
  );
}

function AlertActions({ a, onUpdate }) {
  if (a.status !== "open") return <Badge level="neutral">{label(a.status)}</Badge>;
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
      <button className="btn small" onClick={() => onUpdate(a.id, "acknowledged")}>Acknowledge</button>
      <button className="btn small" onClick={() => onUpdate(a.id, "escalated")}>Escalate</button>
      <button className="btn small" onClick={() => onUpdate(a.id, "resolved")}>Resolve</button>
    </div>
  );
}

function AlertsView({ onOpen, onChanged }) {
  const [status, setStatus] = useState("open");
  const [severity, setSeverity] = useState("");
  const [rows, setRows] = useState(null);
  const load = useCallback(() => api.alerts({ status, severity, limit: 300 }).then(setRows), [status, severity]);
  useEffect(() => { load(); }, [load]);
  const update = async (id, st) => { await api.updateAlert(id, st); await load(); onChanged(); };
  return (
    <div className="panel">
      <div className="filters">
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
          <option value="">Any status</option>{["open", "acknowledged", "escalated", "resolved", "dismissed"].map((s) => <option key={s} value={s}>{label(s)}</option>)}
        </select>
        <select value={severity} onChange={(e) => setSeverity(e.target.value)} aria-label="Filter by severity">
          <option value="">Any severity</option>{RISK.map((s) => <option key={s} value={s}>{label(s)}</option>)}
        </select>
        <span className="muted" style={{ alignSelf: "center" }}>{rows ? `${rows.length} alerts` : "Loading…"}</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Severity</th><th>Finding</th><th>Centre</th><th>When</th><th style={{ textAlign: "right" }}>Action</th></tr></thead>
          <tbody>
            {(rows || []).slice(0, 200).map((a) => (
              <tr key={a.id}>
                <td><Badge level={a.severity} /></td>
                <td style={{ maxWidth: 420 }}><div style={{ fontWeight: 500 }}>{a.title}</div><div className="muted" style={{ fontSize: 12.5 }}>{a.detail}</div></td>
                <td><button className="btn small" onClick={() => onOpen(a.centre_id)}>{a.centre_name || a.centre_id}</button></td>
                <td className="muted" style={{ whiteSpace: "nowrap" }}>{dt(a.created_at)}</td>
                <td><AlertActions a={a} onUpdate={update} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows && !rows.length && <div className="empty">No alerts match these filters.</div>}
      </div>
    </div>
  );
}

function FleetView({ fleet, onOpen }) {
  const modes = [
    { m: "Full", d: "events + up to 3 blurred thumbnails per flag", v: "~5–30 KB/day" },
    { m: "Lite", d: "events + 1 blurred thumbnail when a flag fires (default)", v: "~2–10 KB/day" },
    { m: "Ultra", d: "events only, works on 2G links", v: "~2–3 KB/day" },
    { m: "Offline", d: "stored on device, sent when back online", v: "0 until sync" },
  ];
  return (
    <>
      <div className="mode-cmp">
        {modes.map((x) => (
          <div className="panel" key={x.m}>
            <div className="muted">{x.m} mode</div>
            <div className="v">{x.v}</div>
            <div className="faint" style={{ fontSize: 12.5 }}>{x.d}</div>
          </div>
        ))}
      </div>
      <p className="muted" style={{ margin: "0 0 16px" }}>
        For comparison, streaming one 720p camera for a 6-hour training day uses roughly 4 GB. All analysis runs on the edge box at the centre.
      </p>
      <div className="panel table-wrap">
        <table>
          <thead><tr><th>Centre</th><th>Mode</th><th className="num">KB / day</th><th className="num">Sessions (7 d)</th><th className="num">Usable footage</th><th className="num">Log breaks</th><th>Last report</th></tr></thead>
          <tbody>
            {fleet.map((f) => {
              const stale = !f.last_seen || Date.now() - new Date(f.last_seen).getTime() > 26 * 36e5;
              return (
                <tr key={f.centre_id} className="clickable" onClick={() => onOpen(f.centre_id)}>
                  <td><div style={{ fontWeight: 500 }}>{f.name}</div><div className="mono faint">{f.centre_id}</div></td>
                  <td><Badge level="neutral">{label(f.mode)}</Badge></td>
                  <td className="num mono">{fmt(f.kb_per_day, 1)}</td>
                  <td className="num">{f.sessions_7d}</td>
                  <td className="num" style={{ color: f.valid_pct !== null && f.valid_pct < 90 ? "var(--high)" : undefined }}>{f.valid_pct === null ? "–" : `${fmt(f.valid_pct, 1)}%`}</td>
                  <td className="num" style={{ color: f.chain_breaks_7d ? "var(--critical)" : undefined }}>{f.chain_breaks_7d || "–"}</td>
                  <td style={{ color: stale ? "var(--high)" : "var(--muted)" }}>{stale ? `Offline · ${ago(f.last_seen)}` : ago(f.last_seen)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function PrivacyView() {
  const rows = [
    ["Headcount", "Head / body detection, counts only", false],
    ["Sustained presence", "Anonymous track numbers, reset every session", false],
    ["Equipment presence", "Object detection + Golden Frame comparison", null],
    ["Equipment use", "Motion and people near the item", false],
    ["Tamper checks", "Image statistics and frame fingerprints", null],
    ["Evidence thumbnails", "Only when a flag fires; people pixelated, faces blurred on device", false],
    ["Individual verification", "Never by this system. Escalations use the scheme's existing biometric records, with an officer in the loop", true],
  ];
  return (
    <div className="grid two">
      <div className="panel privacy-table">
        <h3>What is identified from footage</h3>
        <p className="sub">Privacy by architecture: the edge box has no facial-recognition model, and video never leaves the centre.</p>
        <table>
          <thead><tr><th>Check</th><th>Method</th><th>Identifies a person?</th></tr></thead>
          <tbody>
            {rows.map(([a, b, c]) => (
              <tr key={a}><td>{a}</td><td className="muted">{b}</td>
                <td>{c === null ? <span className="faint">Not applicable</span> : c ? <span className="yes">Only by exception</span> : <span className="no">No</span>}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel">
        <h3>Data that leaves the centre</h3>
        <p className="sub">One JSON event per session, about 1–3 KB.</p>
        <pre className="brief-text" style={{ fontSize: 11.5 }}>{`{
  "centre_id": "TC-KA-001",
  "attendance": { "observed_count": 24,
                  "confidence": 0.88 },
  "infrastructure": [{ "item": "computer",
      "sanctioned": 20, "detected": 20,
      "utilization_pct": 71, "status": "ok" }],
  "tamper": [],
  "privacy": { "faces_identified": false,
               "video_uploaded": false },
  "prev_hash": "9c1e…", "hash": "4be0…"
}`}</pre>
        <p className="muted" style={{ fontSize: 12.5 }}>Retention: evidence thumbnails are deleted after 30 days unless attached to an open case. Aligned with the Digital Personal Data Protection Act, 2023 principles of purpose limitation and data minimisation.</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- centre drawer & brief
function CentreDrawer({ id, onClose, onBrief, onChanged }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const load = useCallback(() => api.centre(id).then(setD).catch((e) => setErr(e.message)), [id]);
  useEffect(() => { setD(null); load(); }, [load]);
  useEffect(() => {
    const k = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  const update = async (aid, st) => { await api.updateAlert(aid, st); await load(); onChanged(); };
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label="Centre details">
        <button className="btn small close" onClick={onClose}>Close</button>
        {err && <div className="empty">Could not load this centre: {err}</div>}
        {!d && !err && <div className="loading">Loading centre…</div>}
        {d && (() => {
          const c = d.centre;
          const verified = d.sessions.filter((s) => ["ok", "mismatch"].includes(s.attendance_status));
          const mism = verified.filter((s) => s.attendance_status === "mismatch").length;
          return (
            <>
              <div className="drawer-head">
                <ScoreRing score={c.trust_score} level={c.risk_level} />
                <div>
                  <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                    <h2>{c.name}</h2><Badge level={c.risk_level}>{label(c.risk_level)} risk</Badge>
                  </div>
                  <div className="muted">{c.id} · {c.district}, {c.state} · {c.scheme} · {(c.trades || []).join(", ")}</div>
                  <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                    <button className="btn primary small" onClick={() => onBrief(c.id)}>Inspection brief</button>
                  </div>
                </div>
              </div>

              <div className="grid two-even">
                <div className="panel">
                  <h3>Why this score</h3>
                  <p className="sub">Each deduction is tied to evidence from the last 14 days.</p>
                  {(c.score_breakdown || []).length === 0 && <div className="muted">No deductions. Records and footage agree.</div>}
                  {(c.score_breakdown || []).map((b) => (
                    <div className="factor" key={b.factor}>
                      <div><div style={{ fontWeight: 500 }}>{b.label}</div><div className="muted" style={{ fontSize: 12.5 }}>{b.detail}</div></div>
                      <div className="p">−{fmt(b.penalty, 1)}</div>
                    </div>
                  ))}
                </div>
                <div className="panel">
                  <h3>Event log integrity</h3>
                  <p className="sub">Every session event is hash-chained on the edge device.</p>
                  <div style={{ display: "flex", gap: 22, marginBottom: 12 }}>
                    <div><div className="muted" style={{ fontSize: 12 }}>Verified events</div><div style={{ font: "600 22px var(--display)" }}>{d.chain.verified_events}</div></div>
                    <div><div className="muted" style={{ fontSize: 12 }}>Chain breaks</div><div style={{ font: "600 22px var(--display)", color: d.chain.breaks ? "var(--critical)" : "var(--emerald)" }}>{d.chain.breaks}</div></div>
                  </div>
                  <div className="muted" style={{ fontSize: 12 }}>Current chain head</div>
                  <div className="hash">{d.chain.head || "no events yet"}…</div>
                  {d.chain.breaks > 0 && <p style={{ color: "var(--critical)", fontSize: 12.5 }}>One or more events were edited, deleted or replayed on the device.</p>}
                </div>
              </div>

              <div className="panel" style={{ marginBottom: 16 }}>
                <h3>Attendance per session</h3>
                <p className="sub">
                  Bars: camera count (<span style={{ color: "var(--critical)" }}>red when the register overstates it</span>) · <span style={{ color: "var(--claim)" }}>yellow tick: register claim</span> · {mism} of {verified.length} verified sessions mismatched
                </p>
                <SessionChart sessions={d.sessions} />
              </div>

              <div className="grid two-even">
                <div className="panel">
                  <h3>Sanctioned equipment</h3>
                  <p className="sub">Latest session, compared with the empanelment inventory.</p>
                  {d.inventory.length === 0 && <div className="muted">No inventory data yet.</div>}
                  <table>
                    <thead><tr><th>Item</th><th className="num">Sanctioned</th><th className="num">Seen</th><th style={{ width: "34%" }}>Use</th><th>Status</th></tr></thead>
                    <tbody>
                      {d.inventory.map((it) => (
                        <tr key={it.item}>
                          <td>{label(it.item)}</td>
                          <td className="num">{it.sanctioned}</td>
                          <td className="num" style={{ color: it.detected < it.sanctioned * 0.9 ? "var(--critical)" : undefined }}>{it.detected}</td>
                          <td><Bar value={d.utilization[it.item] ?? it.utilization_pct} color={it.status === "idle" ? "var(--medium)" : "var(--emerald)"} />
                            <span className="faint mono">{fmt(d.utilization[it.item] ?? it.utilization_pct)}%</span></td>
                          <td><Badge level={{ ok: "low", idle: "medium", partial: "high", missing: "critical" }[it.status]}>{label(it.status)}</Badge></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="panel">
                  <h3>Camera tampering</h3>
                  <p className="sub">Covered lens, frozen or replayed feeds, moved camera.</p>
                  {d.tamper_events.length === 0 && <div className="muted">No tampering detected.</div>}
                  {d.tamper_events.slice(0, 8).map((t, i) => (
                    <div className="alert-row" key={i}>
                      <Badge level={["REPLAY", "FROZEN"].includes(t.type) ? "critical" : t.type === "BLURRED" ? "medium" : "high"}>{label(t.type.toLowerCase())}</Badge>
                      <div><div className="t">{day(t.date)} · {fmt(t.duration_s / 60)} min</div><div className="d">{t.detail || `confidence ${fmt(t.confidence, 2)}`}</div></div>
                      <span />
                    </div>
                  ))}
                </div>
              </div>

              <div className="panel">
                <h3>Alerts for this centre</h3>
                <p className="sub">{d.alerts.filter((a) => a.status === "open").length} open</p>
                {d.alerts.length === 0 && <div className="muted">No alerts.</div>}
                {d.alerts.slice(0, 25).map((a) => (
                  <div className="alert-row" key={a.id}>
                    <Badge level={a.severity} />
                    <div style={{ minWidth: 0 }}><div className="t">{a.title}</div><div className="d">{a.detail} · {dt(a.created_at)}</div></div>
                    <AlertActions a={a} onUpdate={update} />
                  </div>
                ))}
              </div>
            </>
          );
        })()}
      </aside>
    </>
  );
}

function BriefModal({ id, onClose }) {
  const [b, setB] = useState(null);
  useEffect(() => { api.brief(id).then(setB); }, [id]);
  const download = () => {
    const blob = new Blob([JSON.stringify(b, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `inspection-brief-${id}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  const print = () => {
    const w = window.open("", "_blank");
    if (!w) return;
    w.document.write(`<title>Inspection brief ${id}</title><pre style="font:13px/1.6 monospace;white-space:pre-wrap;padding:24px">${b.text.replace(/</g, "&lt;")}</pre>`);
    w.document.close();
    w.print();
  };
  return (
    <>
      <div className="scrim" style={{ zIndex: 29 }} onClick={onClose} />
      <div className="panel modal" role="dialog" aria-modal="true" aria-label="Inspection brief" style={{ background: "rgba(10,18,44,.98)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, gap: 8, flexWrap: "wrap" }}>
          <h3 style={{ margin: 0 }}>Inspection brief</h3>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn small" onClick={print} disabled={!b}>Print</button>
            <button className="btn small" onClick={download} disabled={!b}>Download JSON</button>
            <button className="btn small" onClick={onClose}>Close</button>
          </div>
        </div>
        {!b ? <div className="loading">Preparing brief…</div> : <div className="brief-text">{b.text}</div>}
      </div>
    </>
  );
}

// ---------------------------------------------------------------- app shell
export default function App() {
  const [view, setView] = useState("overview");
  const [source, setSource] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const [brief, setBrief] = useState(null);

  const loadAll = useCallback(async () => {
    try {
      const [summary, centres, alerts, queue, fleet] = await Promise.all([
        api.summary(), api.centres(), api.alerts({ status: "open", limit: 400 }), api.queue(), api.fleet(),
      ]);
      setData({ summary, centres, alerts, queue, fleet });
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => { detectSource().then((s) => { setSource(s); loadAll(); }); }, [loadAll]);
  useEffect(() => {
    if (source !== "live") return undefined;
    const t = setInterval(loadAll, 30000);
    return () => clearInterval(t);
  }, [source, loadAll]);

  const v = VIEWS.find((x) => x.id === view);
  const openCount = data ? (data.summary.open_alerts.critical || 0) + (data.summary.open_alerts.high || 0) : 0;
  return (
    <div className="app">
      <nav className="side" aria-label="Main">
        <div className="brand">
          <h1>PRATY<span>A</span>KSH</h1>
          <p>Training centre compliance monitor</p>
        </div>
        {VIEWS.map((x) => (
          <button key={x.id} className={`nav-btn ${view === x.id ? "active" : ""}`} onClick={() => setView(x.id)} aria-current={view === x.id ? "page" : undefined}>
            {x.name}
            {x.id === "alerts" && openCount > 0 && <span className="count">{openCount}</span>}
          </button>
        ))}
        <div className="side-foot">
          <div>Smart India Hackathon 2026</div>
          <div>Built by <strong>Team Wandel</strong></div>
        </div>
      </nav>
      <main className="main">
        <header className="topbar">
          <div>
            <h2>{v.name}</h2>
            <p>{v.blurb}</p>
          </div>
          <span className="source" title={source === "live" ? API_BASE : "Backend not reachable; showing the bundled snapshot"}>
            <span className={`dot ${source === "live" ? "" : "demo"}`} />
            {source === null ? "Connecting…" : source === "live" ? "Live data" : "Demo snapshot"}
            {data && <span className="faint">· updated {dt(data.summary.generated_at)}</span>}
          </span>
        </header>
        {error && <div className="panel" style={{ borderColor: "var(--critical)", marginBottom: 16 }}>Could not load data: {error}. Check that the API is running at <span className="mono">{API_BASE}</span>.</div>}
        {!data && !error && <div className="loading">Loading monitoring data…</div>}
        {data && view === "overview" && <Overview {...data} onOpen={setOpen} go={setView} />}
        {data && view === "queue" && <QueueView queue={data.queue} onOpen={setOpen} onBrief={setBrief} />}
        {data && view === "centres" && <CentresView centres={data.centres} onOpen={setOpen} />}
        {data && view === "alerts" && <AlertsView onOpen={setOpen} onChanged={loadAll} />}
        {data && view === "fleet" && <FleetView fleet={data.fleet} onOpen={setOpen} />}
        {data && view === "privacy" && <PrivacyView />}
      </main>
      {open && <CentreDrawer id={open} onClose={() => setOpen(null)} onBrief={setBrief} onChanged={loadAll} />}
      {brief && <BriefModal id={brief} onClose={() => setBrief(null)} />}
    </div>
  );
}
