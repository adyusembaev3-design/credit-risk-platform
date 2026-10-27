import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { num, pct, pp } from "../format.js";

// The inputs an underwriter would recognise; the other bureau fields come from the applicant's file unchanged.
const GROUPS = [
  { title: "Credit profile", fields: [
    { key: "fico_mid", label: "Credit score (FICO)", step: 1 },
    { key: "bc_util", label: "Bankcard utilization, %", step: 1 },
    { key: "revol_util", label: "Revolving utilization, %", step: 1 },
    { key: "acc_open_past_24mths", label: "Accounts opened, 24 months", step: 1 },
    { key: "inq_last_6mths", label: "Credit inquiries, 6 months", step: 1 },
    { key: "delinq_2yrs", label: "Delinquencies, 2 years", step: 1 },
  ] },
  { title: "Capacity", fields: [
    { key: "annual_inc", label: "Annual income, $", step: 1000 },
    { key: "dti", label: "Debt-to-income, %", step: 0.1 },
    { key: "emp_length_years", label: "Years employed", step: 1 },
    { key: "home_ownership", label: "Housing", categorical: true },
  ] },
  { title: "Loan", fields: [
    { key: "grade", label: "Lending Club grade", options: ["A", "B", "C", "D", "E", "F", "G"] },
    { key: "loan_amnt", label: "Amount, $", step: 500 },
    { key: "purpose", label: "Purpose", categorical: true },
  ] },
];
const SHOWN = new Set(GROUPS.flatMap((g) => g.fields.map((f) => f.key)));
const SCENARIO_NOTE = { Baseline: "today's economy", Adverse: "unemployment +2.5 pp", Severe: "unemployment +5 pp" };

function bandPosition(p, edges) {
  // Bands are deciles of baseline PD; place a PD inside its band so the pin moves smoothly.
  const e = [Math.max(0, edges[0] - (edges[1] - edges[0])), ...edges, Math.min(1, edges[8] + 3 * (edges[8] - edges[7]))];
  let b = 0;
  while (b < 9 && p >= e[b + 1]) b++;
  const f = Math.min(0.96, Math.max(0.04, (p - e[b]) / (e[b + 1] - e[b] || 1)));
  return { band: b + 1, left: ((b + f) / 10) * 100 };
}

