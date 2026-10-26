"""Tests for Module 4 (credit policy optimization). Run from the repo root:  pytest -q"""

import itertools

import numpy as np
import pandas as pd
import pytest

from models.train import run as train_run
from optimize.profit import expected_profit, funding_cost
from optimize.run import run as optimize_run
from optimize.solver import Constraints, is_feasible, solve
from pipeline.build import build
from stress.run import run as stress_run
from tests.make_sample import write_sample, write_unrate_csv


def test_solver_matches_brute_force():
    rng = np.random.default_rng(3)
    k = 12
    exposure = rng.uniform(1, 10, k)
    severe = exposure * rng.uniform(0.02, 0.25, k)
    profit = exposure * rng.uniform(-0.05, 0.12, k)
    risky = rng.random(k) < 0.3
    c = Constraints(max_severe_loss_rate=0.10, min_volume_share=0.3, max_risky_share=0.2)
    sol = solve(profit, exposure, severe, risky, c)
    best = -np.inf
    for bits in itertools.product([0, 1], repeat=k):
        x = np.array(bits, dtype=bool)
        if is_feasible(x, exposure, severe, risky, c):
            best = max(best, profit[x].sum())
    assert sol.status == "optimal"
    assert is_feasible(sol.approve, exposure, severe, risky, c)
    assert sol.objective == pytest.approx(best)


def test_expected_profit_formula():
    book = pd.DataFrame({"grade": ["A"], "installment": [100.0], "loan_amnt": [3000.0],
                         "lgd": [0.6], "pd": [0.1]})
    factors = pd.DataFrame({"grade": ["A"], "yield_good": [0.8], "yield_bad": [0.3]})
    sched = 100 * 36 - 3000                       # 600
    want = 0.9 * sched * 0.8 + 0.1 * (sched * 0.3 - 0.6 * 3000) - funding_cost(book).iloc[0]
    assert expected_profit(book, "pd", factors).iloc[0] == pytest.approx(want)


@pytest.fixture(scope="module")
def optimized(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("m4")
    raw = write_sample(tmp / "sample.csv", n=8000)
    processed = tmp / "processed"
    assert build(raw, str(tmp / "t.duckdb"), 500, tmp / "dq", processed) == 0
    train_run(processed / "loans_model.parquet", tmp / "reports", tmp / "artifacts",
              processed / "scored_loans.parquet", None, 200, 20, use_mlflow=False)
    stress_run(processed, tmp / "reports", write_unrate_csv(tmp / "unrate.csv"))
    c = Constraints(max_severe_loss_rate=0.15, min_volume_share=0.4, max_risky_share=0.25)
    return tmp, optimize_run(processed, tmp / "reports", c), c


def test_optimized_policy(optimized):
    tmp, res, c = optimized
    pol = {p["policy"]: p for p in res["policies"]}
    opt = pol["Optimized"]
    assert opt["meets_constraints"] == "yes"
    assert opt["severe_loss_rate"] <= c.max_severe_loss_rate + 1e-9
    assert opt["volume_share"] >= c.min_volume_share - 1e-9
    for name, p in pol.items():          # never worse than any benchmark that is also feasible
        if p["meets_constraints"] == "yes":
            assert opt["expected_profit_usd_m"] >= p["expected_profit_usd_m"] - 1e-9, name
    assert (tmp / "reports" / "policy_report.md").exists()
    assert (tmp / "reports" / "figures" / "profit_frontier.png").exists()


def test_frontier_profit_rises_with_budget(optimized):
    _, res, _ = optimized
    profits = [r["expected_profit_usd_m"] for r in res["frontier"]]
    assert len(profits) > 3
    assert all(b >= a - 1e-9 for a, b in zip(profits, profits[1:]))
