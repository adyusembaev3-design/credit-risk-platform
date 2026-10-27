import { useEffect, useState } from "react";
import { api } from "./api.js";
import Controls from "./views/Controls.jsx";
import Decide from "./views/Decide.jsx";
import Monitoring from "./views/Monitoring.jsx";
import Portfolio from "./views/Portfolio.jsx";
import Stress from "./views/Stress.jsx";

const TABS = [
  ["decide", "Decide an application"],
  ["portfolio", "Model and policy"],
  ["stress", "Recession stress"],
  ["monitoring", "Live monitoring"],
  ["controls", "Controls"],
];
const initialTab = () => {
  const h = window.location.hash.slice(1);
  return TABS.some(([k]) => k === h) ? h : "decide";
};

export default function App() {
  const [tab, setTab] = useState(initialTab);
  const [meta, setMeta] = useState(null);
  const [dash, setDash] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([api.meta(), api.dashboard()])
      .then(([m, d]) => { setMeta(m); setDash(d); })
      .catch((e) => setError(e.message));
    const onHash = () => setTab(initialTab());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = (k) => { window.location.hash = k; setTab(k); };
  const created = meta?.bundle_created_at ? new Date(meta.bundle_created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : null;

  return (
    <>
      <header className="top">
        <div className="brand">
          <img src="/favicon.svg" alt="" width="32" height="32" />
          <div>
            <h1>Credit Decision Console</h1>
            <p>Lending Club 36-month loans, 2013–2015</p>
          </div>
        </div>
        {meta && (
          <div className="version">
            Model <strong className="num">{meta.model_version}</strong>
            {created && <><br />Results exported {created}</>}
          </div>
        )}
      </header>
      <nav className="tabs" role="tablist" aria-label="Sections">
        {TABS.map(([k, label]) => (
          <button key={k} role="tab" className="tab" aria-selected={tab === k} onClick={() => go(k)}>{label}</button>
        ))}
      </nav>
      <main>
        {error ? (
          <div className="panel">
            <h2>The decision API isn't answering</h2>
            <p className="sub" style={{ marginTop: 6 }}>
              {error}. Start it from the repo root with <code>uvicorn api.main:app --port 8000</code>, then reload this page.
            </p>
          </div>
        ) : !meta || !dash ? (
          <p className="empty">Loading…</p>
        ) : (
          <>
            {tab === "decide" && <Decide meta={meta} />}
            {tab === "portfolio" && <Portfolio dash={dash} />}
            {tab === "stress" && <Stress dash={dash} />}
            {tab === "monitoring" && <Monitoring dash={dash} />}
            {tab === "controls" && <Controls dash={dash} />}
          </>
        )}
      </main>
    </>
  );
}