function Ladder({ result, meta }) {
  const funded = new Set(meta.policy.filter((r) => r.grade === result.grade && r.approve).map((r) => r.risk_band));
  const pins = Object.entries(result.pd_by_scenario).map(([name, p]) => ({ name, p, ...bandPosition(p, meta.band_edges) }));
  return (
    <div className="ladder" aria-label="Where the applicant sits among the ten risk bands">
      <div className="cells">
        {Array.from({ length: 10 }, (_, i) => (
          <div key={i} className={`cell ${funded.has(i + 1) ? "" : "declined"}`}>{i + 1}</div>
        ))}
        {pins.map((pin) => (
          <div key={pin.name} className={`pin ${pin.name === "Baseline" ? "" : "ghost"}`} style={{ left: `${pin.left}%` }}
            title={`${pin.name}: ${pct(pin.p)} (band ${pin.band})`} />
        ))}
      </div>
      <div className="axis"><span>Lowest risk</span><span>Highest risk</span></div>
      <div className="key">
        <span><i className="sw" /> Funded for grade {result.grade}</span>
        <span><i className="sw declined" /> Declined for grade {result.grade}</span>
      </div>
      <table style={{ marginTop: 14 }}>
        <thead>
          <tr><th>Economy</th><th className="r">Probability of default</th><th className="r">Risk band</th></tr>
        </thead>
        <tbody>
          {pins.map((pin) => (
            <tr key={pin.name}>
              <td>{pin.name === "Baseline" ? "● " : "○ "}{pin.name} <span className="hint">({SCENARIO_NOTE[pin.name] ?? pp(meta.scenarios[pin.name])})</span></td>
              <td className="r">{pct(pin.p)}</td>
              <td className="r">{pin.band}{funded.has(pin.band) ? "" : " (declined)"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Decide({ meta }) {
  const [original, setOriginal] = useState(null);
  const [app, setApp] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const seed = useRef(1);
  const timer = useRef(null);

  const load = async () => {
    setError(null);
    try {
      const a = await api.sample(seed.current++);
      setOriginal(a);
      setApp(a);
    } catch (e) { setError(e.message); }
  };
  useEffect(() => { load(); }, []);

  useEffect(() => {                                     // re-score shortly after every edit
    if (!app) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      const { issue_date, is_default, ...payload } = app;
      try { setResult(await api.score(payload)); setError(null); } catch (e) { setError(e.message); }
    }, 220);
    return () => clearTimeout(timer.current);
  }, [app]);

  const set = (key, raw, numeric) => {
    setApp((a) => {
      const next = { ...a, [key]: numeric ? (raw === "" ? null : Number(raw)) : raw || null };
      if (key === "loan_amnt" || key === "annual_inc") {   // derived exactly as in the pipeline SQL
        next.loan_to_income = next.annual_inc > 0 && next.loan_amnt != null ? next.loan_amnt / next.annual_inc : null;
      }
      return next;
    });
  };
  const edited = app && original && GROUPS.some((g) => g.fields.some((f) => app[f.key] !== original[f.key]));

  if (!app) return <div className="panel">{error ? <p className="error">{error}</p> : <p className="empty">Loading an applicant…</p>}</div>;

  return (
    <>
      <p className="lede">
        A real application from the 2015 book. Change any input and the decision updates: the model's probability of
        default, the risk band, the approval policy for that grade, and the reasons a declined applicant would be given.
      </p>
      <div className="grid decide">
        <section className="panel">
          <h2>Application {String(app.loan_id).replace(/^app-/, "")}</h2>
          <p className="sub">{edited ? "Edited from the original file." : `Issued ${app.issue_date ?? "2015"}.`}</p>
          <div className="body">
            {GROUPS.map((g) => (
              <fieldset className="fieldset" key={g.title}>
                <legend>{g.title}</legend>
                <div className="fields">
                  {g.fields.map((f) => {
                    const opts = f.options ?? (f.categorical ? meta.features.categorical[f.key] : null);
                    const id = `f-${f.key}`;
                    return (
                      <div className="field" key={f.key}>
                        <label htmlFor={id}>{f.label}</label>
                        {opts ? (
                          <select id={id} value={app[f.key] ?? ""} onChange={(e) => set(f.key, e.target.value, false)}>
                            {f.categorical && <option value="">Not given</option>}
                            {opts.map((o) => <option key={o} value={o}>{o.replaceAll("_", " ")}</option>)}
                          </select>
                        ) : (
                          <input id={id} type="number" step={f.step} value={app[f.key] ?? ""}
                            onChange={(e) => set(f.key, e.target.value, true)} />
                        )}
                      </div>
                    );
                  })}
                </div>
              </fieldset>
            ))}
            <div className="actions">
              <button className="btn primary" onClick={load}>Load another applicant</button>
              {edited && <button className="btn" onClick={() => setApp(original)}>Undo my changes</button>}
            </div>
            <p className="hint" style={{ marginTop: 10 }}>
              {meta.features.numeric.filter((k) => !SHOWN.has(k)).length + 1} more bureau fields from this
              applicant's file are sent unchanged. State of residence is not an input (fair-lending review).
            </p>
          </div>
        </section>

        <section className="panel" aria-live="polite">
          {error && <p className="error">Scoring failed: {error}</p>}
          {!result ? <p className="empty">Scoring…</p> : (
            <>
              <div className={`verdict ${result.decision}`}>
                <span className="word">{result.decision === "approve" ? "Approve" : "Decline"}</span>
                <span className="why">
                  Grade {result.grade}, risk band {result.risk_band} of 10. The optimized policy{" "}
                  {result.decision === "approve" ? "funds" : "does not fund"} this band for grade {result.grade}.
                </span>
              </div>
              <div className="figures" style={{ marginTop: 18 }}>
                <div className="figure"><div className="label">Probability of default</div><div className="value num">{pct(result.pd_baseline)}</div><div className="note">36-month loan, today's economy</div></div>
                {!edited && original.is_default != null && (
                  <div className="figure"><div className="label">What actually happened</div><div className="value">{original.is_default ? "Defaulted" : "Repaid"}</div><div className="note">This loan's real outcome</div></div>
                )}
              </div>
              <Ladder result={result} meta={meta} />
              <h3 style={{ fontSize: 14.5, marginTop: 22 }}>What raises this applicant's risk</h3>
              {result.reasons.length ? (
                <ol className="reasons">
                  {result.reasons.map((r, i) => (
                    <li key={r.feature}><span className="rank">{i + 1}</span><span>{r.text}<br /><span className="feat">{r.feature}{app[r.feature] != null ? ` = ${num(app[r.feature], Number.isInteger(app[r.feature]) ? 0 : 2)}` : " (missing)"}</span></span></li>
                  ))}
                </ol>
              ) : <p className="hint">No input raises this applicant's risk above the average applicant's.</p>}
              <p className="hint" style={{ marginTop: 14 }}>Model version {result.model_version}, scored in {result.latency_ms.toFixed(1)} ms.</p>
            </>
          )}
        </section>
      </div>
    </>
  );
}
