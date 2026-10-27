const STATUS = {
  PASS: { label: "Pass", color: "var(--good)", icon: "✓" },
  WARN: { label: "Warning", color: "var(--warning)", icon: "!" },
  FAIL: { label: "Fail", color: "var(--critical)", icon: "✕" },
  "N/A": { label: "Not run", color: "var(--muted)", icon: "–" },
};

export function Status({ value }) {
  const s = STATUS[value] ?? STATUS["N/A"];
  return (
    <span className="status">
      <i style={{ background: s.color }} aria-hidden="true" />
      <span aria-hidden="true">{s.icon}</span> {s.label}
    </span>
  );
}

export default function Controls({ dash }) {
  const g = dash.governance;
  if (!g) {
    return <div className="panel"><p className="empty">No control results in this bundle yet. Run <code>python -m governance.run</code>, then <code>python -m api.export</code>.</p></div>;
  }
  const counts = Object.fromEntries(Object.keys(STATUS).map((k) => [k, g.controls.filter((c) => c.status === k).length]));
  const order = { FAIL: 0, WARN: 1, PASS: 2, "N/A": 3 };
  const controls = [...g.controls].sort((a, b) => order[a.status] - order[b.status] || a.id.localeCompare(b.id));

  return (
    <>
      <p className="lede">
        Every control in the model risk register, tested automatically against the artifacts this platform produced,
        and the incidents the controls have raised so far.
      </p>
      <div className="grid">
        <section className="panel">
          <div className="figures">
            <div className="figure"><div className="label">Controls passing</div><div className="value num">{counts.PASS} of {g.controls.length}</div></div>
            <div className="figure"><div className="label">Warnings</div><div className="value num">{counts.WARN}</div></div>
            <div className="figure"><div className="label">Failures</div><div className="value num">{counts.FAIL}</div></div>
            <div className="figure"><div className="label">Open incidents</div><div className="value num">{g.incidents.filter((i) => i.status === "open").length} of {g.incidents.length}</div></div>
          </div>
        </section>
        <section className="panel">
          <h2>Control register</h2>
          <div className="body scroll">
            <table>
              <thead><tr><th>ID</th><th>Risk</th><th>Control</th><th>Status</th><th>Observed</th></tr></thead>
              <tbody>
                {controls.map((c) => (
                  <tr key={c.id}>
                    <td className="num">{c.id}</td><td>{c.risk}</td><td>{c.control}</td>
                    <td><Status value={c.status} /></td><td>{c.observed}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        {g.incidents.length > 0 && (
          <section className="panel">
            <h2>Incident log</h2>
            <div className="body scroll">
              <table>
                <thead><tr><th>ID</th><th>Issue</th><th>Control</th><th>Severity</th><th>Status</th></tr></thead>
                <tbody>
                  {g.incidents.map((i) => (
                    <tr key={i.id}>
                      <td className="num">{i.id}</td><td>{i.title}</td><td className="num">{i.control}</td>
                      <td>{i.severity}</td><td>{i.status === "open" ? "Open" : "Closed"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </div>
    </>
  );
}
