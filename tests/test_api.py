"""Tests for Module 9 (decision API). A synthetic bundle and a stand-in model are used,
so no real data or LightGBM file is needed. Run from the repo root:  pytest -q"""

import json

import numpy as np
import pandas as pd
import pytest

from api.export import SCENARIOS, stress_grid
from api.service import Platform
from models import features as F
from stress.glm import expit, logit

BETA, D_TRAIN = 0.12, -0.8


def predict(X):
    z = -1.8 - 0.03 * (X["fico_mid"].fillna(700) - 700) + 0.01 * (X["bc_util"].fillna(50) - 50)
    return 1 / (1 + np.exp(-np.asarray(z, float)))


def contrib(X):
    c = np.zeros((len(X), len(F.FEATURES)))
    c[:, F.FEATURES.index("fico_mid")] = -0.03 * (X["fico_mid"].fillna(700).to_numpy() - 700)
    c[:, F.FEATURES.index("bc_util")] = 0.01 * (X["bc_util"].fillna(50).to_numpy() - 50)
    return c


def application(rng, i):
    a = {c: float(rng.normal(10, 3)) for c in F.NUMERIC}
    a.update(fico_mid=float(rng.normal(700, 40)), bc_util=float(rng.uniform(0, 100)))
    a.update({c: "a" for c in F.CATEGORICAL}, grade=str(rng.choice(list("ABCDEFG"))), loan_id=f"L{i}")
    return a


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    rng = np.random.default_rng(0)
    d = tmp_path_factory.mktemp("bundle")
    apps = [application(rng, i) for i in range(400)]
    p = predict(pd.DataFrame(apps))
    base = expit(logit(p) + BETA * (0 - D_TRAIN))
    edges = np.quantile(base, np.linspace(0, 1, 11)[1:-1])
    policy = [{"grade": g, "risk_band": b, "approve": b <= 7} for g in "ABCDEFG" for b in range(1, 11)]
    (d / "scorer.json").write_text(json.dumps({
        "model_version": "test123", "beta_per_pp": BETA, "d_unemp_train": D_TRAIN, "band_edges": edges.tolist(),
        "scenarios": SCENARIOS, "categories": {c: ["a", "b"] for c in F.CATEGORICAL}, "policy": policy}))
    book = pd.DataFrame({"grade": [a["grade"] for a in apps], "loan_amnt": 10_000.0, "pd_gbm": p, "lgd": 0.9})
    (d / "stress_grid.json").write_text(json.dumps(stress_grid(book, BETA, D_TRAIN)))
    (d / "samples.json").write_text(json.dumps(apps[:50]))
    (d / "dashboard.json").write_text(json.dumps({"model": {"performance": []}}))
    return d, apps, book


@pytest.fixture(scope="module")
def platform(bundle):
    return Platform(bundle[0], predict=predict, contrib=contrib)


def test_score_matches_policy_and_stress_shift(platform, bundle):
    _, apps, _ = bundle
    out = platform.score(apps[:200])
    assert len(out) == 200 and {o["loan_id"] for o in out} == {a["loan_id"] for a in apps[:200]}
    for o in out:
        assert (o["decision"] == "approve") == (o["risk_band"] <= 7)
        assert o["pd_by_scenario"]["Severe"] > o["pd_by_scenario"]["Adverse"] > o["pd_by_scenario"]["Baseline"]
        assert o["pd_by_scenario"]["Baseline"] == pytest.approx(o["pd_baseline"])
        assert len(o["reasons"]) <= 3
        assert all(isinstance(r["feature"], str) and isinstance(r["text"], str) for r in o["reasons"])


def test_risky_applicant_gets_reasons(platform, bundle):
    a = dict(bundle[1][0], fico_mid=600.0, bc_util=99.0)
    o = platform.score([a])[0]
    assert o["decision"] == "decline"
    assert {r["feature"] for r in o["reasons"]} == {"fico_mid", "bc_util"}
    assert all(r["text"] for r in o["reasons"])


def test_missing_fields_are_allowed(platform):
    o = platform.score([{"grade": "B", "fico_mid": 720.0}])[0]
    assert o["missing_fields"] == len(F.FEATURES) - 1 and o["loan_id"] == "app-1"


def test_stress_grid_matches_scenarios(platform, bundle):
    _, _, book = bundle
    for d in SCENARIOS.values():
        p = expit(logit(book["pd_gbm"].to_numpy()) + BETA * (d - D_TRAIN))
        assert platform.stress(d)["mean_pd"] == pytest.approx(p.mean())
    rates = [g["loss_rate"] for g in platform.grid]
    assert all(np.diff(rates) > 0)                                # more unemployment, more loss
    assert platform.stress(2.6)["d_unemp"] == 2.5                   # snaps to 0.25 pp
    with pytest.raises(ValueError):
        platform.stress(20)


# --- HTTP layer (needs fastapi + httpx) --------------------------------------------
@pytest.fixture(scope="module")
def client(platform):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from api.main import create_app

    with TestClient(create_app(platform)) as c:
        yield c


def test_http_score_and_validation(client, bundle):
    apps = bundle[1][:5]
    r = client.post("/api/score", json={"applications": apps})
    assert r.status_code == 200 and "X-Process-Time-Ms" in r.headers
    body = r.json()
    assert body["model_version"] == "test123" and len(body["decisions"]) == 5
    bad_grade = client.post("/api/score", json={"applications": [dict(apps[0], grade="Z")]})
    protected = client.post("/api/score", json={"applications": [dict(apps[0], addr_state="CA")]})
    empty = client.post("/api/score", json={"applications": []})
    assert bad_grade.status_code == protected.status_code == empty.status_code == 422


def test_http_read_endpoints(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert "addr_state" in client.get("/api/meta").json()["excluded_for_fair_lending"]
    assert len(client.get("/api/applications/sample", params={"n": 3, "seed": 1}).json()) == 3
    assert client.get("/api/stress", params={"d_unemp": 5}).json()["d_unemp"] == 5
    assert client.get("/api/stress", params={"d_unemp": 50}).status_code == 422
    assert "model" in client.get("/api/dashboard").json()
