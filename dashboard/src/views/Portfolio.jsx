import { DataTable, LineChart } from "../charts.jsx";
import { num, pct, usd, usdM } from "../format.js";

function Missing({ what, run }) {
  return <p className="empty">No {what} in this bundle yet. Run <code>{run}</code>, then <code>python -m api.export</code>.</p>;
}

function PolicyGrid({ segments }) {
  const grades = [...new Set(segments.map((s) => s.grade))].sort();
  const at = Object.fromEntries(segments.map((s) => [`${s.grade}${s.risk_band}`, s]));
  return (
    <>
      <div className="pgrid" role="table" aria-label="Funded segments by grade and risk band">
        <div />
        {Array.from({ length: 10 }, (_, i) => <div className="h" key={i}>{i + 1}</div>)}
        {grades.map((g) => (
          <div key={g} style={{ display: "contents" }}>
            <div className="g">{g}</div>
            {Array.from({ length: 10 }, (_, i) => {
              const s = at[`${g}${i + 1}`];
              if (!s) return <div key={i} />;
              const tip = `Grade ${g}, band ${i + 1}: ${s.approve ? "funded" : "declined"}\n${num(s.loans)} loans, ` +
                `mean PD ${pct(s.mean_pd)}\nExpected profit ${usdM(s.profit / 1e6, 2)}, realized ${usdM(s.realized / 1e6, 2)}`;
              return <div key={i} className={`c ${s.approve ? "yes" : "no"}`} title={tip} aria-label={tip} />;
            })}
          </div>
        ))}
      </div>
      <div className="key">
        <span><i className="sw" style={{ background: "var(--s1)" }} /> Funded</span>
        <span><i className="sw" /> Declined</span>
        <span className="hint">Columns are risk bands 1 (safest) to 10. Hover a cell for its loans and profit.</span>
      </div>
    </>
  );
}

