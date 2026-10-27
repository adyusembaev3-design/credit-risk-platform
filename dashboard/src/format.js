export const pct = (v, d = 1) => (v == null || Number.isNaN(v) ? "–" : `${(v * 100).toFixed(d)}%`);
export const usdM = (v, d = 1) => (v == null ? "–" : `${v < 0 ? "−" : ""}$${Math.abs(v).toFixed(d)}M`);
export const usd = (v, d = 2) => (v == null ? "–" : `${v < 0 ? "−" : ""}$${Math.abs(v).toFixed(d)}`);
export const num = (v, d = 0) =>
  v == null ? "–" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
export const compact = (v) => {
  if (v == null) return "–";
  const a = Math.abs(v);
  if (a >= 1e6) return `${(v / 1e6).toFixed(a >= 1e7 ? 0 : 1)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(a >= 1e4 ? 0 : 1)}K`;
  return `${v}`;
};
export const pp = (v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2).replace(/\.?0+$/, "") || "0"} pp`;
