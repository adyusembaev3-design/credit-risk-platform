"""End-to-end test of Module 1 on a synthetic Lending Club file.

Run from the repo root:  pytest -q
"""

import csv

import duckdb
import pytest

from pipeline import config
from pipeline.build import build
from tests.make_sample import write_sample

MIN_ROWS = 500


@pytest.fixture()
def sample(tmp_path):
    return write_sample(tmp_path / "sample.csv")


def run(raw, tmp_path):
    db = str(tmp_path / "test.duckdb")
    code = build(raw, db, MIN_ROWS, tmp_path / "reports", tmp_path / "processed")
    return code, db


def test_pipeline_passes_on_clean_sample(sample, tmp_path):
    code, _ = run(sample, tmp_path)
    assert code == 0
    assert (tmp_path / "processed" / "loans_model.parquet").exists()
    report = (tmp_path / "reports" / "data_quality.md").read_text()
    assert "| FAIL |" not in report


def test_filters_and_leakage(sample, tmp_path):
    _, db = run(sample, tmp_path)
    con = duckdb.connect(db, read_only=True)
    cols = {r[0] for r in con.execute("DESCRIBE loans_model").fetchall()}
    assert not cols & set(config.LEAKAGE_COLUMNS), "post-issue fields leaked into the model table"

    # Only matured 36-month loans with a final outcome
    stg = con.execute("""
        SELECT count(*) FROM stg_loans
        WHERE term_months = 36 AND year(issue_date) BETWEEN 2007 AND 2015
          AND loan_status IN ('Fully Paid', 'Charged Off', 'Default')""").fetchone()[0]
    model = con.execute("SELECT count(*) FROM loans_model").fetchone()[0]
    assert model == stg > MIN_ROWS

    # Footer row dropped, rates parsed from both "13.5" and "13.5%"
    raw = con.execute("SELECT count(*) FROM raw_loans").fetchone()[0]
    staged = con.execute("SELECT count(*) FROM stg_loans").fetchone()[0]
    assert staged == raw - 1
    assert con.execute("SELECT count(*) FROM stg_loans WHERE int_rate IS NULL").fetchone()[0] == 0


def test_duplicate_ids_stop_the_pipeline(sample, tmp_path):
    # Copy the first data row onto the end: same loan_id twice
    rows = list(csv.reader(sample.open()))
    with sample.open("a", newline="") as f:
        csv.writer(f).writerow(rows[1])
    code, _ = run(sample, tmp_path)
    assert code == 1
    report = (tmp_path / "reports" / "data_quality.md").read_text()
    assert "DQ-02" in report and "| FAIL |" in report
    assert not (tmp_path / "processed" / "loans_model.parquet").exists()
