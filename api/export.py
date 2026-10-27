"""Module 9: package everything the API serves into one small folder (api/bundle/).

The API never touches the raw data or the 283K-loan parquet files. This step reads
the outputs of Modules 2-8 once and writes:

  lgbm_model.txt     the PD model (Module 2)
  scorer.json        stress shift, risk-band edges, policy table, categories (Modules 3-4)
  stress_grid.json   book loss rate at every unemployment change from -2 to +8 pp (Module 3)
  samples.json       500 random 2015 applications, to try the API with
  dashboard.json     headline results of every module, for the dashboard

Usage:
    python -m api.export
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from models import features as F
from pipeline import config
from stress.glm import expit, logit

BUNDLE = Path(__file__).resolve().parent / "bundle"
SCENARIOS = {"Baseline": 0.0, "Adverse": 2.5, "Severe": 5.0}   # same as stress/run.py
GRID = np.round(np.arange(-2.0, 8.0001, 0.25), 2)
POLICY_COLS = ["grade", "risk_band", "approve", "loans", "exposure", "mean_pd", "profit", "profit_severe",
               "severe_loss", "realized", "risky"]


def _json(path: Path):
    if not path.exists():
        print(f"  (missing {path.name}: that part of the dashboard will be empty)")
        return None
    return json.loads(path.read_text())


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> JSON-safe records (NaN -> None, numpy -> python)."""
    return json.loads(df.to_json(orient="records", date_format="iso"))


def stress_grid(book: pd.DataFrame, beta: float, d_train: float, grid=GRID) -> list[dict]:
    base = logit(book["pd_gbm"].to_numpy())
    amt, lgd = book["loan_amnt"].to_numpy(float), book["lgd"].to_numpy(float)
    grades = book["grade"].to_numpy()
    rows = []
    for d in grid:
        p = expit(base + beta * (d - d_train))
        el = p * lgd * amt
        row = {"d_unemp": float(d), "mean_pd": float(p.mean()), "expected_loss_usd_m": float(el.sum() / 1e6),
               "loss_rate": float(el.sum() / amt.sum()), "by_grade": {}}
        for g in sorted(set(grades)):
            m = grades == g
            row["by_grade"][g] = {"mean_pd": float(p[m].mean()), "loss_rate": float(el[m].sum() / amt[m].sum())}
        rows.append(row)
    return rows


def sample_applications(loans: pd.DataFrame, n: int, seed: int) -> list[dict]:
    from streaming.source import load_applications

    apps = load_applications(loans)
    s = apps.sample(min(n, len(apps)), random_state=seed)
    s["issue_date"] = s["issue_date"].astype(str).str[:10]
    return _records(s[["loan_id", "issue_date", "grade", "is_default"] + F.FEATURES])


def build_dashboard(rep: Path, seg: pd.DataFrame) -> dict:
    model = _json(rep / "model_metrics.json")
    stress = _json(rep / "stress_results.json")
    opt = _json(rep / "optimization_results.json")
    mon = _json(rep / "monitoring_results.json")
    timeline = _json(rep / "monitoring_timeline.json")
    exp = _json(rep / "experiment_results.json")
    controls = _json(rep / "controls_results.json")
    gov_dir = config.ROOT / "governance" / "incidents.json"
    incidents = _json(gov_dir) or []
    return {
        "model": None if model is None else {
            "performance": [r for r in model["performance"] if r["split"] == "oot"],
            "psi": model.get("psi"), "calibration_oot": model.get("calibration_oot")},
        "stress": None if stress is None else {k: stress[k] for k in (
            "sensitivity", "d_unemp_train", "scenarios", "backtest", "lgd_by_grade") if k in stress},
        "policy": None if opt is None else {
            "constraints": opt["constraints"], "policies": opt["policies"], "frontier": opt["frontier"],
            "segments": _records(seg[[c for c in POLICY_COLS if c in seg.columns]])},
        "monitoring": None if mon is None else {**mon, "timeline": timeline or []},
        "experiment": None if exp is None else {"decision": exp["decision"], "readout": exp["readout"],
                                                "design": exp.get("design")},
        "governance": None if controls is None else {
            "controls": controls,
            "incidents": [{k: i.get(k) for k in ("id", "title", "control", "status", "severity")} for i in incidents]},
    }


def export(root: Path = config.ROOT, out: Path = BUNDLE, n_samples: int = 500, seed: int = 7) -> dict:
    art, rep, proc = root / "models" / "artifacts", root / "reports", root / "data" / "processed"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(art / "lgbm_model.txt", out / "lgbm_model.txt")
    version = hashlib.sha256((art / "lgbm_model.txt").read_bytes()).hexdigest()[:12]

    stress = json.loads((rep / "stress_results.json").read_text())
    beta, d_train = stress["sensitivity"]["beta_per_pp"], stress["d_unemp_train"]
    book = pd.read_parquet(proc / "stressed_book.parquet", columns=["grade", "loan_amnt", "pd_gbm", "lgd", "pd_baseline"])
    edges = np.quantile(book["pd_baseline"], np.linspace(0, 1, 11)[1:-1])     # same as streaming/scorer.py
    seg = pd.read_parquet(proc / "policy_segments.parquet")

    scorer = {"model_version": version, "beta_per_pp": beta, "d_unemp_train": d_train,
              "band_edges": edges.tolist(), "scenarios": SCENARIOS,
              "categories": json.loads((art / "gbm_categories.json").read_text()),
              "policy": _records(seg[["grade", "risk_band", "approve"]]),
              "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (out / "scorer.json").write_text(json.dumps(scorer, indent=1))
    (out / "stress_grid.json").write_text(json.dumps(stress_grid(book, beta, d_train)))

    loans = pd.read_parquet(proc / "loans_model.parquet")
    (out / "samples.json").write_text(json.dumps(sample_applications(loans, n_samples, seed)))
    (out / "dashboard.json").write_text(json.dumps(build_dashboard(rep, seg), default=str))

    size = sum(p.stat().st_size for p in out.iterdir()) / 1e6
    print(f"Bundle: {out}  ({size:.1f} MB, model version {version}, {len(seg)} policy segments, "
          f"{min(n_samples, len(loans))} sample applications)")
    return scorer


if __name__ == "__main__":
    export()
