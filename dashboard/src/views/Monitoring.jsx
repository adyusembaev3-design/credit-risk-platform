import { DataTable, LineChart } from "../charts.jsx";
import { compact, num, pct } from "../format.js";

const PSI_ALERT = 0.2;
const RULES = {
  score_psi: "predicted PD stability", approval_rate_drop: "approval rate", calibration: "calibration",
  latency_p95: "latency", "feature_psi:fico_mid": "credit score stability", "feature_psi:dti": "debt-to-income stability",
  "feature_psi:bc_util": "bankcard utilization stability", "feature_psi:acc_open_past_24mths": "new accounts stability",
  "feature_psi:annual_inc": "income stability", "feature_psi:loan_to_income": "loan-to-income stability",
};

export default function Monitoring({ dash }) {
  const m = dash.monitoring;
  if (!m) {
    return <div className="panel"><p className="empty">No monitoring run in this bundle yet. Run <code>python -m streaming.run</code>, then <code>python -m api.export</code>.</p></div>;
  }
  const tl = m.timeline ?? [];
  const drift = m.drift_at ? [{ x: m.drift_at, label: "Riskier channel starts" }] : [];
  const fa = m.first_alert;

  return (
    <>
      <p className="lede">
        The 2015 book replayed as a live stream of applications. Halfway through, a riskier acquisition channel was
        switched on to test whether the monitors catch it, and whether anything fired before it.
      </p>
      <div className="grid">
        <section className="panel">
          <div className="figures">
            {fa && <div className="figure"><div className="label">Drift detected after</div><div className="value num">{num(fa.delay)} applications</div><div className="note">by the {RULES[fa.rule] ?? fa.rule} monitor</div></div>}
            <div className="figure"><div className="label">False alarms before drift</div><div className="value num">{m.false_alarms_before_drift}</div><div className="note">in {num(m.drift_at ?? m.applications)} clean applications</div></div>
            <div className="figure"><div className="label">Scoring throughput</div><div className="value num">{num(m.throughput_per_s)}/s</div><div className="note">p95 latency {m.latency_p95_ms?.toFixed(2)} ms per application</div></div>
            {m.approval_rate_after != null && <div className="figure"><div className="label">Approval rate</div><div className="value num">{pct(m.approval_rate_before)} to {pct(m.approval_rate_after)}</div><div className="note">before and after the drift</div></div>}
          </div>
        </section>

        {tl.length > 0 ? (
          <div className="grid two">
            <section className="panel">
              <h2>Population stability</h2>
              <p className="sub">PSI of the last 5,000 applications against the training population. Above {PSI_ALERT.toFixed(2)} raises an alert.</p>
              <div className="body">
                <LineChart data={tl} x="processed" height={250}
                  series={[
                    { key: "score_psi", name: "Predicted PD", color: "var(--s1)" },
                    { key: "psi_fico_mid", name: "Credit score", color: "var(--s2)" },
                    { key: "psi_bc_util", name: "Bankcard utilization", color: "var(--s3)" },
                  ]}
                  xFormat={compact} yFormat={(v) => (v == null ? "–" : v.toFixed(2))}
                  tipTitle={(r) => `After ${num(r.processed)} applications`}
                  hrefs={[{ y: PSI_ALERT, label: "Alert" }]} vrefs={drift}
                  ariaLabel="Population stability index over the stream" />
              </div>
            </section>
            <section className="panel">
              <h2>Approval rate</h2>
              <p className="sub">Share of the last 5,000 applications the policy approved.</p>
              <div className="body">
                <LineChart data={tl} x="processed" height={250} yMin={0} yMax={1}
                  series={[{ key: "approval_rate", name: "Approval rate", color: "var(--s1)" }]}
                  xFormat={compact} yFormat={(v) => pct(v, 0)}
                  tipTitle={(r) => `After ${num(r.processed)} applications`}
                  vrefs={drift} ariaLabel="Rolling approval rate over the stream" />
              </div>
            </section>
          </div>
        ) : null}
        {tl.length > 0 && (
          <section className="panel">
            <h2>Monitor readings</h2>
            <DataTable label="Every 5,000 applications" rows={tl.filter((r) => r.processed % 5000 === 0)} columns={[
              { key: "processed", name: "Applications", align: "r", format: (v) => num(v) },
              { key: "score_psi", name: "PD PSI", align: "r", format: (v) => v?.toFixed(3) },
              { key: "psi_fico_mid", name: "Score PSI", align: "r", format: (v) => v?.toFixed(3) },
              { key: "psi_bc_util", name: "Utilization PSI", align: "r", format: (v) => v?.toFixed(3) },
              { key: "approval_rate", name: "Approval", align: "r", format: (v) => pct(v) },
              { key: "mean_pd", name: "Mean PD", align: "r", format: (v) => pct(v, 2) },
            ]} />
          </section>
        )}
      </div>
    </>
  );
}
