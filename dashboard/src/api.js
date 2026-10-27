// Same-origin in production (FastAPI serves the dashboard); proxied to :8000 by Vite in development.
const BASE = import.meta.env.VITE_API_URL || "";

async function request(path, options) {
  const res = await fetch(BASE + path, options);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body.detail) detail = typeof body.detail === "string" ? body.detail : body.detail.map((d) => `${d.loc.slice(-1)[0]}: ${d.msg}`).join("; ");
    } catch { /* not JSON */ }
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  meta: () => request("/api/meta"),
  dashboard: () => request("/api/dashboard"),
  grid: () => request("/api/stress/grid"),
  sample: (seed) => request(`/api/applications/sample?n=1${seed != null ? `&seed=${seed}` : ""}`).then((r) => r[0]),
  score: (application) =>
    request("/api/score", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ applications: [application] }),
    }).then((r) => ({ ...r.decisions[0], model_version: r.model_version, latency_ms: r.latency_ms })),
};
