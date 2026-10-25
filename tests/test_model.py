"""End-to-end test of Module 2 on the synthetic sample (real LightGBM, real DuckDB).

Run from the repo root:  pytest -q
"""

import json

import numpy as np
import pandas as pd
import pytest

from models import features as F
from models.metrics import calibration_table, ks_statistic, psi
from models.reason_codes import top_reasons
from models.train import run
from pipeline.build import build
from tests.make_sample import write_sample


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("m2")
    raw = write_sample(tmp / "sample.csv", n=8000)
    assert build(raw, str(tmp / "t.duckdb"), 500, tmp / "dq", tmp / "processed") == 0
    metrics = run(tmp / "processed" / "loans_model.parquet", tmp / "reports", tmp / "artifacts",
                  tmp / "processed" / "scored_loans.parquet", None, 200, 20, use_mlflow=False)
    return tmp, metrics


def test_outputs_written(trained):
    tmp, _ = trained
    for f in ("model_report.md", "model_metrics.json", "scorecard_points.csv",
              "figures/roc_oot.png", "figures/calibration_oot.png"):
        assert (tmp / "reports" / f).exists(), f
    for f in ("lgbm_model.txt", "scorecard.json", "gbm_categories.json"):
        assert (tmp / "artifacts" / f).exists(), f
    scorecard = json.loads((tmp / "artifacts" / "scorecard.json").read_text())
    assert not set(scorecard["selected_features"]) & set(F.EXCLUDED)


def test_models_learn_signal(trained):
    _, metrics = trained
    oot = {r["model"]: r for r in metrics["performance"] if r["split"] == "oot"}
    assert oot["WOE scorecard"]["auc"] > 0.65
    assert oot["GBM"]["auc"] > 0.65
    assert 0 <= metrics["psi"]["GBM"] < 1


def test_scored_loans(trained):
    tmp, _ = trained
    s = pd.read_parquet(tmp / "processed" / "scored_loans.parquet")
    assert s["loan_id"].is_unique
    assert s["pd_gbm"].between(0, 1).all() and s["pd_scorecard"].between(0, 1).all()
    assert set(s["split"]) == {"train", "valid", "oot"}
    # Higher scorecard points must mean lower predicted risk
    assert s["scorecard_points"].rank().corr(s["pd_scorecard"].rank()) < -0.95
    high = s.nlargest(50, "pd_gbm")
    assert high["reason_1"].notna().all()


def test_metric_helpers():
    y = np.array([0, 0, 1, 1])
    assert ks_statistic(y, np.array([0.1, 0.2, 0.8, 0.9])) == pytest.approx(1.0)
    rng = np.random.default_rng(0)
    a = rng.normal(size=5000)
    assert psi(a, a) < 0.01
    assert psi(a, a + 1) > 0.25
    t = calibration_table(rng.integers(0, 2, 1000), rng.random(1000))
    assert len(t) == 10 and t["loans"].sum() == 1000


def test_reason_codes_only_risk_raising_features():
    contrib = np.array([[0.5, -0.2, 0.1], [-0.3, -0.1, -0.4]])
    r = top_reasons(contrib, ["fico_mid", "dti", "purpose"], k=2)
    assert r.loc[0, "reason_1_feature"] == "fico_mid" and r.loc[0, "reason_2_feature"] == "purpose"
    assert r.loc[1].isna().all()  # nothing raised this loan's risk
