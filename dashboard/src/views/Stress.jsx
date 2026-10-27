import { useEffect, useState } from "react";
import { api } from "../api.js";
import { ColumnChart, DataTable, LineChart } from "../charts.jsx";
import { pct, pp, usdM } from "../format.js";

const PRESETS = [["Baseline", 0], ["Adverse", 2.5], ["Severe", 5]];

export default function Stress({ dash }) {
  const [grid, setGrid] = useState(null);
  const [d, setD] = useState(2.5);
  const [error, setError] = useState(null);
  useEffect(() => { api.grid().then(setGrid).catch((e) => setError(e.message)); }, []);

  if (error) return <div className="panel"><p className="error">{error}</p></div>;
  if (!grid) return <div className="panel"><p className="empty">Loading the stress grid…</p></div>;

  const at = grid.reduce((a, g) => (Math.abs(g.d_unemp - d) < Math.abs(a.d_unemp - d) ? g : a), grid[0]);
  const base = grid.reduce((a, g) => (Math.abs(g.d_unemp) < Math.abs(a.d_unemp) ? g : a), grid[0]);
  const byGrade = Object.keys(at.by_grade).map((g) => ({
    grade: g, base: base.by_grade[g].loss_rate, stressed: at.by_grade[g].loss_rate,
  }));
  const s = dash.stress;
  const sens = s?.sensitivity;
  const bt = s?.backtest;

  return (
    <>
      <p className="lede">
        What the 2015 book would lose if unemployment changed over the life of the loans. The link between unemployment
        and default was estimated on 2007–2014 loans, which include the 2008–09 recession.
      </p>
      <div className="grid">
        <section className="panel">
          <h2>Unemployment change over the next 24 months</h2>
          <div className="body slider">
            <input type="range" min={grid[0].d_unemp} max={grid[grid.length - 1].d_unemp} step="0.25" value={d}
              onChange={(e) => setD(Number(e.target.value))} aria-label="Unemployment change in percentage points" />
            <output className="num">{pp(at.d_unemp)}</output>
            <div className="presets">
              {PRESETS.map(([name, v]) => (
                <button key={name} aria-pressed={at.d_unemp === v} onClick={() => setD(v)}>{name}</button>
              ))}
            </div>
          </div>
          <div className="figures" style={{ marginTop: 20 }}>
            <div className="figure"><div className="label">Expected lifetime loss</div><div className="value num">{usdM(at.expected_loss_usd_m, 0)}</div><div className="note">{at.d_unemp === base.d_unemp ? "today's economy" : `${usdM(at.expected_loss_usd_m - base.expected_loss_usd_m, 0)} vs. today's economy`}</div></div>
            <div className="figure"><div className="label">Loss rate</div><div className="value num">{pct(at.loss_rate)}</div><div className="note">of principal, today {pct(base.loss_rate)}</div></div>
            <div className="figure"><div className="label">Average probability of default</div><div className="value num">{pct(at.mean_pd)}</div><div className="note">today {pct(base.mean_pd)}</div></div>
          </div>
        </section>

        <div className="grid two">
          <section className="panel">
            <h2>Loss rate across unemployment shocks</h2>
            <p className="sub">The dot is the shock selected above.</p>
            <div className="body">
              <LineChart data={grid} x="d_unemp" height={250} area
                series={[{ key: "loss_rate", name: "Loss rate", color: "var(--s1)" }]}
                xFormat={(v) => pp(v)} yFormat={(v, tip) => pct(v, tip ? 2 : 1)}
                tipTitle={(g) => `Unemployment ${pp(g.d_unemp)}`}
                markers={[{ x: at.d_unemp, y: at.loss_rate, label: "", color: "var(--s1)" }]}
                ariaLabel="Book loss rate by unemployment change" />
              <DataTable rows={grid.filter((g) => Number.isInteger(g.d_unemp))} columns={[
                { key: "d_unemp", name: "Unemployment change", format: pp },
                { key: "mean_pd", name: "Mean PD", align: "r", format: (v) => pct(v) },
                { key: "expected_loss_usd_m", name: "Expected loss", align: "r", format: (v) => usdM(v, 0) },
                { key: "loss_rate", name: "Loss rate", align: "r", format: (v) => pct(v, 2) },
              ]} />
            </div>
          </section>
          <section className="panel">
            <h2>Loss rate by grade</h2>
            <p className="sub">Today's economy compared with the selected shock.</p>
            <div className="body">
              <ColumnChart data={byGrade} cat="grade" height={250}
                series={[{ key: "base", name: "Today", color: "var(--s1)" }, { key: "stressed", name: `Unemployment ${pp(at.d_unemp)}`, color: "var(--s2)" }]}
                yFormat={(v) => pct(v, 1)} tipTitle={(g) => `Grade ${g}`}
                ariaLabel="Loss rate by grade, today and under the selected shock" />
              <DataTable rows={byGrade} columns={[
                { key: "grade", name: "Grade" },
                { key: "base", name: "Today", align: "r", format: (v) => pct(v) },
                { key: "stressed", name: "Selected shock", align: "r", format: (v) => pct(v) },
              ]} />
            </div>
          </section>
        </div>

        {sens && (
          <section className="panel">
            <h2>How the shock is modeled</h2>
            <p className="sub" style={{ maxWidth: "76ch" }}>
              Each 1 pp rise in unemployment multiplies the odds of default by {sens.odds_multiplier_per_pp.toFixed(2)},
              estimated with a binomial GLM on {sens.cohorts?.toLocaleString()} issue-month × credit-score cohorts.
              {bt && ` Backtest on 2015: the model expected ${usdM(bt.expected_usd_m, 0)} of losses against ${usdM(bt.actual_usd_m, 0)} actual (ratio ${bt.ratio.toFixed(2)}).`}
            </p>
          </section>
        )}
      </div>
    </>
  );
}
