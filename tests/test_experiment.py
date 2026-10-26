"""Tests for Module 5 (champion/challenger experiment). Run from the repo root:  pytest -q"""

import numpy as np
import pytest
from scipy import stats

from experiment.run import run as experiment_run
from experiment.stats import bootstrap_ci, required_n_per_arm, two_proportion, welch
from models.train import run as train_run
from optimize.run import run as optimize_run
from optimize.solver import Constraints
from pipeline.build import build
from stress.run import run as stress_run
from tests.make_sample import write_sample, write_unrate_csv


def test_welch_matches_scipy():
    rng = np.random.default_rng(0)
    a, b = rng.normal(0, 1, 500), rng.normal(0.2, 2, 700)
    w = welch(a, b)
    ref = stats.ttest_ind(b, a, equal_var=False)
    assert w["p_value"] == pytest.approx(ref.pvalue)
    assert w["ci_low"] < w["diff"] < w["ci_high"]
    lo, hi = bootstrap_ci(a, b, n_boot=300)
    assert lo < w["diff"] < hi


def test_power_formula_hits_target():
    # Simulate at the sample size the formula asks for: about 80% of tests should reject
    n = required_n_per_arm(effect=0.1, sd_a=1.0, sd_b=1.0)
    rng = np.random.default_rng(1)
    hits = sum(welch(rng.normal(0, 1, n), rng.normal(0.1, 1, n))["p_value"] < 0.05 for _ in range(300))
    assert 0.72 < hits / 300 < 0.88


def test_two_proportion():
    r = two_proportion(100, 1000, 100, 1000)
    assert r["diff"] == 0 and r["p_value"] == pytest.approx(1.0)


@pytest.fixture(scope="module")
def experiment(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("m5")
    raw = write_sample(tmp / "sample.csv", n=8000)
    processed = tmp / "processed"
    assert build(raw, str(tmp / "t.duckdb"), 500, tmp / "dq", processed) == 0
    train_run(processed / "loans_model.parquet", tmp / "reports", tmp / "artifacts",
              processed / "scored_loans.parquet", None, 200, 20, use_mlflow=False)
    stress_run(processed, tmp / "reports", write_unrate_csv(tmp / "unrate.csv"))
    optimize_run(processed, tmp / "reports", Constraints(0.15, 0.4, 0.25))
    res = experiment_run(processed, tmp / "reports", n_boot=100, n_splits=10, n_sims=50, sizes=(100, 300, 600))
    return tmp, res


def test_experiment_outputs(experiment):
    tmp, res = experiment
    r = res["readout"]
    assert r["n_champion"] + r["n_challenger"] > 1000
    assert 0 < r["approval_rate_challenger"] <= 1
    assert r["uplift_ci_low"] <= r["uplift"] <= r["uplift_ci_high"]
    assert res["decision"] in ("Launch the challenger", "Do not launch")
    assert res["design"]["n_per_arm"] > 0
    assert (tmp / "reports" / "experiment_report.md").exists()
    assert (tmp / "reports" / "figures" / "power_curve.png").exists()
