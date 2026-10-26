"""Tests for Module 7 (governance and controls). Run from the repo root:  pytest -q"""

import json
import subprocess

import pytest

from governance.controls import FAIL, NA, PASS, WARN, Context, run_controls
from governance.run import run, update_incidents


def write(root, rel, obj):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj))


def good_results(root, gbm_oot=0.688, psi=0.014, ratio=0.95, decision="Launch the challenger"):
    perf = [{"model": m, "split": s, "auc": a, "ks": 0.3, "mean_pd": 0.15, "default_rate": 0.155}
            for m, s, a in (("GBM", "train", 0.745), ("GBM", "oot", gbm_oot), ("Sub-grade benchmark", "oot", 0.679))]
    write(root, "reports/model_metrics.json", {"performance": perf, "psi": {"GBM": psi}, "gbm_trees": 473,
                                               "calibration_oot": [{"ratio": 1.1}, {"ratio": 0.9}]})
    write(root, "reports/data_quality.json", {"results": [{"check_id": "DQ-01", "status": "PASS"}]})
    write(root, "reports/stress_results.json", {"backtest": {"ratio": ratio},
                                                "sensitivity": {"beta_per_pp": 0.15, "se_overdispersion_adjusted": 0.016,
                                                                "odds_multiplier_per_pp": 1.16}})
    write(root, "reports/optimization_results.json", {
        "constraints": {"max_severe_loss_rate": 0.10, "min_volume_share": 0.5},
        "policies": [{"policy": "Optimized", "meets_constraints": "yes", "severe_loss_rate": 0.098, "volume_share": 0.6}],
        "calibration": {"expected_usd_m": 20.1, "realized_usd_m": 12.4}})
    write(root, "reports/experiment_results.json", {"decision": decision, "readout": {
        "uplift_ci_low": 62.5, "default_rate_challenger": 0.121, "default_rate_champion": 0.150}})
    write(root, "reports/agent_eval.json", [{"correct": True, "invalid_citations": 0, "supported_claims": 9,
                                             "judged_claims": 10}] * 3)


def status(rows, cid):
    return next(r for r in rows if r["id"] == cid)["status"]


def test_controls_on_healthy_results(tmp_path):
    good_results(tmp_path)
    rows = run_controls(Context(tmp_path))
    assert len(rows) == 16
    for cid in ("C-01", "C-03", "C-04", "C-05", "C-06", "C-09", "C-10", "C-11", "C-13", "C-15"):
        assert status(rows, cid) == PASS, cid
    assert status(rows, "C-12") == WARN          # profit overstated 1.6x: review, as in incident INC-003
    assert status(rows, "C-02") == NA            # no parquet in this fixture
    assert all(r["owner"] and r["threshold"] for r in rows)


def test_controls_catch_problems(tmp_path):
    good_results(tmp_path, gbm_oot=0.62, psi=0.31, ratio=0.6, decision="Launch the challenger")
    write(tmp_path, "reports/experiment_results.json", {"decision": "Launch the challenger", "readout": {
        "uplift_ci_low": -5.0, "default_rate_challenger": 0.16, "default_rate_champion": 0.15}})
    rows = run_controls(Context(tmp_path))
    assert status(rows, "C-03") == FAIL          # below the performance floor
    assert status(rows, "C-05") == FAIL          # population shift
    assert status(rows, "C-09") == FAIL          # stress test badly understates losses
    assert status(rows, "C-13") == FAIL          # launched although the rule says no


def test_failures_open_one_incident_each(tmp_path):
    rows = [{"id": "C-03", "status": FAIL, "risk": "r", "observed": "AUC 0.62"},
            {"id": "C-05", "status": PASS, "risk": "r", "observed": "ok"}]
    path = tmp_path / "incidents.json"
    path.write_text(json.dumps([{"id": "INC-005", "control": "C-09", "status": "closed"}]))
    inc = update_incidents(rows, path, today="2026-10-26")
    assert [i["id"] for i in inc] == ["INC-005", "INC-006"] and inc[-1]["control"] == "C-03"
    assert len(update_incidents(rows, path)) == 2      # already open: no duplicate


def test_secret_scan(tmp_path):
    if subprocess.run(["git", "--version"], capture_output=True).returncode:
        pytest.skip("git not installed")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "ok.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "ok.py"], cwd=tmp_path, check=True)
    assert status(run_controls(Context(tmp_path)), "C-16") == PASS
    fake_key = "sk-ant-" + "api03-" + "Ab3" * 12          # built at runtime so this file holds no key
    (tmp_path / "leak.py").write_text(f'KEY = "{fake_key}"\n')
    subprocess.run(["git", "add", "leak.py"], cwd=tmp_path, check=True)
    assert status(run_controls(Context(tmp_path)), "C-16") == FAIL


def test_run_writes_report_and_model_card(tmp_path):
    good_results(tmp_path)
    (tmp_path / "governance").mkdir()
    (tmp_path / "governance" / "incidents.json").write_text("[]")
    run(tmp_path, today="2026-10-26")
    report = (tmp_path / "reports" / "controls_report.md").read_text()
    card = (tmp_path / "docs" / "model_card.md").read_text()
    assert "Risk and controls register" in report and "C-16" in report
    assert "Model card" in card and "0.688" in card and "1.16" in card
