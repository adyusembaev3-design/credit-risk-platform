// Small hand-built SVG charts: one y-axis, hairline grid, 2px lines, rounded column ends,
// a crosshair tooltip on lines and a per-group tooltip on columns, and a data table under each.
import { useLayoutEffect, useRef, useState } from "react";

function useWidth() {
  const ref = useRef(null);
  const [w, setW] = useState(640);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(260, Math.round(e.contentRect.width))));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

export function niceTicks(min, max, count = 5) {
  if (min === max) max = min + 1;
  const raw = (max - min) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => raw <= s);
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(+v.toFixed(10));
  return ticks;
}

const scale = (d0, d1, r0, r1) => (v) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);

function Tip({ x, y, width, title, rows }) {
  const left = x + 14 + 170 > width ? x - 14 - 170 : x + 14;
  return (
    <div className="tip" style={{ left: Math.max(0, left), top: Math.max(0, y) }}>
      <div className="t">{title}</div>
      {rows.map((r) => (
        <div className="row" key={r.name}>
          <span>{r.color && <i style={{ background: r.color }} />}{r.name}</span>
          <span className="num">{r.value}</span>
        </div>
      ))}
    </div>
  );
}

export function Legend({ series, square = false }) {
  if (series.length < 2) return null;
  return (
    <div className="legend">
      {series.map((s) => (
        <span key={s.key}><i className={square ? "sq" : ""} style={{ background: s.color }} />{s.name}</span>
      ))}
    </div>
  );
}

