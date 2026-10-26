"""Module 4: choose a credit policy for the 2015 book that maximizes expected profit
while keeping severe-recession losses within a budget.

The policy is chosen from model predictions only (predicted PD, stressed PD, LGD and
yield factors estimated before 2015). The 2015 outcomes are used afterwards, only to
measure the realized profit of each policy.

Usage:
    python -m optimize.run
    python -m optimize.run --max-severe-loss 0.09 --min-volume 0.6 --solver gurobi
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

from models.train import md_table  # noqa: E402
from optimize.profit import FUNDING_RATE, expected_profit, realized_profit, yield_factors  # noqa: E402
from optimize.solver import Constraints, is_feasible, solve  # noqa: E402
from pipeline import config  # noqa: E402

RISKY_GRADES = ("E", "F", "G")
N_RISK_BANDS = 10
FRONTIER = np.round(np.arange(0.06, 0.1601, 0.005), 3)


def build_segments(book: pd.DataFrame) -> pd.DataFrame:
    book["risk_band"] = pd.qcut(book["pd_baseline"].rank(method="first"), N_RISK_BANDS,
                                labels=range(1, N_RISK_BANDS + 1)).astype(int)
    seg = (book.groupby(["grade", "risk_band"])
           .agg(loans=("loan_id", "size"), exposure=("loan_amnt", "sum"), mean_pd=("pd_baseline", "mean"),
                profit=("profit_baseline", "sum"), profit_severe=("profit_severe", "sum"),
                severe_loss=("el_severe", "sum"), realized=("profit_realized", "sum"))
           .reset_index())
    seg["risky"] = seg["grade"].isin(RISKY_GRADES)
    return seg


def evaluate(name: str, approve: np.ndarray, seg: pd.DataFrame, c: Constraints) -> dict:
    s = seg[approve]
    exp = s["exposure"].sum()
    return {
        "policy": name,
        "loans": int(s["loans"].sum()),
        "volume_share": exp / seg["exposure"].sum(),
        "exposure_usd_m": exp / 1e6,
        "expected_profit_usd_m": s["profit"].sum() / 1e6,
        "expected_profit_severe_usd_m": s["profit_severe"].sum() / 1e6,
        "severe_loss_rate": s["severe_loss"].sum() / exp if exp else float("nan"),
        "realized_profit_usd_m": s["realized"].sum() / 1e6,
        "realized_return": s["realized"].sum() / exp if exp else float("nan"),
        "meets_constraints": "yes" if is_feasible(approve, seg["exposure"], seg["severe_loss"], seg["risky"], c) else "no",
    }


def frontier(seg: pd.DataFrame, c: Constraints, solver: str) -> pd.DataFrame:
    rows = []
    for L in FRONTIER:
        cc = Constraints(max_severe_loss_rate=float(L), min_volume_share=0.0, max_risky_share=c.max_risky_share)
        sol = solve(seg["profit"].to_numpy(), seg["exposure"].to_numpy(), seg["severe_loss"].to_numpy(),
                    seg["risky"].to_numpy(), cc, solver)
        if sol.status != "optimal":
            continue
        e = evaluate(f"L={L}", sol.approve, seg, cc)
        rows.append({"severe_loss_budget": float(L), **{k: e[k] for k in (
            "volume_share", "expected_profit_usd_m", "realized_profit_usd_m", "severe_loss_rate")}})
    return pd.DataFrame(rows)


def plot_frontier(fr: pd.DataFrame, chosen: float, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.4))
    ax.plot(fr["severe_loss_budget"], fr["expected_profit_usd_m"], marker="o", markersize=3, color="#1f4e8c",
            label="Expected profit (model)")
    ax.plot(fr["severe_loss_budget"], fr["realized_profit_usd_m"], marker="o", markersize=3, color="#c0504d",
            linestyle="--", label="Realized profit (2015 outcomes)")
    ax.axvline(chosen, color="grey", linewidth=0.8, linestyle=":")
    ax.xaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set(xlabel="Severe-scenario loss budget (% of approved principal)", ylabel="Lifetime profit, $M",
           title="Profit at each severe-loss budget")
    ax2 = ax.twinx()
    ax2.bar(fr["severe_loss_budget"], fr["volume_share"], width=0.0035, alpha=0.18, color="grey", label="Volume share (right)")
    ax2.set_ylim(0, 1.05)
    ax2.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax2.set_ylabel("Share of book approved")
    ax.set_zorder(ax2.get_zorder() + 1)
    ax.patch.set_visible(False)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=3, frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def decision_grid(seg: pd.DataFrame) -> pd.DataFrame:
    g = seg.pivot(index="grade", columns="risk_band", values="approve").reindex(columns=range(1, N_RISK_BANDS + 1))
    g = g.map(lambda v: "" if pd.isna(v) else ("approve" if v else "·"))
    g.columns = [f"band {c}" for c in g.columns]
    return g.reset_index()


def _usd(x: float) -> str:
    return f"{'-' if x < 0 else ''}${abs(x):,.1f}M"


def write_report(path: Path, policies: pd.DataFrame, c: Constraints, factors: pd.DataFrame, grid: pd.DataFrame,
                 fr: pd.DataFrame, calib: dict, n_book: int, exposure: float, solver: str) -> None:
    p = policies.set_index("policy")
    opt, allp, ad = p.loc["Optimized"], p.loc["Approve all"], p.loc["Grades A-D only"]
    lines = [
        "# Credit policy optimization report",
        "",
        f"The optimized policy funds **{opt['volume_share']:.0%}** of the 2015 book and earned "
        f"**{_usd(opt['realized_profit_usd_m'])}** of realized profit ({opt['realized_return']:.2%} of principal), vs. "
        f"{_usd(allp['realized_profit_usd_m'])} ({allp['realized_return']:.2%}) for approving every loan and "
        f"{_usd(ad['realized_profit_usd_m'])} ({ad['realized_return']:.2%}) for a grade A–D cutoff, while holding "
        f"severe-recession losses to {opt['severe_loss_rate']:.1%} (budget {c.max_severe_loss_rate:.0%}).",
        "",
        f"Book: {n_book:,} loans issued in 2015, ${exposure / 1e6:,.0f}M of principal. The policy is chosen from "
        "model predictions only; 2015 outcomes are used afterwards to measure realized profit.",
        "",
        "## Policies compared",
        "",
        md_table(policies, {"loans": ",", "volume_share": ".0%", "exposure_usd_m": ",.0f",
                            "expected_profit_usd_m": ",.1f", "expected_profit_severe_usd_m": ",.1f",
                            "severe_loss_rate": ".2%", "realized_profit_usd_m": ",.1f", "realized_return": ".2%"}),
        "",
        f"Constraints: severe-scenario loss ≤ {c.max_severe_loss_rate:.0%} of approved principal · approved volume ≥ "
        f"{c.min_volume_share:.0%} of the book · grades {', '.join(RISKY_GRADES)} ≤ {c.max_risky_share:.0%} of approved "
        f"principal. Solver: {solver}.",
        "",
        "## Which segments are approved",
        "",
        f"Rows are Lending Club grades; columns are deciles of predicted default risk (band 1 safest, band "
        f"{N_RISK_BANDS} riskiest). Blank = no loans.",
        "",
        md_table(grid),
        "",
        "## Profit frontier",
        "",
        "Best expected profit at each severe-loss budget (no volume floor), and what that policy actually earned.",
        "",
        "![Frontier](figures/profit_frontier.png)",
        "",
        md_table(fr, {"severe_loss_budget": ".1%", "volume_share": ".0%", "expected_profit_usd_m": ",.1f",
                      "realized_profit_usd_m": ",.1f", "severe_loss_rate": ".2%"}),
        "",
        "## Profit model",
        "",
        "Expected profit = (1 − PD) × scheduled interest × yield_good + PD × (scheduled interest × yield_bad − LGD × "
        f"principal) − funding cost ({FUNDING_RATE:.0%} a year on 1.5 principal-years). Yield factors are the share of "
        "scheduled interest actually collected on loans issued 2013–2014 (prepayment and default cut it):",
        "",
        md_table(factors, {"yield_good": ".1%", "yield_bad": ".1%"}),
        "",
        f"Calibration check, every 2015 loan: expected profit {_usd(calib['expected_usd_m'])} vs. realized "
        f"{_usd(calib['realized_usd_m'])}.",
        "",
        "## Limitations",
        "",
        "- Lending Club data only contains approved loans, so this chooses which approved loans to fund; "
        "applicants Lending Club declined are unseen (reject inference is out of scope).",
        "- Approve/decline by segment; credit-line size and pricing are held at what Lending Club offered.",
        "- Funding cost and balance-years are simple assumptions; prepayment also shortens funding need.",
        "",
    ]
    path.write_text("\n".join(lines))


def run(data_dir: Path, reports: Path, c: Constraints, solver: str = "highs") -> dict:
    (reports / "figures").mkdir(parents=True, exist_ok=True)
    book = pd.read_parquet(data_dir / "stressed_book.parquet")
    outcomes = pd.read_parquet(data_dir / "loan_outcomes.parquet")
    loans = pd.read_parquet(data_dir / "loans_model.parquet")

    factors = yield_factors(loans, outcomes)
    book = book.merge(outcomes[["loan_id", "interest_received", "loss_rate"]], on="loan_id", how="left")
    book["profit_baseline"] = expected_profit(book, "pd_baseline", factors)
    book["profit_severe"] = expected_profit(book, "pd_severe", factors)
    book["profit_realized"] = realized_profit(book)
    calib = {"expected_usd_m": book["profit_baseline"].sum() / 1e6, "realized_usd_m": book["profit_realized"].sum() / 1e6}

    seg = build_segments(book)
    sol = solve(seg["profit"].to_numpy(), seg["exposure"].to_numpy(), seg["severe_loss"].to_numpy(),
                seg["risky"].to_numpy(), c, solver)
    if sol.status != "optimal":
        raise SystemExit(f"No policy meets the constraints ({sol.status}). Loosen --max-severe-loss or --min-volume.")
    seg["approve"] = sol.approve

    policies = pd.DataFrame([
        evaluate("Approve all", np.ones(len(seg), dtype=bool), seg, c),
        evaluate("Grades A-D only", ~seg["risky"].to_numpy(), seg, c),
        evaluate("Optimized", sol.approve, seg, c),
    ])
    fr = frontier(seg, c, solver)

    plot_frontier(fr, c.max_severe_loss_rate, reports / "figures" / "profit_frontier.png")
    write_report(reports / "policy_report.md", policies, c, factors, decision_grid(seg), fr, calib,
                 len(book), float(book["loan_amnt"].sum()), solver)
    seg.to_parquet(data_dir / "policy_segments.parquet", index=False)
    decisions = book.merge(seg[["grade", "risk_band", "approve"]], on=["grade", "risk_band"], how="left")
    decisions[["loan_id", "issue_date", "grade", "risk_band", "approve", "loan_amnt", "is_default", "pd_baseline",
               "profit_baseline", "profit_realized"]].to_parquet(data_dir / "policy_loans.parquet", index=False)
    results = {"constraints": vars(c), "policies": policies.to_dict(orient="records"),
               "frontier": fr.to_dict(orient="records"), "yield_factors": factors.to_dict(orient="records"),
               "calibration": calib, "segments_approved": int(sol.approve.sum()), "segments": int(len(seg))}
    (reports / "optimization_results.json").write_text(json.dumps(results, indent=2, default=float))

    show = policies[["policy", "volume_share", "expected_profit_usd_m", "severe_loss_rate", "realized_profit_usd_m",
                     "realized_return", "meets_constraints"]]
    print(show.to_string(index=False, formatters={"volume_share": "{:.0%}".format, "severe_loss_rate": "{:.2%}".format,
                                                 "realized_return": "{:.2%}".format,
                                                 "expected_profit_usd_m": "{:,.1f}".format,
                                                 "realized_profit_usd_m": "{:,.1f}".format}))
    print(f"Approved {sol.approve.sum()} of {len(seg)} segments · report: {reports / 'policy_report.md'}")
    return results


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", type=Path, default=config.PROCESSED_DIR)
    p.add_argument("--reports", type=Path, default=config.REPORTS_DIR)
    p.add_argument("--max-severe-loss", type=float, default=Constraints.max_severe_loss_rate)
    p.add_argument("--min-volume", type=float, default=Constraints.min_volume_share)
    p.add_argument("--max-risky", type=float, default=Constraints.max_risky_share)
    p.add_argument("--solver", choices=["highs", "gurobi"], default="highs")
    a = p.parse_args()
    run(a.data, a.reports, Constraints(a.max_severe_loss, a.min_volume, a.max_risky), a.solver)


if __name__ == "__main__":
    main()
