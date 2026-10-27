"""Tests for Module 6 (live scoring and monitoring). No Kafka needed: the memory backend
runs the same scoring and monitoring code. Run from the repo root:  pytest -q"""

import numpy as np
import pandas as pd
import pytest

from models import features as F
from streaming.monitor import RollingPSI, StreamMonitor, psi
from streaming.run import Metrics, make_monitor, run_memory, write_report
from streaming.scorer import PolicyScorer
from streaming.source import inject_drift, load_applications


def fake_loans(n, split, rng):
    d = pd.DataFrame({c: rng.normal(10, 3, n) for c in F.NUMERIC})
    d["fico_mid"] = rng.normal(700, 30, n)
    d["bc_util"] = rng.uniform(0, 100, n)
    d["acc_open_past_24mths"] = rng.integers(0, 12, n).astype(float)
    for c in F.CATEGORICAL:
        d[c] = rng.choice(["a", "b"], n)
    d["grade"] = rng.choice(list("ABCDEFG"), n)
    d["loan_id"] = [f"{split}{i}" for i in range(n)]
    d["issue_date"] = pd.Timestamp("2015-01-01")
    d["loan_amnt"] = 10_000.0
    d["split"] = split
    d["is_default"] = (rng.random(n) < predict(d)).astype(int)
    return d


def predict(X):
    z = -1.8 - 0.03 * (X["fico_mid"] - 700) + 0.01 * (X["bc_util"] - 50) + 0.1 * (X["acc_open_past_24mths"] - 6)
    return 1 / (1 + np.exp(-np.asarray(z, float)))


@pytest.fixture(scope="module")
def setup():
    rng = np.random.default_rng(0)
    loans = pd.concat([fake_loans(15_000, "train", rng), fake_loans(30_000, "oot", rng)], ignore_index=True)
    edges = np.quantile(predict(loans[loans["split"] == "oot"]), np.linspace(0, 1, 11)[1:-1])
    policy = pd.DataFrame([(g, b, b <= 7) for g in "ABCDEFG" for b in range(1, 11)],
                          columns=["grade", "risk_band", "approve"])
    scorer = PolicyScorer(predict, lambda X: rng.normal(0, 0.1, (len(X), len(F.FEATURES))), 0.0, 0.0, edges, policy,
                          {c: ["a", "b"] for c in F.CATEGORICAL})
    scored = pd.DataFrame({"split": "train", "pd_gbm": predict(loans[loans["split"] == "train"])})
    return loans, scorer, scored


def test_psi_basics():
    rng = np.random.default_rng(1)
    ref = rng.normal(size=20_000)
    same, shifted = RollingPSI(ref, 5000), RollingPSI(ref, 5000)
    same.update(rng.normal(size=5000))
    shifted.update(rng.normal(1.0, 1, 5000))
    assert same.value < 0.02 and shifted.value > 0.25
    assert psi(np.array([10, 10.0]), np.array([10, 10.0])) == pytest.approx(0)


def test_drift_injection_only_after_start():
    b = pd.DataFrame({"fico_mid": [700.0] * 100, "bc_util": [50.0] * 100, "acc_open_past_24mths": [2.0] * 100})
    assert inject_drift(b, 0, 1000, 0).equals(b)                 # batch entirely before drift
    after = inject_drift(b, 1000, 1000, 0)
    hit = after["fico_mid"] < 700
    assert 0.4 < hit.mean() < 0.8 and (after.loc[hit, "bc_util"] == 75).all()


def test_applications_have_unique_columns(setup):
    loans, scorer, _ = setup
    apps = load_applications(loans)
    assert apps.columns.is_unique                                   # a duplicate column breaks LightGBM
    assert scorer.matrix(apps.head(10)).shape[1] == len(F.FEATURES)


def test_scorer_applies_policy(setup):
    loans, scorer, _ = setup
    dec = scorer.score(loans[loans["split"] == "oot"].head(2000))
    assert set(dec.columns) >= {"loan_id", "pd", "risk_band", "approve", "reason_1"}
    assert dec["risk_band"].between(1, 10).all()
    assert not dec.loc[dec["risk_band"] >= 8, "approve"].any()     # policy declines bands 8-10
    assert dec.loc[dec["risk_band"] <= 7, "approve"].all()


def test_stream_detects_drift_without_false_alarms(setup, tmp_path):
    loans, scorer, scored = setup
    apps = load_applications(loans)
    mon = make_monitor(loans, scored, window=5000)
    dec = run_memory(scorer, apps, mon, drift_at=15_000, metrics=Metrics(None))
    assert len(dec) == len(apps) and mon.processed == len(apps)
    fired = {r: a.first_at for r, a in mon.alerts.items()}
    assert all(at >= 15_000 for at in fired.values()), fired      # nothing fires before drift
    assert "score_psi" in fired and fired["score_psi"] - 15_000 < 5_000
    summary = write_report(tmp_path / "r.md", mon, dec, 15_000, 1.0, "memory")
    assert summary["false_alarms_before_drift"] == 0 and summary["first_alert"]["delay"] < 5_000
    assert summary["approval_rate_after"] < summary["approval_rate_before"]


def test_no_alerts_without_drift(setup):
    loans, scorer, scored = setup
    mon = make_monitor(loans, scored, window=5000)
    run_memory(scorer, load_applications(loans), mon, drift_at=None, metrics=Metrics(None))
    assert not [r for r in mon.alerts if r != "latency_p95"]


def test_monitor_alert_hysteresis():
    rng = np.random.default_rng(2)
    m = StreamMonitor(rng.normal(size=10_000), {}, window=2000)
    for _ in range(10):
        m.update(rng.normal(size=500), {}, np.ones(500))
    m.update(rng.normal(2, 1, 2000), {}, np.ones(2000))
    first = m.alerts["score_psi"].first_at
    m.update(rng.normal(2, 1, 2000), {}, np.ones(2000))
    assert m.alerts["score_psi"].first_at == first                 # not re-opened while active
