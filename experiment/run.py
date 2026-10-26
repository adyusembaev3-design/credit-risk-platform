"""Module 5: champion/challenger experiment for the optimized credit policy.

Champion   = the status quo: fund every applicant Lending Club approved.
Challenger = the optimized policy from Module 4.

Applicants in the 2015 book are randomly split 50/50. Each arm applies its own
policy; a declined applicant earns 0. The primary metric is realized lifetime
profit per applicant. Guardrails: approval rate, default rate among funded loans.

Steps
  1. Design: from model predictions only (expected profit), size the test with a
     power calculation, before looking at outcomes.
  2. Readout: realized results with a Welch t-test and a bootstrap CI.
  3. Robustness: repeat the random split 50 times; empirical power at smaller sizes.
  4. Decision rule: launch if the 95% CI of the profit uplift is above 0 and the
     default rate of funded loans is not higher than the champion's.

Usage:
    python -m experiment.run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import PercentFormatter  # noqa: E402

from experiment.stats import bootstrap_ci, required_n_per_arm, two_proportion, welch  # noqa: E402
from models.train import md_table  # noqa: E402
from optimize.profit import realized_profit  # noqa: E402
from pipeline import config  # noqa: E402

SEED = 2015
N_SPLITS = 50
N_SIMS = 200
SIZES = (1_000, 2_000, 5_000, 10_000, 20_000, 50_000, 100_000)


def historical_profit_sd(data_dir: Path) -> float:
    """SD of realized lifetime profit per loan on 2013-2014 loans (known before the 2015 test)."""
    loans = pd.read_parquet(data_dir / "loans_model.parquet", columns=["loan_id", "split"])
    out = pd.read_parquet(data_dir / "loan_outcomes.parquet")
    hist = out.merge(loans[loans["split"].isin(["train", "valid"])], on="loan_id")
    return float(realized_profit(hist).std(ddof=1))


def arm_profits(df: pd.DataFrame, metric: str) -> tuple[np.ndarray, np.ndarray]:
    """Per-applicant profit if everyone were in the champion / challenger arm."""
    champ = df[metric].to_numpy()
    chall = np.where(df["approve"].to_numpy(), champ, 0.0)
    return champ, chall


def assign(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.permutation(n) < n // 2          # True = challenger arm


def readout(df: pd.DataFrame, in_b: np.ndarray, n_boot: int) -> dict:
    champ, chall = arm_profits(df, "profit_realized")
    a, b = champ[~in_b], chall[in_b]
    w = welch(a, b)
    lo, hi = bootstrap_ci(a, b, n_boot=n_boot, seed=SEED)
    fund_a = np.ones((~in_b).sum(), dtype=bool)
    fund_b = df["approve"].to_numpy()[in_b]
    dflt = df["is_default"].to_numpy()
    dr = two_proportion(int(dflt[~in_b][fund_a].sum()), int(fund_a.sum()),
                        int(dflt[in_b][fund_b].sum()), int(fund_b.sum()))
    return {
        "n_champion": int((~in_b).sum()), "n_challenger": int(in_b.sum()),
        "profit_per_applicant_champion": float(a.mean()), "profit_per_applicant_challenger": float(b.mean()),
        "uplift": w["diff"], "uplift_ci_low": w["ci_low"], "uplift_ci_high": w["ci_high"], "p_value": w["p_value"],
        "uplift_boot_low": lo, "uplift_boot_high": hi,
        "approval_rate_challenger": float(fund_b.mean()),
        "default_rate_champion": dr["rate_a"], "default_rate_challenger": dr["rate_b"],
        "default_rate_p_value": dr["p_value"],
    }


def repeated_splits(df: pd.DataFrame, n_splits: int) -> pd.DataFrame:
    champ, chall = arm_profits(df, "profit_realized")
    rows = []
    for s in range(n_splits):
        in_b = assign(len(df), SEED + 1 + s)
        w = welch(champ[~in_b], chall[in_b])
        rows.append({"seed": s, "uplift": w["diff"], "p_value": w["p_value"]})
    return pd.DataFrame(rows)


def power_curve(df: pd.DataFrame, sizes: tuple[int, ...], n_sims: int) -> pd.DataFrame:
    champ, chall = arm_profits(df, "profit_realized")
    rng = np.random.default_rng(SEED)
    rows = []
    for n in sizes:
        if 2 * n > len(df):
            continue
        hits = 0
        for _ in range(n_sims):
            idx = rng.choice(len(df), 2 * n, replace=False)
            hits += welch(champ[idx[:n]], chall[idx[n:]])["p_value"] < 0.05
        rows.append({"applicants_per_arm": n, "power": hits / n_sims})
    return pd.DataFrame(rows)


def plot_power(pc: pd.DataFrame, n_planned: int, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.plot(pc["applicants_per_arm"], pc["power"], marker="o", color="#1f4e8c", linewidth=1.6)
    ax.axhline(0.8, color="grey", linestyle="--", linewidth=0.8)
    ax.text(pc["applicants_per_arm"].min(), 0.82, "80% power", fontsize=8, color="grey")
    if n_planned:
        ax.axvline(n_planned, color="#c0504d", linestyle=":", linewidth=1)
        ax.text(n_planned / 1.08, 0.05, f"planned\n{n_planned:,}/arm", fontsize=8, color="#c0504d", ha="right")
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_ylim(0, 1.02)
    ax.set(xlabel="Applicants per arm (log scale)", ylabel="Share of simulated tests detecting the uplift",
           title="How large the test needs to be")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _d(x: float, sign: bool = False) -> str:
    """Dollar amount with the minus sign before the $ (e.g. -$12.30)."""
    s = "-" if x < 0 else ("+" if sign and x > 0 else "")
    return f"{s}${abs(x):,.2f}"


def write_report(path: Path, design: dict, r: dict, splits: pd.DataFrame, pc: pd.DataFrame, decision: str,
                 reasons: list[str]) -> None:
    sig = (splits["p_value"] < 0.05).mean()
    lines = [
        "# Champion/challenger experiment readout",
        "",
        f"**Decision: {decision}.** The optimized policy earned **{_d(abs(r['uplift']))} {'more' if r['uplift'] >= 0 else 'less'} per applicant** "
        f"(95% CI {_d(r['uplift_ci_low'])} to {_d(r['uplift_ci_high'])}, p = {r['p_value']:.2g}) while funding "
        f"{r['approval_rate_challenger']:.0%} of applicants, and its funded loans defaulted at "
        f"{r['default_rate_challenger']:.1%} vs. {r['default_rate_champion']:.1%}.",
        "",
        "Simulated on the 2015 book: applicants randomly split 50/50; champion funds everyone Lending Club approved, "
        "challenger applies the Module 4 policy; a declined applicant earns $0.",
        "",
        "## Design (before outcomes)",
        "",
        f"From model predictions, the challenger was expected to add **{_d(design['expected_uplift'])} per applicant** "
        f"(per-applicant profit SD ${design['sd_per_applicant']:,.0f}, from realized profit on 2013–2014 loans). "
        f"Detecting that with 80% power at α = 0.05 needs **{design['n_per_arm']:,} applicants per arm**; "
        f"the book supplies {r['n_challenger']:,}.",
        "",
        "## Readout",
        "",
        md_table(pd.DataFrame([
            {"metric": "Profit per applicant", "champion": f"{_d(r['profit_per_applicant_champion'])}",
             "challenger": f"{_d(r['profit_per_applicant_challenger'])}",
             "difference": f"{_d(r['uplift'], sign=True)}",
             "95% CI": f"{_d(r['uplift_ci_low'])} to {_d(r['uplift_ci_high'])}", "p-value": f"{r['p_value']:.2g}"},
            {"metric": "Profit per applicant (bootstrap CI)", "champion": "", "challenger": "", "difference": "",
             "95% CI": f"{_d(r['uplift_boot_low'])} to {_d(r['uplift_boot_high'])}", "p-value": ""},
            {"metric": "Approval rate", "champion": "100%", "challenger": f"{r['approval_rate_challenger']:.1%}",
             "difference": f"{r['approval_rate_challenger'] - 1:+.1%}", "95% CI": "", "p-value": ""},
            {"metric": "Default rate of funded loans", "champion": f"{r['default_rate_champion']:.2%}",
             "challenger": f"{r['default_rate_challenger']:.2%}",
             "difference": f"{r['default_rate_challenger'] - r['default_rate_champion']:+.2%}", "95% CI": "",
             "p-value": f"{r['default_rate_p_value']:.2g}"},
        ])),
        "",
        f"Applicants: {r['n_champion']:,} champion, {r['n_challenger']:,} challenger.",
        "",
        "## Decision rule",
        "",
        "Launch if the 95% CI of the profit uplift is above $0 **and** funded loans do not default more than the "
        "champion's. " + " ".join(reasons),
        "",
        "## Robustness",
        "",
        f"Re-running the random split {len(splits)} times: uplift ranged from {_d(splits['uplift'].min())} to "
        f"{_d(splits['uplift'].max())} per applicant and was significant at 5% in **{sig:.0%}** of splits.",
        "",
        "Empirical power at smaller test sizes (applicants drawn from the 2015 book):",
        "",
        "![Power](figures/power_curve.png)",
        "",
        md_table(pc, {"applicants_per_arm": ",", "power": ".0%"}),
        "",
        "## Limitations",
        "",
        "- A simulation on historical outcomes, not a live test: no behavioral response (declined applicants "
        "reapplying elsewhere, competitors) and no seasonality between arms.",
        "- Profit is lifetime (36 months); a live test would read early indicators (30+ days past due at 6 and 12 "
        "months) and confirm later.",
        "- The challenger was designed on predictions for this same book; a live rollout would use the next cohort.",
        "",
    ]
    path.write_text("\n".join(lines))


def run(data_dir: Path, reports: Path, n_boot: int = 500, n_splits: int = N_SPLITS, n_sims: int = N_SIMS,
        sizes: tuple[int, ...] = SIZES) -> dict:
    (reports / "figures").mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(data_dir / "policy_loans.parquet").reset_index(drop=True)
    df["approve"] = df["approve"].fillna(False).astype(bool)

    # 1. Design, before 2015 outcomes: uplift from model predictions, variance from 2013-2014 loans
    e_champ, e_chall = arm_profits(df, "profit_baseline")
    exp_uplift = float(e_chall.mean() - e_champ.mean())
    sd_hist = historical_profit_sd(data_dir)
    n_plan = required_n_per_arm(exp_uplift, sd_hist, sd_hist)
    design = {"expected_uplift": exp_uplift, "sd_per_applicant": sd_hist, "n_per_arm": n_plan}

    # 2. Readout
    in_b = assign(len(df), SEED)
    r = readout(df, in_b, n_boot)

    # 3. Robustness
    splits = repeated_splits(df, n_splits)
    pc = power_curve(df, sizes, n_sims)

    # 4. Decision
    profit_ok = r["uplift_ci_low"] > 0
    risk_ok = r["default_rate_challenger"] <= r["default_rate_champion"]
    decision = "Launch the challenger" if profit_ok and risk_ok else "Do not launch"
    reasons = [
        f"Profit criterion {'met' if profit_ok else 'not met'} (CI lower bound {_d(r['uplift_ci_low'])}).",
        f"Risk guardrail {'met' if risk_ok else 'not met'} ({r['default_rate_challenger']:.2%} vs. "
        f"{r['default_rate_champion']:.2%}).",
    ]

    plot_power(pc, n_plan if n_plan < 10 * max(sizes) else 0, reports / "figures" / "power_curve.png")
    write_report(reports / "experiment_report.md", design, r, splits, pc, decision, reasons)
    results = {"design": design, "readout": r, "decision": decision,
               "splits_significant_share": float((splits["p_value"] < 0.05).mean()),
               "power_curve": pc.to_dict(orient="records")}
    (reports / "experiment_results.json").write_text(json.dumps(results, indent=2))

    print(f"Design: expected uplift {_d(exp_uplift)}/applicant -> {n_plan:,} applicants per arm for 80% power")
    print(f"Readout: uplift {_d(r['uplift'])}/applicant (95% CI {_d(r['uplift_ci_low'])} to "
          f"{_d(r['uplift_ci_high'])}, p={r['p_value']:.2g}); approval {r['approval_rate_challenger']:.0%}; "
          f"default rate {r['default_rate_challenger']:.2%} vs {r['default_rate_champion']:.2%}")
    print(f"Significant in {(splits['p_value'] < 0.05).mean():.0%} of {len(splits)} random splits · Decision: {decision}")
    print(f"Report: {reports / 'experiment_report.md'}")
    return results


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", type=Path, default=config.PROCESSED_DIR)
    p.add_argument("--reports", type=Path, default=config.REPORTS_DIR)
    a = p.parse_args()
    run(a.data, a.reports)


if __name__ == "__main__":
    main()
