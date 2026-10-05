// Data layer. Talks to the FastAPI backend; if it is unreachable (or VITE_FORCE_DEMO=1),
// serves the bundled snapshot exported by backend/scripts/export_snapshot.py.
import snapshot from "./demo-snapshot.json";

const env = import.meta.env || {};
export const API_BASE = (env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");
const FORCE_DEMO = env.VITE_FORCE_DEMO === "1";

let source = null; // "live" | "demo"

async function fetchJSON(path, opts = {}, timeout = 8000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeout);
  try {
    const r = await fetch(API_BASE + path, { ...opts, signal: ctrl.signal, headers: { "Content-Type": "application/json", ...(opts.headers || {}) } });
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body.detail || `${r.status} ${r.statusText}`);
    }
    return r.headers.get("content-type")?.includes("json") ? r.json() : r.text();
  } finally {
    clearTimeout(t);
  }
}

export async function detectSource() {
  if (FORCE_DEMO) return (source = "demo");
  try {
    await fetchJSON("/api/v1/health", {}, 1500);
    source = "live";
  } catch {
    source = "demo";
  }
  return source;
}

export const getSource = () => source;
const qs = (o) => {
  const p = Object.entries(o || {}).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return p.length ? "?" + new URLSearchParams(p).toString() : "";
};
const clone = (x) => JSON.parse(JSON.stringify(x));

export const api = {
  summary: () => (source === "live" ? fetchJSON("/api/v1/dashboard/summary") : Promise.resolve(clone(snapshot.summary))),
  centres: () => (source === "live" ? fetchJSON("/api/v1/centres") : Promise.resolve(clone(snapshot.centres))),
  centre: (id) => (source === "live" ? fetchJSON(`/api/v1/centres/${id}`) : Promise.resolve(clone(snapshot.details[id]))),
  brief: (id) => (source === "live" ? fetchJSON(`/api/v1/centres/${id}/brief`) : Promise.resolve(clone(snapshot.briefs[id]))),
  queue: () => (source === "live" ? fetchJSON("/api/v1/inspections/queue") : Promise.resolve(clone(snapshot.queue))),
  fleet: () => (source === "live" ? fetchJSON("/api/v1/fleet") : Promise.resolve(clone(snapshot.fleet))),
  alerts: (params) => {
    if (source === "live") return fetchJSON("/api/v1/alerts" + qs(params));
    let a = snapshot.alerts;
    if (params?.status) a = a.filter((x) => x.status === params.status);
    if (params?.severity) a = a.filter((x) => x.severity === params.severity);
    if (params?.centre_id) a = a.filter((x) => x.centre_id === params.centre_id);
    return Promise.resolve(clone(a));
  },
  updateAlert: (id, status, note = "") => {
    if (source === "live") return fetchJSON(`/api/v1/alerts/${id}`, { method: "PATCH", body: JSON.stringify({ status, note }) });
    const touch = (list) => list.forEach((a) => a.id === id && Object.assign(a, { status, note }));
    touch(snapshot.alerts);
    Object.values(snapshot.details).forEach((d) => touch(d.alerts));
    return Promise.resolve({ id, status, note });
  },
};
