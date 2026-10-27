"""Tests for Module 10 (rates and credit spreads). Synthetic FRED series and loans, no downloads.
Run from the repo root:  pytest -q"""

import numpy as np
import pandas as pd
import pytest

from market import fred as FR
from market.analysis import modified_duration, price, wal_years
from market.run import analyze, plot_history, plot_spreads, write_report


def test_amortization_math():
    assert wal_years(0) == pytest.approx(37 / 24)                    # equal principal: (n+1)/2 months
    assert wal_years(5) < wal_years(15) < wal_years(25)              # higher rate: principal comes back later
    assert price(12, 12) == pytest.approx(1.0)                        # a loan is worth par at its own rate
    assert price(12, 13) < 1 < price(12, 11)
    d = modified_duration(12)
    assert 1.2 < d < wal_years(12)                                    # duration below WAL for an amortizer
    assert price(12, 12.01) - 1 == pytest.approx(-d * 0.0001, rel=0.01)


def test_fred_parsing_and_changes():
    csv = "observation_date,BAA10Y\n2010-01-04,2.0\n2010-01-05,.\n2010-01-06,4.0\n2010-02-01,3.5\n2010-03-01,5.0\n"
    s = FR.parse_fred_csv(csv, "BAA10Y")
    assert s[pd.Period("2010-01", "M")] == pytest.approx(3.0)        # monthly mean, '.' skipped
    dates = pd.Series(pd.to_datetime(["2010-01-01", "2010-02-01"]))
    ch = FR.forward_change(dates, s, horizon=2)
    assert ch.iloc[0] == pytest.approx((3.5 + 5.0) / 2 - 3.0) and np.isnan(ch.iloc[1])
    assert FR.at_issue(dates, s).tolist() == [3.0, 3.5]


def synthetic(seed=0, effect="baa"):
    """Monthly market series 2007-2018 with a 2008-09 spread blow-out, and loans whose default
    risk follows either the Baa-spread change or the unemployment change."""
    rng = np.random.default_rng(seed)
    months = pd.period_range("2007-01", "2018-12", freq="M")
    t = np.arange(len(months))
    baa = 2 + 3.5 * np.exp(-((t - 24) / 7) ** 2) + 0.3 * np.sin(t / 5)
    unrate = 5 + 4 * np.exp(-((t - 34) / 14) ** 2) + 0.2 * np.cos(t / 7)
    market = pd.DataFrame({"DGS3": 1 + 0.3 * np.sin(t / 9), "DGS2": 0.8 + 0.2 * np.sin(t / 9),
                           "DGS10": 2.5 + 0.2 * np.sin(t / 11), "BAA10Y": baa}, index=months)
    un = pd.Series(unrate, index=months)
    n = 60_000
    issue = pd.to_datetime(rng.choice(pd.period_range("2007-01", "2015-12", freq="M").to_timestamp(), n))
    fico = rng.normal(705, 30, n)
    d_baa = FR.forward_change(pd.Series(issue), market["BAA10Y"], 24).to_numpy()
    d_un = FR.forward_change(pd.Series(issue), un, 24).to_numpy()
    driver = np.nan_to_num(d_baa if effect == "baa" else d_un)
    z = -1.8 - 0.02 * (fico - 705) + 0.35 * driver
    y = (rng.random(n) < 1 / (1 + np.exp(-z))).astype(int)
    grade = np.select([fico > 740, fico > 715, fico > 690, fico > 670], list("ABCD"), "E")
    rate = pd.Series(grade).map({"A": 7.5, "B": 11.0, "C": 14.0, "D": 17.5, "E": 21.0}).to_numpy()
    loans = pd.DataFrame({"loan_id": np.arange(n), "issue_date": issue, "fico_mid": fico, "is_default": y,
                          "grade": grade, "int_rate": rate, "loan_amnt": 10_000.0,
                          "split": np.where(issue.year == 2015, "oot", "train")})
    book = loans[loans["split"] == "oot"].assign(pd_baseline=lambda d: 1 / (1 + np.exp(-(-1.8 - 0.02 * (d["fico_mid"] - 705)))),
                                                 lgd=0.85)
    outcomes = pd.DataFrame({"loan_id": loans["loan_id"], "loss_rate": np.where(y == 1, 0.8, 0.0)})
    return loans, book, outcomes, market, un


@pytest.fixture(scope="module")
def result():
    return analyze(*synthetic())


def test_spread_table_economics(result):
    t = result["spreads"].set_index("grade")
    assert (t["loss_adjusted_spread_bp"] < t["spread_bp"]).all()     # losses always reduce the spread
    assert t.loc["E", "expected_loss_bp"] > t.loc["A", "expected_loss_bp"]
    assert t.loc["Book", "loans"] == t.drop("Book")["loans"].sum()


def test_rate_risk_signs(result):
    r = result["rate_risk"]
    shocks = {s["shock_bp"]: s["value_change_usd_m"] for s in r["shocks"]}
    assert shocks[100] < 0 < shocks[-100] and shocks[200] < shocks[100]
    assert r["dv01_usd"] < 0
    assert r["floating_funding_cost_per_100bp_usd_m"] == pytest.approx(
        r["principal_usd_m"] * r["wal_years"] * 0.01, rel=0.02)


def test_glm_picks_the_true_driver():
    for effect, winner in [("baa", "Baa spread change"), ("unemp", "Unemployment change (Module 3)")]:
        m = analyze(*synthetic(seed=1, effect=effect))["models"].set_index("model")
        single = m.loc[["Baa spread change", "Unemployment change (Module 3)"]]
        assert single["aic"].idxmin() == winner, (effect, single["aic"].to_dict())


def test_report_and_figures(result, tmp_path):
    (tmp_path / "figures").mkdir()
    plot_spreads(result["spreads"], result["baa_book"], tmp_path / "figures" / "s.png")
    plot_history(result["history"], tmp_path / "figures" / "h.png")
    write_report(tmp_path / "market_report.md", result)
    text = (tmp_path / "market_report.md").read_text()
    assert "bp a year over 3-year Treasuries" in text and "DV01" in text and "fred.stlouisfed.org" in text
    assert (tmp_path / "figures" / "s.png").stat().st_size > 5_000


def test_fico_bands_match_stress_module():
    from market.analysis import FICO_BANDS
    from stress.run import FICO_BANDS as STRESS_BANDS

    assert FICO_BANDS == STRESS_BANDS