export default function Portfolio({ dash }) {
  const { model, policy, experiment } = dash;
  const perf = model?.performance ?? [];
  const gbm = perf.find((r) => r.model === "GBM");
  const bench = perf.find((r) => r.model === "Sub-grade benchmark");
  const chosen = policy?.policies.find((p) => p.policy === "Optimized");
  const r = experiment?.readout;

  return (
    <>
      <p className="lede">
        How well the model ranks risk on loans it never saw (2015), which applicants the optimized policy funds, and
        what that policy earned when the loans played out.
      </p>
      <div className="grid">
        <section className="panel">
          <div className="figures">
            {gbm && <div className="figure"><div className="label">Out-of-time AUC</div><div className="value num">{gbm.auc.toFixed(3)}</div><div className="note">{bench ? `Lending Club's own grade: ${bench.auc.toFixed(3)}` : "2015 loans"}</div></div>}
            {gbm && <div className="figure"><div className="label">KS statistic</div><div className="value num">{gbm.ks.toFixed(3)}</div><div className="note">Gini {gbm.gini.toFixed(3)}</div></div>}
            {chosen && <div className="figure"><div className="label">Realized profit, optimized policy</div><div className="value num">{usdM(chosen.realized_profit_usd_m)}</div><div className="note">{pct(chosen.volume_share, 0)} of principal funded</div></div>}
            {r && <div className="figure"><div className="label">Champion/challenger uplift</div><div className="value num">{usd(r.uplift)}</div><div className="note">per applicant, 95% CI {usd(r.uplift_ci_low)} to {usd(r.uplift_ci_high)}</div></div>}
          </div>
          {experiment && <p className="hint" style={{ marginTop: 14 }}>Experiment decision: {experiment.decision}.</p>}
        </section>

        <div className="grid two">
          <section className="panel">
            <h2>Model performance on 2015 loans</h2>
            <p className="sub">Higher AUC and KS mean better ranking of who defaults.</p>
            <div className="body scroll">
              {perf.length ? (
                <table>
                  <thead><tr><th>Model</th><th className="r">AUC</th><th className="r">KS</th><th className="r">Gini</th><th className="r">Brier</th></tr></thead>
                  <tbody>
                    {perf.map((p) => (
                      <tr key={p.model} className={p.model === "GBM" ? "chosen" : ""}>
                        <td>{p.model === "GBM" ? "LightGBM (deployed)" : p.model}</td>
                        <td className="r">{p.auc.toFixed(3)}</td><td className="r">{p.ks.toFixed(3)}</td>
                        <td className="r">{p.gini.toFixed(3)}</td><td className="r">{p.brier.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <Missing what="model results" run="python -m models.train" />}
            </div>
          </section>

          <section className="panel">
            <h2>Three approval policies on the 2015 book</h2>
            <p className="sub">
              {policy ? `Constraints: severe-recession loss at most ${pct(policy.constraints.max_severe_loss_rate, 0)} of funded principal, at least ${pct(policy.constraints.min_volume_share, 0)} of volume, grades E–G at most ${pct(policy.constraints.max_risky_share, 0)}.` : ""}
            </p>
            <div className="body scroll">
              {policy ? (
                <table>
                  <thead><tr><th>Policy</th><th className="r">Volume</th><th className="r">Severe loss</th><th className="r">Expected profit</th><th className="r">Realized</th><th>Meets limits</th></tr></thead>
                  <tbody>
                    {policy.policies.map((p) => (
                      <tr key={p.policy} className={p.policy === "Optimized" ? "chosen" : ""}>
                        <td>{p.policy}</td><td className="r">{pct(p.volume_share, 0)}</td><td className="r">{pct(p.severe_loss_rate)}</td>
                        <td className="r">{usdM(p.expected_profit_usd_m)}</td><td className="r">{usdM(p.realized_profit_usd_m)}</td>
                        <td>{p.meets_constraints === "yes" ? "Yes" : "No"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <Missing what="policy results" run="python -m optimize.run" />}
            </div>
          </section>
        </div>

        {policy && (
          <div className="grid two">
            <section className="panel">
              <h2>Which segments the policy funds</h2>
              <p className="sub">Each cell is a grade and risk-band segment, chosen by mixed-integer optimization.</p>
              <div className="body"><PolicyGrid segments={policy.segments} /></div>
            </section>
            <section className="panel">
              <h2>Profit at each recession-loss budget</h2>
              <p className="sub">Re-solving the policy with a looser or tighter severe-loss limit. The dashed line is the limit in use.</p>
              <div className="body">
                <LineChart
                  data={policy.frontier} x="severe_loss_budget" height={250}
                  series={[
                    { key: "expected_profit_usd_m", name: "Expected (model)", color: "var(--s1)" },
                    { key: "realized_profit_usd_m", name: "Realized (2015 outcomes)", color: "var(--s2)" },
                  ]}
                  xFormat={(v) => pct(v, 1)} yFormat={(v, tip) => (tip ? usdM(v) : `$${v}M`)}
                  tipTitle={(d) => `Loss budget ${pct(d.severe_loss_budget, 1)}, volume ${pct(d.volume_share, 0)}`}
                  vrefs={[{ x: policy.constraints.max_severe_loss_rate, label: "In use" }]}
                  ariaLabel="Expected and realized profit by severe-loss budget"
                />
                <DataTable rows={policy.frontier} columns={[
                  { key: "severe_loss_budget", name: "Loss budget", align: "r", format: (v) => pct(v, 1) },
                  { key: "volume_share", name: "Volume", align: "r", format: (v) => pct(v, 0) },
                  { key: "expected_profit_usd_m", name: "Expected", align: "r", format: (v) => usdM(v) },
                  { key: "realized_profit_usd_m", name: "Realized", align: "r", format: (v) => usdM(v) },
                ]} />
              </div>
            </section>
          </div>
        )}
      </div>
    </>
  );
}
