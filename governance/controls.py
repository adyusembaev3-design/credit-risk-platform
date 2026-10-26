"""Risk and controls register with automated control tests.

Each control states the risk it covers, what it checks, its threshold, its owner
and how often it runs. Its test reads the project's real outputs and returns
PASS, WARN, FAIL or N/A (artifact not produced yet), with the observed value.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from pipeline import config

PASS, WARN, FAIL, NA = "PASS", "WARN", "FAIL", "N/A"
# Shape of a real Anthropic credential: prefix plus a long random token (a bare prefix in code is not a key)
KEY_RE = re.compile(r"sk-ant-[a-z0-9]+-[A-Za-z0-9_\-]{20,}")


@dataclass
class Result:
    status: str
    observed: str


@dataclass
class Control:
    id: str
    category: str
    risk: str
    control: str
    kind: str            # preventive | detective
    threshold: str
    owner: str
    frequency: str
    test: Callable[["Context"], Result]


class Context:
    """Loads artifacts lazily so a missing one makes only its own controls N/A."""

    def __init__(self, root: Path = config.ROOT):
        self.root = root
        self.data = root / "data" / "processed"
        self._cache: dict = {}

    def json(self, rel: str):
        p = self.root / rel
        return json.loads(p.read_text()) if p.exists() else None

    def parquet(self, name: str, columns=None):
        key = (name, tuple(columns or ()))
        if key not in self._cache:
            p = self.data / name
            self._cache[key] = pd.read_parquet(p, columns=columns) if p.exists() else None
        return self._cache[key]


def _perf(ctx, model, split, metric="auc"):
    m = ctx.json("reports/model_metrics.json")
    if not m:
        return None
    return next((r[metric] for r in m["performance"] if r["model"] == model and r["split"] == split), None)


# --- control tests ------------------------------------------------------------------
def c01_data_quality(ctx):
    dq = ctx.json("reports/data_quality.json")
    if not dq:
        return Result(NA, "data_quality.json not found")
    fails = [r["check_id"] for r in dq["results"] if r["status"] == "FAIL"]
    warns = sum(r["status"] == "WARN" for r in dq["results"])
    if fails:
        return Result(FAIL, f"{len(fails)} failing checks: {', '.join(fails[:5])}")
    return Result(WARN if warns else PASS, f"{len(dq['results'])} checks, {warns} warnings, 0 failures")


def c02_leakage(ctx):
    p = ctx.data / "loans_model.parquet"
    if not p.exists():
        return Result(NA, "loans_model.parquet not found")
    import pyarrow.parquet as pq

    cols = {c.lower() for c in pq.read_schema(p).names}
    leaked = sorted(cols & set(config.LEAKAGE_COLUMNS))
    return Result(FAIL if leaked else PASS, ", ".join(leaked) if leaked else "no post-issue fields in model table")


def c03_performance_floor(ctx):
    gbm, bench = _perf(ctx, "GBM", "oot"), _perf(ctx, "Sub-grade benchmark", "oot")
    if gbm is None:
        return Result(NA, "model_metrics.json not found")
    ok = gbm >= 0.66 and gbm >= bench - 0.01
    return Result(PASS if ok else FAIL, f"GBM out-of-time AUC {gbm:.3f} vs benchmark {bench:.3f}")


def c04_overfitting(ctx):
    tr, oot = _perf(ctx, "GBM", "train"), _perf(ctx, "GBM", "oot")
    if tr is None:
        return Result(NA, "model_metrics.json not found")
    gap = tr - oot
    return Result(PASS if gap <= 0.08 else WARN if gap <= 0.12 else FAIL, f"train {tr:.3f} - out-of-time {oot:.3f} = {gap:.3f}")


def c05_stability(ctx):
    m = ctx.json("reports/model_metrics.json")
    if not m:
        return Result(NA, "model_metrics.json not found")
    psi = m["psi"]["GBM"]
    return Result(PASS if psi < 0.10 else WARN if psi <= 0.25 else FAIL, f"PSI {psi:.3f}")


def c06_calibration(ctx):
    m = ctx.json("reports/model_metrics.json")
    if not m:
        return Result(NA, "model_metrics.json not found")
    oot = next(r for r in m["performance"] if r["model"] == "GBM" and r["split"] == "oot")
    ratio = oot["mean_pd"] / oot["default_rate"]
    worst = max(abs(d["ratio"] - 1) for d in m.get("calibration_oot", [{"ratio": 1}]))
    status = PASS if abs(ratio - 1) <= 0.10 and worst <= 0.35 else WARN if abs(ratio - 1) <= 0.20 else FAIL
    return Result(status, f"mean PD / default rate {ratio:.2f}; worst decile actual/predicted off by {worst:.0%}")


def c07_monotonicity(ctx):
    """Raising a risk-increasing input must never lower predicted PD (and vice versa)."""
    model_p = ctx.root / "models" / "artifacts" / "lgbm_model.txt"
    cats_p = ctx.root / "models" / "artifacts" / "gbm_categories.json"
    loans = ctx.parquet("loans_model.parquet")
    if not model_p.exists() or loans is None:
        return Result(NA, "model artifact or loans_model not found")
    try:
        import lightgbm as lgb
    except (ImportError, OSError):
        return Result(NA, "lightgbm not available")
    from models import features as F
    from models.train import gbm_matrix

    booster = lgb.Booster(model_file=str(model_p))
    sample = loans[loans["split"] == "oot"].sample(min(2000, (loans["split"] == "oot").sum()), random_state=0)
    X = gbm_matrix(sample, json.loads(cats_p.read_text()))
    base = booster.predict(X)
    violations = []
    for col, sign in F.MONOTONE.items():
        Xs = X.copy()
        Xs[col] = Xs[col] + np.nanstd(X[col].astype(float))
        moved = booster.predict(Xs) - base
        bad = (moved * sign < -1e-9).mean()
        if bad > 0:
            violations.append(f"{col} ({bad:.1%})")
    return Result(FAIL if violations else PASS,
                  ", ".join(violations) if violations else f"{len(F.MONOTONE)} constrained inputs, 0 violations on 2,000 loans")


def c08_reason_codes(ctx):
    s = ctx.parquet("scored_loans.parquet", ["pd_gbm", "reason_1"])
    if s is None:
        return Result(NA, "scored_loans.parquet not found")
    top = s[s["pd_gbm"] >= s["pd_gbm"].quantile(0.9)]
    missing = top["reason_1"].isna().mean()
    return Result(PASS if missing == 0 else FAIL, f"{missing:.2%} of highest-risk decile without a reason code")


def c09_stress_backtest(ctx):
    s = ctx.json("reports/stress_results.json")
    if not s:
        return Result(NA, "stress_results.json not found")
    r = s["backtest"]["ratio"]
    return Result(PASS if 0.85 <= r <= 1.15 else WARN if 0.7 <= r <= 1.3 else FAIL, f"expected / actual loss {r:.2f}")


def c10_macro_significance(ctx):
    s = ctx.json("reports/stress_results.json")
    if not s:
        return Result(NA, "stress_results.json not found")
    z = s["sensitivity"]["beta_per_pp"] / s["sensitivity"]["se_overdispersion_adjusted"]
    return Result(PASS if z >= 2 else WARN, f"z = {z:.1f} (overdispersion-adjusted)")


def c11_policy_limits(ctx):
    o = ctx.json("reports/optimization_results.json")
    if not o:
        return Result(NA, "optimization_results.json not found")
    p = next(x for x in o["policies"] if x["policy"] == "Optimized")
    c = o["constraints"]
    return Result(PASS if p["meets_constraints"] == "yes" else FAIL,
                  f"severe loss {p['severe_loss_rate']:.1%} (limit {c['max_severe_loss_rate']:.0%}), "
                  f"volume {p['volume_share']:.0%} (floor {c['min_volume_share']:.0%})")


def c12_profit_calibration(ctx):
    o = ctx.json("reports/optimization_results.json")
    if not o:
        return Result(NA, "optimization_results.json not found")
    e, r = o["calibration"]["expected_usd_m"], o["calibration"]["realized_usd_m"]
    ratio = e / r if r else float("inf")
    return Result(PASS if 0.8 <= ratio <= 1.25 else WARN if 0.5 <= ratio <= 2 else FAIL,
                  f"expected ${e:,.1f}M vs realized ${r:,.1f}M profit (ratio {ratio:.2f})")


def c13_launch_guardrail(ctx):
    e = ctx.json("reports/experiment_results.json")
    if not e:
        return Result(NA, "experiment_results.json not found")
    r = e["readout"]
    ok = r["uplift_ci_low"] > 0 and r["default_rate_challenger"] <= r["default_rate_champion"]
    launched = e["decision"].startswith("Launch")
    status = PASS if ok == launched else FAIL       # the decision must follow the rule
    return Result(status, f"decision '{e['decision']}', uplift CI low ${r['uplift_ci_low']:,.2f}, "
                          f"default {r['default_rate_challenger']:.1%} vs {r['default_rate_champion']:.1%}")


def c14_geographic_disparity(ctx):
    """Approval-rate ratio across states (4/5ths rule). Protected attributes are not in
    the data, so geography is reviewed as a proxy; a WARN means review, not a violation."""
    pl = ctx.parquet("policy_loans.parquet", ["loan_id", "approve"])
    lm = ctx.parquet("loans_model.parquet", ["loan_id", "addr_state"])
    if pl is None or lm is None:
        return Result(NA, "policy_loans or loans_model not found")
    d = pl.merge(lm, on="loan_id")
    rates = d.groupby("addr_state").agg(n=("approve", "size"), rate=("approve", "mean"))
    rates = rates[rates["n"] >= 1000]
    ratio = rates["rate"].min() / rates["rate"].max()
    lo, hi = rates["rate"].idxmin(), rates["rate"].idxmax()
    return Result(PASS if ratio >= 0.8 else WARN,
                  f"lowest/highest state approval rate {ratio:.2f} ({lo} {rates.loc[lo, 'rate']:.0%} vs "
                  f"{hi} {rates.loc[hi, 'rate']:.0%}; {len(rates)} states with 1,000+ applicants)")


def c15_ai_quality(ctx):
    ev = ctx.json("reports/agent_eval.json")
    if not ev:
        return Result(NA, "agent_eval.json not found")
    df = pd.DataFrame(ev)
    acc = df["correct"].mean()
    invalid = int((df["invalid_citations"] > 0).sum())
    faith = df["supported_claims"].sum() / df["judged_claims"].sum() if "judged_claims" in df and df["judged_claims"].sum() else None
    ok = acc >= 0.95 and invalid == 0 and (faith is None or faith >= 0.85)
    return Result(PASS if ok else FAIL, f"accuracy {acc:.0%}, answers with invented citations {invalid}, "
                                        f"faithfulness {faith:.0%}" if faith is not None else f"accuracy {acc:.0%}")


def c16_secrets(ctx):
    try:
        tracked = subprocess.run(["git", "ls-files"], cwd=ctx.root, capture_output=True, text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        return Result(NA, "not a git repository")
    env_tracked = [f for f in tracked if Path(f).name in (".env", "kaggle.json")]
    hits = []
    for f in tracked:
        p = ctx.root / f
        if p.suffix in (".py", ".md", ".json", ".txt", ".sql", ".toml", ".cfg", ".yml", ".yaml") and p.exists():
            if KEY_RE.search(p.read_text(errors="ignore")):
                hits.append(f)
    bad = env_tracked + hits
    return Result(FAIL if bad else PASS, ", ".join(bad) if bad else f"{len(tracked)} tracked files, no credentials")


REGISTER = [
    Control("C-01", "Data", "Corrupt or incomplete input data reaches the model",
            "Data-quality controls DQ-01 to DQ-17 gate the pipeline; any failure stops it", "preventive",
            "0 failing checks", "Data engineering", "Every pipeline run", c01_data_quality),
    Control("C-02", "Data", "Post-issue information leaks into the default model",
            "Payment and recovery fields are kept out of the model table", "preventive",
            "0 leakage columns", "Data engineering", "Every pipeline run", c02_leakage),
    Control("C-03", "Model", "Default model ranks risk worse than the lender's own grade",
            "Out-of-time AUC floor and benchmark comparison", "detective",
            "AUC >= 0.66 and >= benchmark - 0.01", "Model owner", "Every retrain", c03_performance_floor),
    Control("C-04", "Model", "Model overfits training vintages",
            "Gap between training and out-of-time AUC", "detective",
            "<= 0.08 pass, <= 0.12 warn", "Model owner", "Every retrain", c04_overfitting),
    Control("C-05", "Model", "Applicant population drifts away from training data",
            "Population stability index of predicted PD", "detective",
            "< 0.10 pass, <= 0.25 warn", "Model owner", "Monthly", c05_stability),
    Control("C-06", "Model", "Predicted default rates are biased, misstating expected loss",
            "Calibration in the large and by decile, out-of-time", "detective",
            "mean ratio within 10%, deciles within 35%", "Model owner", "Every retrain", c06_calibration),
    Control("C-07", "Model", "Model rewards worse credit attributes (indefensible decisions)",
            "Perturbation test of every monotone-constrained input", "preventive",
            "0 violations", "Model validation", "Every retrain", c07_monotonicity),
    Control("C-08", "Compliance", "Declined applicants cannot be given reasons (adverse action)",
            "Every high-risk loan carries SHAP reason codes", "preventive",
            "0% missing in top risk decile", "Model owner", "Every scoring run", c08_reason_codes),
    Control("C-09", "Model", "Stress test misstates losses",
            "Out-of-time backtest of expected vs. actual loss", "detective",
            "ratio 0.85-1.15 pass, 0.70-1.30 warn", "Risk analytics", "Quarterly", c09_stress_backtest),
    Control("C-10", "Model", "Macro sensitivity is noise",
            "Significance of the unemployment coefficient after overdispersion adjustment", "detective",
            "z >= 2", "Risk analytics", "Quarterly", c10_macro_significance),
    Control("C-11", "Decision", "Credit policy breaches its risk appetite",
            "Optimized policy checked against loss budget, volume floor, concentration cap", "preventive",
            "all constraints met", "Credit strategy", "Every policy change", c11_policy_limits),
    Control("C-12", "Decision", "Profit estimates used for decisions are biased",
            "Expected vs. realized lifetime profit on the full book", "detective",
            "ratio 0.80-1.25 pass, 0.5-2 warn", "Credit strategy", "Quarterly", c12_profit_calibration),
    Control("C-13", "Decision", "Policy launched without evidence or against guardrails",
            "Launch decision must follow the pre-registered rule", "preventive",
            "decision consistent with rule", "Credit strategy", "Every experiment", c13_launch_guardrail),
    Control("C-14", "Compliance", "Policy has disparate impact across geographies",
            "Approval-rate ratio across states (4/5ths rule), reviewed as a proxy", "detective",
            ">= 0.80 pass, else review", "Compliance", "Every policy change", c14_geographic_disparity),
    Control("C-15", "AI", "AI analyst gives wrong or unsupported answers",
            "28-question evaluation: accuracy, invented citations, judged faithfulness", "detective",
            "accuracy >= 95%, 0 invented citations, faithfulness >= 85%", "AI owner", "Every prompt or model change",
            c15_ai_quality),
    Control("C-16", "Technology", "Credentials committed to the repository",
            "Tracked files scanned for API keys and credential files", "preventive",
            "0 findings", "Engineering", "Every commit", c16_secrets),
]


def run_controls(ctx: Context, register=REGISTER) -> list[dict]:
    rows = []
    for c in register:
        try:
            r = c.test(ctx)
        except Exception as e:  # noqa: BLE001 - a broken test is itself a finding
            r = Result(FAIL, f"control test error: {type(e).__name__}: {str(e)[:120]}")
        rows.append({"id": c.id, "category": c.category, "risk": c.risk, "control": c.control, "kind": c.kind,
                     "threshold": c.threshold, "owner": c.owner, "frequency": c.frequency,
                     "status": r.status, "observed": r.observed})
    return rows
