"""Module 3: macroeconomic stress test of the 2015 loan book.

Steps
  1. Macro sensitivity: for every issue-month x FICO-band cohort issued before 2015,
     regress the realized default rate on the unemployment change the cohort lived
     through (binomial GLM, FICO-band intercepts). Pre-2013 'history' loans supply
     the 2008-09 recession.
  2. Loss given default: average realized loss rate of defaulted loans by grade,
     from loans issued before 2015.
  3. Scenarios: shift each 2015 loan's model PD in log-odds by
        beta x (scenario unemployment change - change during the PD training period)
     because the PD model learned under the training period's macro conditions.
  4. Expected loss = PD x LGD x loan amount, by scenario and grade.
  5. Backtest: the 'Realized' scenario uses the unemployment path 2015 loans
     actually experienced; its expected loss is compared with their actual losses.

Every parameter is estimated on loans issued before 2015, so the backtest is out-of-time.

Usage:
    python -m stress.run
    python -m stress.run --refresh-macro      # re-download unemployment from FRED
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
from pipeline import config  # noqa: E402
from stress.glm import expit, fit_binomial, logit  # noqa: E402
from stress.macro import CACHE, load_unemployment, unemployment_change  # noqa: E402

HORIZON_MONTHS = 24          # most 36-month loan defaults happen in the first two years
BOOK_SPLIT = "oot"           # the 2015 loans act as the current portfolio
ESTIMATION_END = "2014-12-31"
FICO_BANDS = [(0, 680), (680, 700), (700, 720), (720, 750), (750, 900)]
# Average change in unemployment over the next 24 months, percentage points.
# For reference, US unemployment rose about 4.4 pp from 2007 to its 2009 peak.
SCENARIOS = {"Baseline": 0.0, "Adverse": 2.5, "Severe": 5.0}


def fico_band(fico: pd.Series) -> pd.Series:
    labels = [f"{lo}-{hi - 1}" if lo else f"<{hi}" for lo, hi in FICO_BANDS]
    labels[-1] = f"{FICO_BANDS[-1][0]}+"
    edges = [b[0] for b in FICO_BANDS] + [FICO_BANDS[-1][1]]
    return pd.cut(fico, edges, right=False, labels=labels).astype(str)


# --- 1. macro sensitivity ------------------------------------------------------
def fit_sensitivity(loans: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    est = loans[(loans["issue_date"] <= ESTIMATION_END) & loans["d_unemp"].notna()].copy()
    est["band"] = fico_band(est["fico_mid"])
    est["month"] = est["issue_date"].dt.to_period("M")
    cohorts = (est.groupby(["month", "band"], observed=True)
               .agg(loans=("is_default", "size"), defaults=("is_default", "sum"), d_unemp=("d_unemp", "first"))
               .reset_index())
    bands = sorted(cohorts["band"].unique())
    X = np.column_stack([(cohorts["band"] == b).astype(float) for b in bands] + [cohorts["d_unemp"]])
    names = [f"band {b}" for b in bands] + ["d_unemp"]
    res = fit_binomial(X, cohorts["defaults"], cohorts["loans"], names)

    # Overdispersion: cohorts share calendar time, so binomial SEs are too small.
    p = expit(X @ res.coef)
    n, y = cohorts["loans"].to_numpy(), cohorts["defaults"].to_numpy()
    pearson = np.sum((y - n * p) ** 2 / (n * p * (1 - p)))
    scale = max(1.0, pearson / (len(cohorts) - X.shape[1]))
    beta, se = float(res.coef[-1]), float(res.se[-1])
    out = {
        "beta_per_pp": beta,
        "se": se,
        "se_overdispersion_adjusted": se * np.sqrt(scale),
        "dispersion": float(scale),
        "odds_multiplier_per_pp": float(np.exp(beta)),
        "cohorts": int(len(cohorts)),
        "loans": int(cohorts["loans"].sum()),
        "estimation_window": f"{est['issue_date'].min():%b %Y}–{est['issue_date'].max():%b %Y}",
        "d_unemp_range": [float(cohorts["d_unemp"].min()), float(cohorts["d_unemp"].max())],
        "coefficients": res.as_dict(),
    }
    return out, cohorts


# --- 2. loss given default -----------------------------------------------------
def lgd_by_grade(loans: pd.DataFrame, outcomes: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    d = loans[["loan_id", "grade", "issue_date"]].merge(outcomes[["loan_id", "is_default", "loss_rate"]], on="loan_id")
    d = d[(d["issue_date"] <= ESTIMATION_END) & (d["is_default"] == 1) & d["loss_rate"].notna()]
    t = d.groupby("grade").agg(defaults=("loss_rate", "size"), lgd=("loss_rate", "mean")).reset_index()
    overall = float(d["loss_rate"].mean())
    return t, overall


# --- 3-5. scenarios, expected loss, backtest -----------------------------------
def stress_book(book: pd.DataFrame, beta: float, d_train: float, scenarios: dict[str, float]) -> pd.DataFrame:
    base_logit = logit(book["pd_gbm"].to_numpy())
    for name, d in scenarios.items():
        key = name.lower()
        pd_s = expit(base_logit + beta * (d - d_train))
        book[f"pd_{key}"] = pd_s
        book[f"el_{key}"] = pd_s * book["lgd"] * book["loan_amnt"]
    return book


def summarize(book: pd.DataFrame, scenarios: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    exposure = book["loan_amnt"].sum()
    rows = []
    for s in scenarios:
        k = s.lower()
        rows.append({"scenario": s, "mean_pd": book[f"pd_{k}"].mean(),
                     "expected_loss_usd_m": book[f"el_{k}"].sum() / 1e6,
                     "loss_rate": book[f"el_{k}"].sum() / exposure})
    by_scn = pd.DataFrame(rows)
    by_grade = book.groupby("grade").agg(loans=("loan_id", "size"), exposure_usd_m=("loan_amnt", lambda x: x.sum() / 1e6),
                                         lgd=("lgd", "mean")).reset_index()
    for s in scenarios:
        k = s.lower()
        g = book.groupby("grade").apply(lambda x: x[f"el_{k}"].sum() / x["loan_amnt"].sum(), include_groups=False)
        by_grade[f"loss_rate_{k}"] = by_grade["grade"].map(g)
    return by_scn, by_grade


def plot_history(cohorts: pd.DataFrame, path: Path) -> None:
    c = cohorts.assign(quarter=cohorts["month"].dt.asfreq("Q"), w=cohorts["d_unemp"] * cohorts["loans"])
    q = c.groupby("quarter").agg(loans=("loans", "sum"), defaults=("defaults", "sum"), w=("w", "sum"))
    q = q[q["loans"] >= 30]
    x = q.index.to_timestamp()
    fig, ax = plt.subplots(figsize=(7.5, 4))
    l1 = ax.plot(x, q["defaults"] / q["loans"], color="#1f4e8c", linewidth=1.8, marker="o", markersize=3,
                 label="Default rate (left)")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_ylabel("Default rate, loans issued that quarter")
    ax2 = ax.twinx()
    l2 = ax2.plot(x, q["w"] / q["loans"], color="#c0504d", linewidth=1.5, linestyle="--",
                  label="Unemployment change over next 24 months (right)")
    ax2.axhline(0, color="grey", linewidth=0.8)
    ax2.set_ylabel("Change in unemployment, pp")
    ax.legend(l1 + l2, [ln.get_label() for ln in l1 + l2], loc="upper right", frameon=False, fontsize=8)
    ax.set_title("Default rate vs. the unemployment change each vintage lived through")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_scenarios(by_grade: pd.DataFrame, scenarios: list[str], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 4))
    w = 0.8 / len(scenarios)
    xs = np.arange(len(by_grade))
    colors = ["#9db3d1", "#4f7cb8", "#1f3f6e", "#c0504d"]
    for i, s in enumerate(scenarios):
        ax.bar(xs + (i - (len(scenarios) - 1) / 2) * w, by_grade[f"loss_rate_{s.lower()}"], w, label=s, color=colors[i % 4])
    ax.set_xticks(xs, by_grade["grade"])
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set(xlabel="Lending Club grade", ylabel="Expected loss, % of principal",
           title="Expected loss by grade and scenario, 2015 book")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _m(x: float) -> str:
    return f"{x:,.0f}" if abs(x) >= 100 else f"{x:,.1f}"


def write_report(path: Path, sens: dict, d_train: float, d_book: float, lgd_t: pd.DataFrame, lgd_all: float,
                 by_scn: pd.DataFrame, by_grade: pd.DataFrame, backtest: dict, n_book: int, exposure: float) -> None:
    base = by_scn.set_index("scenario")
    sev, bl = base.loc["Severe", "expected_loss_usd_m"], base.loc["Baseline", "expected_loss_usd_m"]
    lines = [
        "# Stress test report",
        "",
        f"A 5-point rise in unemployment would lift expected losses on the 2015 book from "
        f"**${_m(bl)}M to ${_m(sev)}M** ({sev / bl - 1:+.0%}). Each 1-point rise multiplies default odds by "
        f"**{sens['odds_multiplier_per_pp']:.2f}**, estimated from {sens['loans']:,} loans issued "
        f"{sens['estimation_window']}.",
        "",
        f"Book: {n_book:,} loans issued in 2015, ${exposure / 1e6:,.0f}M of principal. "
        "All parameters are estimated on loans issued before 2015.",
        "",
        "## Backtest",
        "",
        f"2015 loans lived through an average unemployment change of **{d_book:+.2f} pp** over their first "
        f"{HORIZON_MONTHS} months. Under that realized path the model expects "
        f"**${_m(backtest['expected_usd_m'])}M** of losses; actual losses were **${_m(backtest['actual_usd_m'])}M** "
        f"(ratio {backtest['ratio']:.2f}).",
        "",
        "## Scenarios",
        "",
        "Unemployment change is the average over the next 24 months relative to today, in percentage points "
        f"(Baseline 0, Adverse +{SCENARIOS['Adverse']}, Severe +{SCENARIOS['Severe']}). The PD model was trained on "
        f"loans that saw a {d_train:+.2f} pp change, so every scenario shifts PD by "
        "beta × (scenario change − training change).",
        "",
        md_table(by_scn, {"mean_pd": ".2%", "expected_loss_usd_m": ",.1f", "loss_rate": ".2%"}),
        "",
        "![Scenarios](figures/stress_by_grade.png)",
        "",
        md_table(by_grade, {"exposure_usd_m": ",.1f", "lgd": ".1%", "loans": ",",
                            **{c: ".2%" for c in by_grade.columns if c.startswith("loss_rate_")}}),
        "",
        "## Macro sensitivity",
        "",
        f"Binomial GLM of default on the 24-month unemployment change, with FICO-band intercepts, fit on "
        f"{sens['cohorts']:,} issue-month × FICO-band cohorts. Unemployment changes in the data range from "
        f"{sens['d_unemp_range'][0]:+.1f} to {sens['d_unemp_range'][1]:+.1f} pp.",
        "",
        md_table(pd.DataFrame([{"term": "unemployment change (per pp)", "coef": sens["beta_per_pp"],
                                "se": sens["se"], "se_adjusted": sens["se_overdispersion_adjusted"],
                                "odds_multiplier": sens["odds_multiplier_per_pp"]}]),
                 {"coef": ".3f", "se": ".3f", "se_adjusted": ".3f", "odds_multiplier": ".2f"}),
        "",
        f"`se_adjusted` widens the binomial standard error for overdispersion (dispersion {sens['dispersion']:.1f}), "
        "because cohorts issued in the same months share the same economy.",
        "",
        "![History](figures/default_vs_unemployment.png)",
        "",
        "## Loss given default",
        "",
        f"Realized loss of principal on defaulted loans issued before 2015 (net of recoveries and collection fees); "
        f"overall {lgd_all:.1%}. Held at these through-the-cycle averages in every scenario.",
        "",
        md_table(lgd_t, {"lgd": ".1%", "defaults": ","}),
        "",
        "## Limitations",
        "",
        "- One recession in the data: the sensitivity rests mostly on 2007–2008 vintages, which are small.",
        "- Lending Club tightened underwriting after 2008; FICO-band intercepts absorb only part of that mix shift.",
        "- LGD is not stressed; downturn LGD would raise severe-scenario losses further.",
        "- The 24-month window ignores defaults in months 25–36 shifting with later macro conditions.",
        "",
    ]
    path.write_text("\n".join(lines))


def run(data_dir: Path, reports: Path, unrate_path: Path, refresh: bool = False) -> dict:
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "figures").mkdir(exist_ok=True)
    loans = pd.read_parquet(data_dir / "loans_model.parquet")
    outcomes = pd.read_parquet(data_dir / "loan_outcomes.parquet")
    scored = pd.read_parquet(data_dir / "scored_loans.parquet")
    loans["issue_date"] = pd.to_datetime(loans["issue_date"])

    unrate = load_unemployment(unrate_path, refresh)
    loans["d_unemp"] = unemployment_change(loans["issue_date"], unrate, HORIZON_MONTHS)

    sens, cohorts = fit_sensitivity(loans)
    beta = sens["beta_per_pp"]
    d_train = float(loans.loc[loans["split"] == "train", "d_unemp"].mean())
    print(f"Macro sensitivity: beta {beta:.3f} per pp (odds x{np.exp(beta):.2f}), "
          f"{sens['cohorts']} cohorts; training-period change {d_train:+.2f} pp")

    lgd_t, lgd_all = lgd_by_grade(loans, outcomes)
    book = scored[scored["split"] == BOOK_SPLIT].copy()
    book = book.merge(loans[["loan_id", "d_unemp"]], on="loan_id", how="left")
    book["lgd"] = book["grade"].map(dict(zip(lgd_t["grade"], lgd_t["lgd"]))).fillna(lgd_all)
    d_book = float(book["d_unemp"].mean())

    scenarios = {**SCENARIOS, "Realized": d_book}
    book = stress_book(book, beta, d_train, scenarios)
    by_scn, by_grade = summarize(book, list(scenarios))

    actual = book.merge(outcomes[["loan_id", "loss_rate"]], on="loan_id", how="left")
    actual_usd = float((actual["loss_rate"].fillna(0) * actual["loan_amnt"] * actual["is_default"]).sum())
    expected_usd = float(book["el_realized"].sum())
    backtest = {"actual_usd_m": actual_usd / 1e6, "expected_usd_m": expected_usd / 1e6,
                "ratio": expected_usd / actual_usd if actual_usd else float("nan"), "d_unemp_book": d_book}

    plot_history(cohorts, reports / "figures" / "default_vs_unemployment.png")
    plot_scenarios(by_grade, list(SCENARIOS), reports / "figures" / "stress_by_grade.png")
    write_report(reports / "stress_report.md", sens, d_train, d_book, lgd_t, lgd_all, by_scn,
                 by_grade, backtest, len(book), float(book["loan_amnt"].sum()))

    keep = ["loan_id", "issue_date", "grade", "sub_grade", "int_rate", "loan_amnt", "installment", "is_default",
            "pd_gbm", "lgd"] + [c for c in book.columns if c.startswith(("pd_", "el_")) and c != "pd_gbm"]
    book[[c for c in dict.fromkeys(keep) if c in book.columns]].to_parquet(data_dir / "stressed_book.parquet", index=False)

    results = {"sensitivity": sens, "d_unemp_train": d_train, "scenarios": by_scn.to_dict(orient="records"),
               "backtest": backtest, "lgd_by_grade": lgd_t.to_dict(orient="records"), "lgd_overall": lgd_all}
    (reports / "stress_results.json").write_text(json.dumps(results, indent=2, default=str))

    print(by_scn.to_string(index=False, formatters={"mean_pd": "{:.2%}".format, "loss_rate": "{:.2%}".format,
                                                   "expected_loss_usd_m": "{:,.1f}".format}))
    print(f"Backtest: expected ${backtest['expected_usd_m']:,.1f}M vs actual ${backtest['actual_usd_m']:,.1f}M "
          f"(ratio {backtest['ratio']:.2f})")
    print(f"Report: {reports / 'stress_report.md'}")
    return results


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", type=Path, default=config.PROCESSED_DIR)
    p.add_argument("--reports", type=Path, default=config.REPORTS_DIR)
    p.add_argument("--unrate", type=Path, default=CACHE)
    p.add_argument("--refresh-macro", action="store_true")
    a = p.parse_args()
    run(a.data, a.reports, a.unrate, a.refresh_macro)


if __name__ == "__main__":
    main()
