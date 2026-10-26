"""Module 7: run every control, log incidents, and regenerate the model card.

Outputs
  reports/controls_report.md      register with this run's results, plus the incident log
  reports/controls_results.json   machine-readable results
  governance/incidents.json       incident log; a new FAIL opens an incident automatically
  docs/model_card.md              model card built from the current results

Usage:
    python -m governance.run
    python -m governance.run --strict      # exit with code 1 if any control fails (for CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from governance.controls import FAIL, NA, PASS, WARN, Context, run_controls
from models import features as F
from models.train import md_table
from pipeline import config

INCIDENTS = config.ROOT / "governance" / "incidents.json"


def update_incidents(rows: list[dict], path: Path = INCIDENTS, today: str | None = None) -> list[dict]:
    incidents = json.loads(path.read_text()) if path.exists() else []
    open_controls = {i["control"] for i in incidents if i["status"] == "open"}
    n = max([int(i["id"].split("-")[1]) for i in incidents] + [0])
    for r in rows:
        if r["status"] == FAIL and r["id"] not in open_controls:
            n += 1
            incidents.append({
                "id": f"INC-{n:03d}", "opened": today or date.today().isoformat(), "closed": None,
                "severity": "high", "control": r["id"], "title": f"Control {r['id']} failed: {r['risk']}",
                "detection": r["observed"], "root_cause": "To be investigated", "remediation": "To be defined",
                "outcome": None, "status": "open"})
            open_controls.add(r["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(incidents, indent=2) + "\n")
    return incidents


def write_controls_report(path: Path, rows: list[dict], incidents: list[dict]) -> None:
    counts = {s: sum(r["status"] == s for r in rows) for s in (PASS, WARN, FAIL, NA)}
    open_inc = [i for i in incidents if i["status"] == "open"]
    df = pd.DataFrame(rows)
    order = {FAIL: 0, WARN: 1, NA: 2, PASS: 3}
    attention = df[df["status"].isin([FAIL, WARN])].sort_values("status", key=lambda s: s.map(order))
    lines = [
        "# Model risk controls report",
        "",
        f"Run {date.today().isoformat()}: **{counts[PASS]} of {len(rows)} controls pass**, {counts[WARN]} need review, "
        f"{counts[FAIL]} fail, {counts[NA]} not yet run. {len(open_inc)} incident(s) open.",
        "",
        "## Needs attention",
        "",
        md_table(attention[["id", "risk", "status", "observed", "owner"]]) if len(attention) else "Nothing.",
        "",
        "## Risk and controls register",
        "",
        md_table(df[["id", "category", "risk", "control", "kind", "threshold", "status", "observed", "owner", "frequency"]]),
        "",
        "## Incident log",
        "",
        md_table(pd.DataFrame(incidents)[["id", "opened", "closed", "severity", "control", "title", "status"]])
        if incidents else "No incidents.",
        "",
    ]
    for i in incidents:
        lines += [f"### {i['id']}: {i['title']}", "",
                  f"- **Detected:** {i['detection']}",
                  f"- **Root cause:** {i['root_cause']}",
                  f"- **Remediation:** {i['remediation']}",
                  f"- **Outcome:** {i['outcome'] or 'pending'} · **Status:** {i['status']}", ""]
    path.write_text("\n".join(lines))


def write_model_card(path: Path, ctx: Context, rows: list[dict]) -> None:
    m = ctx.json("reports/model_metrics.json") or {}
    s = ctx.json("reports/stress_results.json") or {}
    perf = pd.DataFrame(m.get("performance", []))
    cols = [c for c in ("model", "auc", "gini", "ks", "brier", "mean_pd", "default_rate", "n") if c in perf.columns]
    oot = perf.loc[perf["split"] == "oot", cols] if len(perf) else pd.DataFrame()
    status = {r["id"]: r["status"] for r in rows}
    p = config.SPLIT_PERIODS
    lines = [
        "# Model card: probability-of-default model (LightGBM)",
        "",
        f"Generated {date.today().isoformat()} from the current results by `python -m governance.run`.",
        "",
        "## Purpose",
        "",
        "- **Intended use:** rank and estimate the lifetime default probability of 36-month unsecured personal-loan "
        "applicants, as input to expected-loss stress testing (Module 3) and credit-policy decisions (Module 4).",
        "- **Not for:** 60-month loans, other products or lenders without revalidation, pricing on its own, or any use "
        "involving protected attributes.",
        "- **Decision support only:** policy changes go through a champion/challenger test (Module 5).",
        "",
        "## Data",
        "",
        f"- Lending Club accepted loans, 36-month term, final outcome known. Train {p['train'][0]} to {p['train'][1]}, "
        f"validation {p['valid'][0]} to {p['valid'][1]}, out-of-time test {p['oot'][0]} to {p['oot'][1]}.",
        f"- {len(F.FEATURES)} application-time inputs ({len(F.NUMERIC)} numeric, {len(F.CATEGORICAL)} categorical). "
        f"Excluded by design: {', '.join(F.EXCLUDED)} (outputs of Lending Club's own pricing).",
        "- Target: charged off or default = 1; fully paid = 0.",
        "",
        "## Performance (out-of-time)",
        "",
        md_table(oot, {"auc": ".3f", "gini": ".3f", "ks": ".3f", "brier": ".4f", "mean_pd": ".2%",
                       "default_rate": ".2%", "n": ","}) if len(oot) else "Not yet trained.",
        "",
        f"- Stability (PSI, train vs. out-of-time): {m.get('psi', {}).get('GBM', float('nan')):.3f}.",
        f"- Trees: {m.get('gbm_trees', 'n/a')} (early-stopped on validation).",
        "",
        "## Design safeguards",
        "",
        f"- Monotone constraints on {len(F.MONOTONE)} inputs (e.g. higher credit score can never raise PD); "
        f"verified by control C-07 ({status.get('C-07', 'n/a')}).",
        f"- Top-3 SHAP reason codes for every loan, for adverse-action notices; control C-08 ({status.get('C-08', 'n/a')}).",
        f"- Post-issue fields kept out of the model table; control C-02 ({status.get('C-02', 'n/a')}).",
        "",
        "## Use in stress testing",
        "",
        (f"- Each 1-point rise in unemployment multiplies default odds by "
         f"{s['sensitivity']['odds_multiplier_per_pp']:.2f}; out-of-time loss backtest ratio "
         f"{s['backtest']['ratio']:.2f} (control C-09: {status.get('C-09', 'n/a')}).") if s else "- Not yet run.",
        "",
        "## Known limitations",
        "",
        "- Trained on loans Lending Club approved; applicants it declined are unseen (no reject inference).",
        "- One recession in the macro data; sensitivity estimates rest mostly on 2007-2008 vintages.",
        "- Profit estimates built on this model overstate realized profit (incident INC-003, control C-12).",
        "- Protected attributes are absent, so fair-lending review uses geography as a proxy (control C-14).",
        "",
        "## Monitoring",
        "",
        md_table(pd.DataFrame(rows)[["id", "control", "frequency", "status"]]),
        "",
        "## Ownership",
        "",
        "- Model owner and developer: Akhmad Dyussembayev. Independent validation: not yet performed.",
        "",
    ]
    path.write_text("\n".join(lines))


def run(root: Path = config.ROOT, today: str | None = None) -> list[dict]:
    ctx = Context(root)
    rows = run_controls(ctx)
    incidents = update_incidents(rows, root / "governance" / "incidents.json", today)
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    write_controls_report(reports / "controls_report.md", rows, incidents)
    (reports / "controls_results.json").write_text(json.dumps(rows, indent=2))
    (root / "docs").mkdir(exist_ok=True)
    write_model_card(root / "docs" / "model_card.md", ctx, rows)

    width = max(len(r["id"]) for r in rows)
    for r in rows:
        print(f"  {r['id']:<{width}}  {r['status']:<4}  {r['observed'][:95]}")
    counts = {s: sum(r["status"] == s for r in rows) for s in (PASS, WARN, FAIL, NA)}
    print(f"\n{counts[PASS]} pass · {counts[WARN]} review · {counts[FAIL]} fail · {counts[NA]} n/a · "
          f"{sum(i['status'] == 'open' for i in incidents)} open incident(s)")
    print(f"Report: {reports / 'controls_report.md'} · Model card: {root / 'docs' / 'model_card.md'}")
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--strict", action="store_true", help="exit 1 if any control fails")
    a = p.parse_args()
    rows = run()
    if a.strict and any(r["status"] == FAIL for r in rows):
        sys.exit(1)


if __name__ == "__main__":
    main()
