"""Module 10: the loan book through a fixed-income lens (Treasury yields and credit spreads from FRED).

  1. Pricing and relative value: each 2015 loan's spread over the 3-year Treasury at issue,
     less its expected annual credit loss, by grade, next to the Baa corporate bond spread.
  2. Interest-rate risk: duration, DV01 and the value change of the book for parallel rate
     shocks; the extra cost if the book were funded at a floating rate.
  3. Market signals: does the change in the Baa spread explain cohort default rates as well
     as, or better than, the unemployment change used in Module 3? Compared by AIC and by
     out-of-time deviance (fit on 2007-2012 cohorts, scored on 2013-2014).

Usage:
    python -m market.run
    python -m market.run --refresh      # re-download the FRED series
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

from market import fred as FR  # noqa: E402
from market.analysis import compare_models, cohorts, rate_risk, spread_table  # noqa: E402
from models.train import md_table  # noqa: E402
from pipeline import config  # noqa: E402

HORIZON = 24                     # same shock window as Module 3
ESTIMATION_END = "2014-12-31"
SPLIT_MONTH = "2012-12"          # market-signal models: fit through 2012, score 2013-2014
MODELS = {
    "Unemployment change (Module 3)": ["d_unemp"],
    "Baa spread change": ["d_baa"],
    "Both changes": ["d_unemp", "d_baa"],
    "Unemployment change + Baa spread at issue": ["d_unemp", "baa_at_issue"],
}
BLUE, ORANGE, AQUA, INK2, GRID = "#2a78d6", "#eb6834", "#1baf7a", "#52514e", "#e1e0d9"


def analyze(loans: pd.DataFrame, book: pd.DataFrame, outcomes: pd.DataFrame, market: pd.DataFrame,
            unrate: pd.Series) -> dict:
    """loans: modeling table; book: Module 3 stressed 2015 book; market: monthly FRED series;
    unrate: monthly unemployment rate indexed by Period('M')."""
    loans = loans.copy()
    loans["issue_date"] = pd.to_datetime(loans["issue_date"])
    b = book.merge(outcomes[["loan_id", "loss_rate"]], on="loan_id", how="left")
    b["issue_date"] = pd.to_datetime(b["issue_date"])
    b["ust3"] = FR.at_issue(b["issue_date"], market["DGS3"])
    b["pd"] = b["pd_baseline"]
    b = b.dropna(subset=["ust3", "int_rate", "pd", "lgd"])
    book_months = b["issue_date"].dt.to_period("M").unique()
    baa_book = float(market["BAA10Y"].reindex(book_months).mean())

    # 1. pricing and relative value
    spreads = spread_table(b, baa_book)

    # 2. rate risk
    risk = rate_risk(b)

    # 3. market signals vs. cohort defaults (loans issued before 2015, as in Module 3)
    est = loans[loans["issue_date"] <= ESTIMATION_END].copy()
    est["d_unemp"] = FR.forward_change(est["issue_date"], unrate, HORIZON)
    est["d_baa"] = FR.forward_change(est["issue_date"], market["BAA10Y"], HORIZON)
    est["baa_at_issue"] = FR.at_issue(est["issue_date"], market["BAA10Y"])
    c = cohorts(est, ["d_unemp", "d_baa", "baa_at_issue"])
    models = compare_models(c, MODELS, SPLIT_MONTH)

    q = est.assign(quarter=est["issue_date"].dt.to_period("Q")).groupby("quarter").agg(
        loans=("is_default", "size"), default_rate=("is_default", "mean")).reset_index()
    mq = market.groupby(market.index.asfreq("Q")).mean()
    history = q.merge(mq[["BAA10Y", "DGS3"]], left_on="quarter", right_index=True, how="left")

    return {"spreads": spreads, "baa_book": baa_book, "rate_risk": risk, "models": models,
            "cohorts": int(len(c)), "history": history,
            "book_window": f"{b['issue_date'].min():%b %Y}–{b['issue_date'].max():%b %Y}",
            "ust3_book": float(np.average(b["ust3"], weights=b["loan_amnt"]))}


# --- figures --------------------------------------------------------------------------
def _style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#c3c2b7")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK2, labelsize=9)


def plot_spreads(t: pd.DataFrame, baa: float, path: Path) -> None:
    g = t[t["grade"] != "Book"]
    x = np.arange(len(g))
    w = 0.26
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.bar(x - w - 0.02, g["spread_bp"], w, color=BLUE, label="Spread over 3-yr Treasury")
    ax.bar(x, g["loss_adjusted_spread_bp"], w, color=ORANGE, label="After expected losses")
    ax.bar(x + w + 0.02, g["realized_loss_adjusted_spread_bp"], w, color=AQUA, label="After realized losses")
    ax.axhline(baa * 100, color=INK2, linewidth=1, linestyle="--", label=f"Baa corporate spread ({baa * 100:.0f} bp)")
    ax.axhline(0, color="#c3c2b7", linewidth=1)
    ax.set_xticks(x, g["grade"])
    ax.set(xlabel="Lending Club grade", ylabel="Basis points per year", title="What each grade paid over Treasuries, 2015 loans")
    _style(ax)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_history(h: pd.DataFrame, path: Path) -> None:
    h = h[h["loans"] >= 50]
    x = h["quarter"].dt.to_timestamp()
    fig, axes = plt.subplots(3, 1, figsize=(7.5, 6.4), sharex=True)
    for ax, col, color, title, fmt in [
        (axes[0], "default_rate", BLUE, "Default rate of loans issued that quarter", PercentFormatter(1.0, 0)),
        (axes[1], "BAA10Y", ORANGE, "Baa corporate spread over 10-yr Treasury, %", None),
        (axes[2], "DGS3", AQUA, "3-year Treasury yield, %", None),
    ]:
        ax.plot(x, h[col], color=color, linewidth=2)
        ax.set_title(title, loc="left", fontsize=10, color=INK2)
        if fmt:
            ax.yaxis.set_major_formatter(fmt)
        _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# --- report -----------------------------------------------------------------------------
def write_report(path: Path, r: dict) -> None:
    t, risk, m = r["spreads"], r["rate_risk"], r["models"]
    book = t[t["grade"] == "Book"].iloc[0]
    a = t[t["grade"] == "A"].iloc[0] if (t["grade"] == "A").any() else None
    up100 = next(s for s in risk["shocks"] if s["shock_bp"] == 100)
    base = m.iloc[0]
    best = m.sort_values("oot_deviance").iloc[0]
    baa_only = m[m["model"] == "Baa spread change"].iloc[0]
    both = m[m["model"] == "Both changes"].iloc[0]
    if best["model"] == base["model"]:
        signal = (f"Unemployment remains the better stress driver: the Baa-spread model scores "
                  f"{baa_only['oot_deviance'] - base['oot_deviance']:+,.0f} deviance out of time, and adding the spread "
                  f"to unemployment changes AIC by {both['aic'] - base['aic']:+,.1f}.")
    else:
        signal = (f"The **{best['model'].lower()}** model predicts 2013–2014 cohort defaults best "
                  f"(out-of-time deviance {best['oot_deviance'] - base['oot_deviance']:+,.0f} vs. Module 3's unemployment model).")
    lead = [
        f"After expected credit losses, the 2015 book earned **{book['loss_adjusted_spread_bp']:,.0f} bp a year over "
        f"3-year Treasuries** ({book['spread_bp']:,.0f} bp coupon spread less {book['expected_loss_bp']:,.0f} bp of expected loss); "
        f"after the losses that actually happened, {book['realized_loss_adjusted_spread_bp']:,.0f} bp. "
        f"Baa corporate bonds paid {r['baa_book'] * 100:,.0f} bp over the 10-year Treasury in the same months, before any losses.",
        "",
        f"The book's modified duration is **{risk['modified_duration']:.2f} years**: a parallel +100 bp move cuts its value by "
        f"**${-up100['value_change_usd_m']:,.1f}M ({-up100['value_change_pct']:.2%})**, a DV01 of ${-risk['dv01_usd']:,.0f}. "
        f"Funded at a floating rate, each +100 bp would cost ${risk['floating_funding_cost_per_100bp_usd_m']:,.1f}M over the loans' life.",
        "",
        signal,
    ]
    if a is not None:
        lead.insert(1, f"Grade A loans earned {a['loss_adjusted_spread_bp']:,.0f} bp after expected losses, "
                       f"{a['vs_baa_bp']:+,.0f} bp against the Baa spread.")
    show = t[["grade", "loans", "principal_usd_m", "coupon", "treasury_3y", "spread_bp", "wal_years", "pd", "lgd",
              "expected_loss_bp", "loss_adjusted_spread_bp", "realized_loss_bp", "realized_loss_adjusted_spread_bp"]]
    shocks = pd.DataFrame(risk["shocks"])
    mshow = m[["model", "aic", "delta_aic", "oot_deviance", "dispersion"] +
              [c for c in m.columns if c.endswith(("_coef", "_z_adj"))]]
    lines = [
        "# Rates and credit spreads: the loan book as a fixed-income asset",
        "",
        *lead,
        "",
        f"Book: {int(book['loans']):,} loans issued {r['book_window']}, ${book['principal_usd_m']:,.0f}M of principal. "
        f"Average 3-year Treasury at issue {r['ust3_book']:.2f}%.",
        "",
        "## 1. Pricing and relative value",
        "",
        "Dollar-weighted by grade. Annual loss = lifetime loss rate (PD × LGD, or the realized loss) ÷ weighted-average "
        "life of a 36-month level-payment loan. PD is the Module 3 baseline-scenario PD; LGD is the Module 3 estimate.",
        "",
        md_table(show, {"loans": ",", "principal_usd_m": ",.0f", "coupon": ".2f", "treasury_3y": ".2f", "spread_bp": ",.0f",
                        "wal_years": ".2f", "pd": ".1%", "lgd": ".0%", "expected_loss_bp": ",.0f",
                        "loss_adjusted_spread_bp": ",.0f", "realized_loss_bp": ",.0f",
                        "realized_loss_adjusted_spread_bp": ",.0f"}),
        "",
        "![Spreads by grade](figures/market_spreads_by_grade.png)",
        "",
        "The Baa spread is quoted over the 10-year Treasury and before default losses, so it is a benchmark for the price "
        "of corporate credit risk, not a like-for-like maturity match.",
        "",
        "## 2. Interest-rate risk",
        "",
        f"Weighted-average life {risk['wal_years']:.2f} years, modified duration {risk['modified_duration']:.2f} years. "
        "Each loan's fixed cash flows are re-discounted at its own rate plus the shock.",
        "",
        md_table(shocks, {"value_change_usd_m": ",.1f", "value_change_pct": ".2%"}),
        "",
        "Prepayment is ignored, so these are upper bounds: borrowers who prepay shorten the book's life and its rate risk.",
        "",
        "## 3. Do market signals explain defaults?",
        "",
        f"Binomial GLM on {r['cohorts']:,} issue-month × FICO-band cohorts issued before 2015 (FICO-band intercepts, as in "
        f"Module 3). A change is the average over the {HORIZON} months after issue minus the value at issue. "
        "`oot_deviance`: fit on cohorts through 2012, scored on 2013–2014 cohorts. `z_adj` is overdispersion-adjusted. "
        "Lower AIC and deviance are better.",
        "",
        md_table(mshow, {"aic": ",.1f", "delta_aic": ",.1f", "oot_deviance": ",.1f", "dispersion": ".1f",
                         **{c: ".3f" for c in mshow.columns if c.endswith("_coef")},
                         **{c: ".1f" for c in mshow.columns if c.endswith("_z_adj")}}),
        "",
        "![History](figures/market_history.png)",
        "",
        "## Data",
        "",
        "Series: " + ", ".join(f"`{k}` ({v})" for k, v in FR.SERIES.items()) + ". Daily values are averaged by month.",
        "",
        f"Source: {FR.CITATION}. Moody's data is cited, not redistributed: the series stay in the git-ignored `data/raw/fred/`.",
        "",
    ]
    path.write_text("\n".join(lines))


def run(data_dir: Path = config.PROCESSED_DIR, reports: Path = config.REPORTS_DIR, refresh: bool = False) -> dict:
    from stress.macro import load_unemployment

    (reports / "figures").mkdir(parents=True, exist_ok=True)
    loans = pd.read_parquet(data_dir / "loans_model.parquet")
    book = pd.read_parquet(data_dir / "stressed_book.parquet")
    outcomes = pd.read_parquet(data_dir / "loan_outcomes.parquet")
    market = FR.load_series(refresh=refresh)
    u = load_unemployment(refresh=refresh)
    r = analyze(loans, book, outcomes, market, u.set_index("month")["unrate"])

    plot_spreads(r["spreads"], r["baa_book"], reports / "figures" / "market_spreads_by_grade.png")
    plot_history(r["history"], reports / "figures" / "market_history.png")
    write_report(reports / "market_report.md", r)
    results = {"spreads": r["spreads"].to_dict(orient="records"), "baa_spread_book_pct": r["baa_book"],
               "rate_risk": r["rate_risk"], "models": r["models"].to_dict(orient="records"),
               "cohorts": r["cohorts"], "book_window": r["book_window"], "ust3_book_pct": r["ust3_book"]}
    (reports / "market_results.json").write_text(json.dumps(results, indent=2, default=float))

    b = r["spreads"][r["spreads"]["grade"] == "Book"].iloc[0]
    up = next(s for s in r["rate_risk"]["shocks"] if s["shock_bp"] == 100)
    print(f"Loss-adjusted spread over 3-yr Treasury: {b['loss_adjusted_spread_bp']:,.0f} bp "
          f"(realized {b['realized_loss_adjusted_spread_bp']:,.0f} bp); Baa spread {r['baa_book'] * 100:,.0f} bp")
    print(f"Duration {r['rate_risk']['modified_duration']:.2f} yrs: +100 bp -> ${up['value_change_usd_m']:,.1f}M "
          f"({up['value_change_pct']:.2%}); DV01 ${r['rate_risk']['dv01_usd']:,.0f}")
    print(r["models"][["model", "delta_aic", "oot_deviance"]].to_string(index=False, float_format="{:,.1f}".format))
    print(f"Report: {reports / 'market_report.md'}")
    return results


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--refresh", action="store_true", help="re-download FRED series")
    a = p.parse_args()
    run(refresh=a.refresh)


if __name__ == "__main__":
    main()