export function DataTable({ columns, rows, label = "Data table" }) {
  return (
    <details className="data">
      <summary>{label}</summary>
      <div className="scroll">
        <table>
          <thead>
            <tr>{columns.map((c) => <th key={c.key} className={c.align === "r" ? "r" : ""}>{c.name}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c.key} className={c.align === "r" ? "r" : ""}>{c.format ? c.format(r[c.key], r) : r[c.key]}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

/** Line chart. data: rows sorted by x; series: [{key, name, color}]. */
export function LineChart({
  data, x, series, height = 260, xFormat = String, yFormat = String, tipTitle,
  yMin, yMax, hrefs = [], vrefs = [], markers = [], area = false, ariaLabel,
}) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const m = { t: 14, r: 16, b: 28, l: 52 };
  const xs = data.map((d) => d[x]);
  const ys = data.flatMap((d) => series.map((s) => d[s.key])).filter((v) => v != null && !Number.isNaN(v));
  const refYs = hrefs.map((h) => h.y);
  const lo = yMin ?? Math.min(0, ...ys, ...refYs);
  const hi = yMax ?? Math.max(...ys, ...refYs);
  const yt = niceTicks(lo, hi, 4);
  const sx = scale(Math.min(...xs), Math.max(...xs), m.l, width - m.r);
  const sy = scale(yt[0], yt[yt.length - 1], height - m.b, m.t);
  const xt = niceTicks(Math.min(...xs), Math.max(...xs), Math.max(2, Math.floor(width / 110)))
    .filter((v) => v >= Math.min(...xs) && v <= Math.max(...xs));

  const path = (key) => {
    let d = "", open = false;
    data.forEach((row) => {
      const v = row[key];
      if (v == null || Number.isNaN(v)) { open = false; return; }
      d += `${open ? "L" : "M"}${sx(row[x]).toFixed(1)},${sy(v).toFixed(1)}`;
      open = true;
    });
    return d;
  };

  const onMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * width;
    let best = 0;
    data.forEach((row, i) => { if (Math.abs(sx(row[x]) - px) < Math.abs(sx(data[best][x]) - px)) best = i; });
    setHover(best);
  };
  const h = hover != null ? data[hover] : null;

  return (
    <div className="chart" ref={ref}>
      <Legend series={series} />
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel}>
        {yt.map((t) => (
          <g key={t}>
            <line className={t === 0 ? "baseline" : "grid-line"} x1={m.l} x2={width - m.r} y1={sy(t)} y2={sy(t)} />
            <text x={m.l - 8} y={sy(t) + 4} textAnchor="end">{yFormat(t)}</text>
          </g>
        ))}
        {xt.map((t) => <text key={t} x={sx(t)} y={height - 8} textAnchor="middle">{xFormat(t)}</text>)}
        {vrefs.map((v) => (
          <g key={v.label}>
            <line className="ref" x1={sx(v.x)} x2={sx(v.x)} y1={m.t} y2={height - m.b} />
            <text className="ref-label" x={sx(v.x) + 6} y={m.t + 10}>{v.label}</text>
          </g>
        ))}
        {hrefs.map((r) => (
          <g key={r.label}>
            <line className="ref" x1={m.l} x2={width - m.r} y1={sy(r.y)} y2={sy(r.y)} />
            <text className="ref-label" x={width - m.r} y={sy(r.y) - 6} textAnchor="end">{r.label}</text>
          </g>
        ))}
        {area && series.length === 1 && (
          <path d={`${path(series[0].key)}L${sx(xs[xs.length - 1])},${sy(yt[0])}L${sx(xs[0])},${sy(yt[0])}Z`}
            fill={series[0].color} opacity="0.1" />
        )}
        {series.map((s) => (
          <path key={s.key} d={path(s.key)} fill="none" stroke={s.color} strokeWidth="2"
            strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {markers.map((p) => (
          <g key={p.label}>
            <circle cx={sx(p.x)} cy={sy(p.y)} r="5" fill={p.color || "var(--ink)"} stroke="var(--surface)" strokeWidth="2" />
            {p.label && <text x={sx(p.x)} y={sy(p.y) - 11} textAnchor="middle" className="ref-label">{p.label}</text>}
          </g>
        ))}
        {h && (
          <g>
            <line className="cross" x1={sx(h[x])} x2={sx(h[x])} y1={m.t} y2={height - m.b} />
            {series.map((s) => h[s.key] != null && !Number.isNaN(h[s.key]) && (
              <circle key={s.key} cx={sx(h[x])} cy={sy(h[s.key])} r="4.5" fill={s.color} stroke="var(--surface)" strokeWidth="2" />
            ))}
          </g>
        )}
        <rect x={m.l} y={0} width={Math.max(0, width - m.l - m.r)} height={height} fill="transparent"
          onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
      </svg>
      {h && (
        <Tip x={sx(h[x])} y={8} width={width} title={tipTitle ? tipTitle(h) : xFormat(h[x])}
          rows={series.map((s) => ({ name: s.name, color: s.color, value: yFormat(h[s.key], true) }))} />
      )}
    </div>
  );
}

/** Grouped columns. data: [{[cat]: label, ...values}]; series: [{key, name, color}]. */
export function ColumnChart({ data, cat, series, height = 240, yFormat = String, tipTitle = (d) => d, ariaLabel }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const m = { t: 14, r: 8, b: 28, l: 52 };
  const ys = data.flatMap((d) => series.map((s) => d[s.key]));
  const yt = niceTicks(0, Math.max(...ys), 4);
  const sy = scale(0, yt[yt.length - 1], height - m.b, m.t);
  const band = (width - m.l - m.r) / data.length;
  const bw = Math.min(24, (band * 0.7 - 2 * (series.length - 1)) / series.length);
  const groupW = bw * series.length + 2 * (series.length - 1);
  const col = (x, y, w) => {
    const base = sy(0), r = Math.min(4, w / 2, base - y);
    return `M${x},${base}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${base}Z`;
  };
  return (
    <div className="chart" ref={ref}>
      <Legend series={series} square />
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={ariaLabel}>
        {yt.map((t) => (
          <g key={t}>
            <line className={t === 0 ? "baseline" : "grid-line"} x1={m.l} x2={width - m.r} y1={sy(t)} y2={sy(t)} />
            <text x={m.l - 8} y={sy(t) + 4} textAnchor="end">{yFormat(t)}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const x0 = m.l + i * band + (band - groupW) / 2;
          return (
            <g key={d[cat]} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={m.l + i * band} y={m.t} width={band} height={height - m.t - m.b}
                fill={hover === i ? "var(--surface-2)" : "transparent"} />
              {series.map((s, j) => (
                <path key={s.key} d={col(x0 + j * (bw + 2), sy(d[s.key]), bw)} fill={s.color} />
              ))}
              <text x={m.l + i * band + band / 2} y={height - 8} textAnchor="middle">{d[cat]}</text>
            </g>
          );
        })}
      </svg>
      {hover != null && (
        <Tip x={m.l + hover * band + band / 2} y={8} width={width} title={tipTitle(data[hover][cat])}
          rows={series.map((s) => ({ name: s.name, color: s.color, value: yFormat(data[hover][s.key], true) }))} />
      )}
    </div>
  );
}
