"""Module 2: train and validate the probability-of-default (PD) models.

Three ways to rank risk, compared on the same loans:
  1. Benchmark   - Lending Club's own sub-grade (A1 safest ... G5 riskiest)
  2. Scorecard   - logistic regression on weight-of-evidence bins, with points
  3. GBM         - LightGBM with monotone constraints and SHAP reason codes

Trained Jan 2013-Jun 2014, early-stopped on Jul-Dec 2014, tested out-of-time on 2015
(periods set in pipeline/config.py; pre-2013 loans lack the extended bureau fields).

Usage:
    python -m models.train
    python -m models.train --sample-frac 0.2 --no-mlflow     # quick run
"""

from __future__ import annotations

import argparse
import json
import time
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import PercentFormatter  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import roc_curve  # noqa: E402

from models import features as F  # noqa: E402
from models.metrics import calibration_table, psi, summarize  # noqa: E402
from models.reason_codes import mean_abs_contribution, top_reasons  # noqa: E402
from models.woe import Scorecard  # noqa: E402
from pipeline import config  # noqa: E402

ARTIFACTS = config.ROOT / "models" / "artifacts"
SPLITS = config.MODEL_SPLITS  # 'history' loans (pre-2013) lack bureau fields and are not modeled


def period(split: str) -> str:
    """Human-readable issue period of a split, e.g. 'Jan 2013–Jun 2014'."""
    lo, hi = (pd.Timestamp(d) for d in config.SPLIT_PERIODS[split])
    return f"{lo:%b %Y}–{hi:%b %Y}" if (lo.year, lo.month) != (hi.year, hi.month) else f"{lo:%b %Y}"


# --- data ----------------------------------------------------------------------
def load(path: Path, sample_frac: float | None = None, seed: int = 42) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df = df[df["split"].isin(SPLITS)]
    if sample_frac:
        df = df.groupby("split", group_keys=False).sample(frac=sample_frac, random_state=seed)
    return df.reset_index(drop=True)


def gbm_matrix(df: pd.DataFrame, categories: dict[str, list[str]]) -> pd.DataFrame:
    X = df[F.FEATURES].copy()
    for col in F.NUMERIC:
        X[col] = X[col].astype(float)
    for col in F.CATEGORICAL:
        vals = X[col].astype("object")
        vals = vals.where(vals.isin(categories[col]))  # unseen levels -> missing
        X[col] = pd.Categorical(vals, categories=categories[col])
    return X


def benchmark_risk(df: pd.DataFrame) -> np.ndarray:
    """Sub-grade as a risk rank: A1 = 1 (safest) ... G5 = 35 (riskiest)."""
    rank = {sg: i + 1 for i, sg in enumerate(F.SUB_GRADES)}
    return df[F.BENCHMARK].map(rank).fillna(len(rank) / 2).to_numpy(dtype=float)


# --- models --------------------------------------------------------------------
def train_gbm(Xtr, ytr, Xva, yva, n_estimators: int, min_child_samples: int, seed: int = 42):
    import lightgbm as lgb

    model = lgb.LGBMClassifier(
        n_estimators=n_estimators,
        learning_rate=0.03,
        num_leaves=31,
        min_child_samples=min_child_samples,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.8,
        reg_lambda=1.0,
        monotone_constraints=[F.MONOTONE.get(c, 0) for c in F.FEATURES],
        random_state=seed,
        verbose=-1,
    )
    warnings.filterwarnings("ignore", message=".*eval_set.*deprecated.*")
    model.fit(
        Xtr, ytr,
        eval_set=[(Xva, yva)],
        eval_metric="auc",
        callbacks=[lgb.early_stopping(100, verbose=False), lgb.log_evaluation(0)],
    )
    return model


