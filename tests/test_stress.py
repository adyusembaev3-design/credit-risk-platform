"""Tests for Module 3 (stress testing). Run from the repo root:  pytest -q"""

import numpy as np
import pandas as pd
import pytest

from models.train import run as train_run
from pipeline.build import build
from stress.glm import expit, fit_binomial
from stress.macro import load_unemployment, unemployment_change
from stress.run import SCENARIOS, run as stress_run
from tests.make_sample import write_sample, write_unrate_csv


def test_glm_recovers_known_coefficients():
    rng = np.random.default_rng(1)
    k = 400
    x = rng.normal(size=k)
    band = rng.integers(0, 2, k)
    X = np.column_stack([band == 0, band == 1, x]).astype(float)
    true = np.array([-2.0, -1.0, 0.4])
    n = rng.integers(200, 2000, k)
    y = rng.binomial(n, expit(X @ true))
    res = fit_binomial(X, y, n, ["b0", "b1", "x"])
    assert np.allclose(res.coef, true, atol=3 * res.se.max() + 0.02)
    assert (res.se > 0).all()


def test_unemployment_change(tmp_path):
    csv = tmp_path / "u.csv"
    rows = ["observation_date,UNRATE"] + [f"2010-{m:02d}-01,{4 + m}" for m in range(1, 13)]
    csv.write_text("\n".join(rows))
    u = load_unemployment(csv)
    d = unemployment_change(pd.Series(pd.to_datetime(["2010-01-01", "2010-11-01"])), u, horizon=2)
    assert d.iloc[0] == pytest.approx((6 + 7) / 2 - 5)   # Feb, Mar vs Jan
    assert np.isnan(d.iloc[1])                             # needs Dec and next Jan


@pytest.fixture(scope="module")
def stressed(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("m3")
    raw = write_sample(tmp / "sample.csv", n=8000)
    processed = tmp / "processed"
    assert build(raw, str(tmp / "t.duckdb"), 500, tmp / "dq", processed) == 0
    train_run(processed / "loans_model.parquet", tmp / "reports", tmp / "artifacts",
              processed / "scored_loans.parquet", None, 200, 20, use_mlflow=False)
    results = stress_run(processed, tmp / "reports", write_unrate_csv(tmp / "unrate.csv"))
    return tmp, results


def test_recovers_macro_sensitivity(stressed):
    _, res = stressed
    beta = res["sensitivity"]["beta_per_pp"]
    assert 0.15 < beta < 0.5            # synthetic data was generated with 0.30


def test_losses_rise_with_severity(stressed):
    tmp, res = stressed
    el = {r["scenario"]: r["expected_loss_usd_m"] for r in res["scenarios"]}
    assert el["Baseline"] < el["Adverse"] < el["Severe"]
    assert set(SCENARIOS) <= set(el)
    book = pd.read_parquet(tmp / "processed" / "stressed_book.parquet")
    assert (book["pd_severe"] >= book["pd_baseline"]).all()
    assert book["lgd"].between(0, 1).all()
    assert (tmp / "reports" / "stress_report.md").exists()
    assert np.isfinite(res["backtest"]["ratio"])