# --- reporting -----------------------------------------------------------------
def md_table(df: pd.DataFrame, fmt: dict[str, str] | None = None) -> str:
    fmt = fmt or {}
    cols = list(df.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for _, row in df.astype(object).iterrows():
        cells = []
        for c in cols:
            v = row[c]
            if v is None or (isinstance(v, float) and np.isnan(v)):
                cells.append("")
            elif c in fmt:
                cells.append(format(v, fmt[c]))
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def plot_roc(y, scores: dict[str, np.ndarray], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(5.5, 5))
    for name, s in scores.items():
        fpr, tpr, _ = roc_curve(y, s)
        ax.plot(fpr, tpr, label=name, linewidth=1.6)
    ax.plot([0, 1], [0, 1], linestyle="--", color="grey", linewidth=1)
    ax.set(xlabel="False positive rate (goods flagged)", ylabel="True positive rate (bads caught)",
           title=f"ROC, out-of-time test ({period('oot')})")
    ax.legend(loc="lower right", frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_calibration(tables: dict[str, pd.DataFrame], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(5.5, 5))
    hi = max(max(t["predicted"].max(), t["actual"].max()) for t in tables.values())
    for name, t in tables.items():
        ax.plot(t["predicted"], t["actual"], marker="o", label=name, linewidth=1.4)
    ax.plot([0, hi], [0, hi], linestyle="--", color="grey", linewidth=1, label="perfect")
    ax.set(xlabel="Predicted default rate", ylabel="Actual default rate",
           title="Calibration by decile, out-of-time test")
    ax.xaxis.set_major_formatter(PercentFormatter(1.0))
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_report(path: Path, perf: pd.DataFrame, calib: pd.DataFrame, stability: dict,
                 importance: pd.DataFrame, iv: pd.DataFrame, examples: pd.DataFrame,
                 best_iter: int | None, n_by_split: dict) -> None:
    oot = perf[perf["split"] == "oot"].set_index("model")
    gbm_auc, bench_auc = oot.loc["GBM", "auc"], oot.loc["Sub-grade benchmark", "auc"]
    sc_auc = oot.loc["WOE scorecard", "auc"]
    best = oot["auc"].idxmax()
    verdict = (f"The {best} ranks risk best" if best != "Sub-grade benchmark"
               else "Lending Club's own sub-grade still ranks risk best")
    lines = [
        "# Probability-of-default model report",
        "",
        f"{verdict} on the {period('oot')} out-of-time test: GBM AUC **{gbm_auc:.3f}**, "
        f"WOE scorecard **{sc_auc:.3f}**, Lending Club sub-grade **{bench_auc:.3f}** "
        f"(GBM vs. sub-grade: {gbm_auc - bench_auc:+.3f}). Neither model uses grade or interest rate as an input.",
        "",
        f"Loans: train {n_by_split['train']:,} ({period('train')}) · validation {n_by_split['valid']:,} "
        f"({period('valid')}) · out-of-time {n_by_split['oot']:,} ({period('oot')}). "
        f"GBM trees: {best_iter} (early-stopped on validation). Loans issued before 2013 are excluded "
        "because the extended credit-bureau fields were not reported yet.",
        "",
        "## Performance",
        "",
        md_table(perf, {"auc": ".3f", "gini": ".3f", "ks": ".3f", "brier": ".4f",
                        "mean_pd": ".2%", "default_rate": ".2%", "n": ","}),
        "",
        "Brier and mean PD are blank for the benchmark because sub-grade is a rank, not a probability.",
        "",
        "![ROC](figures/roc_oot.png)",
        "",
        "## Calibration (GBM, out-of-time)",
        "",
        md_table(calib, {"predicted": ".2%", "actual": ".2%", "ratio": ".2f", "loans": ","}),
        "",
        "![Calibration](figures/calibration_oot.png)",
        "",
        "## Stability",
        "",
        "Population stability index of the predicted PD, training vs. out-of-time "
        "(< 0.10 stable, 0.10–0.25 moderate shift, > 0.25 significant):",
        "",
        md_table(pd.DataFrame([{"model": k, "psi": v} for k, v in stability.items()]), {"psi": ".3f"}),
        "",
        "## What drives the GBM (mean |SHAP|, out-of-time)",
        "",
        md_table(importance.head(10), {"mean_abs_shap": ".4f"}),
        "",
        "## Scorecard features by information value",
        "",
        md_table(iv.head(12), {"iv": ".3f"}),
        "",
        "Full points table: `reports/scorecard_points.csv`.",
        "",
        "## Example reason codes (5 highest-risk out-of-time loans)",
        "",
        md_table(examples, {"pd_gbm": ".1%"}),
        "",
        "## Design choices",
        "",
        "- **No pricing inputs.** Grade, sub-grade, interest rate and installment are outputs of "
        "Lending Club's model; sub-grade is used only as the benchmark to beat.",
        "- **Out-of-time validation.** The test period comes after the training period, as it would in production.",
        "- **Full credit file.** 35 application-time inputs, including 15 extended bureau attributes "
        "(utilization, recent account openings, credit limits, delinquency history) reported from 2013.",
        "- **Monotone constraints** on credit score, income, DTI, inquiries, delinquencies, public records, "
        "bankruptcies, utilization and loan-to-income, so the model can never reward a worse value.",
        "- **Reason codes** are each loan's top three SHAP contributions that raised its risk.",
        "",
    ]
    path.write_text("\n".join(lines))


# --- main ----------------------------------------------------------------------
def run(data: Path, reports: Path, artifacts: Path, scored_out: Path, sample_frac: float | None,
        n_estimators: int, min_child_samples: int, use_mlflow: bool) -> dict:
    t0 = time.time()
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "figures").mkdir(exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)

    df = load(data, sample_frac)
    parts = {s: df[df["split"] == s] for s in SPLITS}
    y = {s: parts[s][F.TARGET].to_numpy() for s in SPLITS}
    n_by_split = {s: len(parts[s]) for s in SPLITS}
    print("Loans by split:", {s: f"{n:,}" for s, n in n_by_split.items()})

    # 1. Benchmark
    bench = {s: benchmark_risk(parts[s]) for s in SPLITS}

    # 2. WOE scorecard
    sc = Scorecard().fit(parts["train"][F.FEATURES], parts["train"][F.TARGET], F.NUMERIC, F.CATEGORICAL)
    pd_sc = {s: sc.predict_proba(parts[s][F.FEATURES]) for s in SPLITS}
    print(f"Scorecard: {len(sc.selected)} features with IV >= {sc.min_iv}")

    # 3. GBM
    categories = {c: sorted(parts["train"][c].dropna().astype(str).unique()) for c in F.CATEGORICAL}
    X = {s: gbm_matrix(parts[s], categories) for s in SPLITS}
    gbm = train_gbm(X["train"], y["train"], X["valid"], y["valid"], n_estimators, min_child_samples)
    pd_gbm = {s: gbm.predict_proba(X[s])[:, 1] for s in SPLITS}
    best_iter = gbm.best_iteration_ or n_estimators
    print(f"GBM: {best_iter} trees")

    # Performance table
    rows = []
    for s in SPLITS:
        for name, scores in (("Sub-grade benchmark", bench), ("WOE scorecard", pd_sc), ("GBM", pd_gbm)):
            m = summarize(y[s], scores[s])
            rows.append({"model": name, "split": s, **m})
    perf = pd.DataFrame(rows)[["model", "split", "auc", "gini", "ks", "brier", "mean_pd", "default_rate", "n"]]

    calib = calibration_table(y["oot"], pd_gbm["oot"])
    calib_sc = calibration_table(y["oot"], pd_sc["oot"])
    stability = {"GBM": psi(pd_gbm["train"], pd_gbm["oot"]), "WOE scorecard": psi(pd_sc["train"], pd_sc["oot"])}

    # SHAP contributions (exact TreeSHAP from LightGBM) and reason codes for every loan
    scored = []
    importance = None
    for s in SPLITS:
        contrib = gbm.predict(X[s], pred_contrib=True)[:, :-1]  # last column is the bias term
        if s == "oot":
            importance = mean_abs_contribution(contrib, F.FEATURES)
        reasons = top_reasons(contrib, F.FEATURES)
        part = parts[s][["loan_id", "issue_date", "issue_year", "split", F.TARGET, "grade", "sub_grade",
                         "int_rate", "loan_amnt", "installment", "annual_inc"]].reset_index(drop=True)
        part["pd_scorecard"] = pd_sc[s]
        part["scorecard_points"] = np.round(sc.score(parts[s][F.FEATURES])).astype(int)
        part["pd_gbm"] = pd_gbm[s]
        scored.append(pd.concat([part, reasons], axis=1))
    scored = pd.concat(scored, ignore_index=True)
    scored_out.parent.mkdir(parents=True, exist_ok=True)
    scored.to_parquet(scored_out, index=False)

    examples = (scored[scored["split"] == "oot"].nlargest(5, "pd_gbm")
                [["loan_id", "sub_grade", "pd_gbm", "reason_1", "reason_2", "reason_3"]])
    iv = (pd.DataFrame({"feature": list(sc.binner.iv), "iv": list(sc.binner.iv.values())})
          .sort_values("iv", ascending=False, ignore_index=True))
    iv["in_scorecard"] = iv["feature"].isin(sc.selected).map({True: "yes", False: "no"})

    # Files
    plot_roc(y["oot"], {"GBM": pd_gbm["oot"], "WOE scorecard": pd_sc["oot"], "Sub-grade": bench["oot"]},
             reports / "figures" / "roc_oot.png")
    plot_calibration({"GBM": calib, "WOE scorecard": calib_sc}, reports / "figures" / "calibration_oot.png")
    sc.points_table().to_csv(reports / "scorecard_points.csv", index=False)
    write_report(reports / "model_report.md", perf, calib, stability, importance, iv, examples, best_iter, n_by_split)
    gbm.booster_.save_model(str(artifacts / "lgbm_model.txt"))
    (artifacts / "scorecard.json").write_text(json.dumps(sc.to_dict(), indent=2))
    (artifacts / "gbm_categories.json").write_text(json.dumps(categories, indent=2))

    metrics = {"performance": perf.to_dict(orient="records"), "psi": stability, "gbm_trees": best_iter,
               "calibration_oot": calib.to_dict(orient="records")}
    (reports / "model_metrics.json").write_text(json.dumps(metrics, indent=2, default=str))

    if use_mlflow:
        log_mlflow(perf, stability, best_iter, n_estimators, min_child_samples, sample_frac, reports, artifacts)

    oot = perf[perf["split"] == "oot"].set_index("model")["auc"]
    print("\nOut-of-time AUC: " + " · ".join(f"{k} {v:.3f}" for k, v in oot.items()))
    print(f"Report: {reports / 'model_report.md'}  ({time.time() - t0:.0f}s)")
    return metrics


def log_mlflow(perf, stability, best_iter, n_estimators, min_child_samples, sample_frac, reports, artifacts):
    try:
        import mlflow
    except ImportError:
        print("MLflow not installed; skipping experiment tracking.")
        return
    mlflow.set_experiment("credit-risk-pd")
    with mlflow.start_run(run_name="pd-models"):
        mlflow.log_params({"n_estimators_max": n_estimators, "gbm_trees": best_iter,
                           "min_child_samples": min_child_samples, "sample_frac": sample_frac or 1.0,
                           "features": len(F.FEATURES)})
        for _, r in perf.iterrows():
            key = f"{r['model'].lower().replace(' ', '_').replace('-', '_')}_{r['split']}"
            for m in ("auc", "gini", "ks"):
                mlflow.log_metric(f"{key}_{m}", r[m])
        for k, v in stability.items():
            mlflow.log_metric(f"psi_{k.lower().replace(' ', '_')}", v)
        mlflow.log_artifacts(str(reports), artifact_path="reports")
        mlflow.log_artifacts(str(artifacts), artifact_path="model")
    print("Logged run to MLflow (view with: mlflow ui)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", type=Path, default=config.PROCESSED_DIR / "loans_model.parquet")
    p.add_argument("--reports", type=Path, default=config.REPORTS_DIR)
    p.add_argument("--artifacts", type=Path, default=ARTIFACTS)
    p.add_argument("--scored-out", type=Path, default=config.PROCESSED_DIR / "scored_loans.parquet")
    p.add_argument("--sample-frac", type=float, default=None, help="Train on a random share of loans (quick runs)")
    p.add_argument("--n-estimators", type=int, default=2000)
    p.add_argument("--min-child-samples", type=int, default=200)
    p.add_argument("--no-mlflow", action="store_true")
    a = p.parse_args()
    run(a.data, a.reports, a.artifacts, a.scored_out, a.sample_frac, a.n_estimators, a.min_child_samples,
        not a.no_mlflow)


if __name__ == "__main__":
    main()
