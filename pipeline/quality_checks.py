"""Automated data-quality checks on the modeling table.

Each check is a control: it states what must be true, measures it, and
records PASS / WARN / FAIL. A FAIL stops the pipeline, so a bad table
can never reach the model. Results go to reports/data_quality.md and
reports/data_quality.json.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from pipeline import config

TABLE = "loans_model"


@dataclass
class CheckResult:
    check_id: str
    description: str
    severity: str          # "fail" (blocks the pipeline) or "warn"
    passed: bool
    observed: str
    expected: str

    @property
    def status(self) -> str:
        if self.passed:
            return "PASS"
        return "FAIL" if self.severity == "fail" else "WARN"


def _one(con: duckdb.DuckDBPyConnection, sql: str):
    return con.execute(sql).fetchone()[0]


def run_checks(con: duckdb.DuckDBPyConnection, min_rows: int = config.MIN_ROWS) -> list[CheckResult]:
    results: list[CheckResult] = []
    n = _one(con, f"SELECT count(*) FROM {TABLE}")

    # DQ-01 Volume
    results.append(CheckResult(
        "DQ-01", "Table has enough rows to model", "fail",
        n >= min_rows, f"{n:,} rows", f">= {min_rows:,} rows"))

    if n == 0:
        return results  # nothing else is meaningful on an empty table

    # DQ-02 Primary key
    dupes = _one(con, f"SELECT count(*) - count(DISTINCT loan_id) FROM {TABLE}")
    results.append(CheckResult(
        "DQ-02", "loan_id is unique", "fail",
        dupes == 0, f"{dupes:,} duplicate ids", "0 duplicates"))

    # DQ-03 Required fields present
    for col in config.REQUIRED_NOT_NULL:
        nulls = _one(con, f"SELECT count(*) FILTER (WHERE {col} IS NULL) FROM {TABLE}")
        results.append(CheckResult(
            f"DQ-03.{col}", f"{col} is never null", "fail",
            nulls == 0, f"{nulls:,} nulls", "0 nulls"))

    # DQ-04 Target is binary
    bad_target = _one(con, f"SELECT count(*) FILTER (WHERE is_default NOT IN (0, 1)) FROM {TABLE}")
    results.append(CheckResult(
        "DQ-04", "is_default is 0 or 1", "fail",
        bad_target == 0, f"{bad_target:,} invalid values", "0 invalid values"))

    # DQ-05 Default rate is plausible (catches a wrong target definition)
    rate = _one(con, f"SELECT avg(is_default) FROM {TABLE}")
    lo, hi = config.DEFAULT_RATE_RANGE
    results.append(CheckResult(
        "DQ-05", "Default rate is in a plausible range", "fail",
        lo <= rate <= hi, f"{rate:.2%}", f"{lo:.0%} to {hi:.0%}"))

    # DQ-06 Value ranges
    for col, (low, high, severity) in config.RANGE_CHECKS.items():
        share = _one(con, f"""
            SELECT coalesce(avg(CASE WHEN {col} < {low} OR {col} > {high} THEN 1.0 ELSE 0.0 END), 0)
            FROM {TABLE} WHERE {col} IS NOT NULL""")
        results.append(CheckResult(
            f"DQ-06.{col}", f"{col} within [{low:,}, {high:,}]", severity,
            share <= config.MAX_OUT_OF_RANGE_SHARE,
            f"{share:.3%} out of range", f"<= {config.MAX_OUT_OF_RANGE_SHARE:.1%}"))

    # DQ-07 Missingness per feature (warning only)
    all_cols = [r[0] for r in con.execute(f"DESCRIBE {TABLE}").fetchall()]
    feature_cols = [c for c in all_cols if c not in config.REQUIRED_NOT_NULL]
    for col in feature_cols:
        share = _one(con, f"SELECT avg(CASE WHEN {col} IS NULL THEN 1.0 ELSE 0.0 END) FROM {TABLE}")
        results.append(CheckResult(
            f"DQ-07.{col}", f"{col} null share is acceptable", "warn",
            share <= config.MAX_NULL_SHARE, f"{share:.1%} null", f"<= {config.MAX_NULL_SHARE:.0%}"))

    # DQ-08 No leakage columns in the model table
    present = sorted({c.lower() for c in all_cols} & set(config.LEAKAGE_COLUMNS))
    results.append(CheckResult(
        "DQ-08", "No post-issue (leakage) fields in the model table", "fail",
        not present, ", ".join(present) or "none found", "none"))

    # DQ-09 No feature dated after the loan was issued
    future = _one(con, f"""
        SELECT coalesce(avg(CASE WHEN earliest_cr_line_date > issue_date THEN 1.0 ELSE 0.0 END), 0)
        FROM {TABLE} WHERE earliest_cr_line_date IS NOT NULL""")
    results.append(CheckResult(
        "DQ-09", "Credit history starts before the issue date", "fail",
        future <= config.MAX_OUT_OF_RANGE_SHARE, f"{future:.3%} after issue date",
        f"<= {config.MAX_OUT_OF_RANGE_SHARE:.1%}"))

    # DQ-10 Sample definition respected
    outside = _one(con, f"""
        SELECT count(*) FILTER (WHERE issue_year NOT BETWEEN {config.ISSUE_YEAR_MIN} AND {config.ISSUE_YEAR_MAX}
                                   OR split IS NULL)
        FROM {TABLE}""")
    results.append(CheckResult(
        "DQ-10", "Every loan is in the sample window and has a split", "fail",
        outside == 0, f"{outside:,} loans outside", "0 loans outside"))

    # DQ-11 Every split is populated
    for split in ("train", "valid", "oot"):
        k = _one(con, f"SELECT count(*) FROM {TABLE} WHERE split = '{split}'")
        results.append(CheckResult(
            f"DQ-11.{split}", f"'{split}' split has loans", "fail",
            k > 0, f"{k:,} loans", "> 0 loans"))

    # DQ-12 Default rate rises from grade A to G (sanity check on the target)
    rates = [r[1] for r in con.execute(f"""
        SELECT grade, avg(is_default) FROM {TABLE}
        WHERE grade IN ('A','B','C','D','E','F','G')
        GROUP BY grade ORDER BY grade""").fetchall()]
    monotonic = all(a <= b for a, b in zip(rates, rates[1:]))
    results.append(CheckResult(
        "DQ-12", "Default rate increases from grade A to G", "warn",
        monotonic, " < ".join(f"{r:.1%}" for r in rates), "non-decreasing"))

    # DQ-13 Reconciliation: installment matches the amortization formula
    mismatch = _one(con, f"""
        WITH calc AS (
            SELECT installment,
                   loan_amnt * (int_rate / 1200.0)
                     / (1 - pow(1 + int_rate / 1200.0, -{config.TERM_MONTHS})) AS expected
            FROM {TABLE}
            WHERE int_rate > 0 AND installment IS NOT NULL
        )
        SELECT coalesce(avg(CASE WHEN abs(installment - expected) / expected > 0.02 THEN 1.0 ELSE 0.0 END), 0)
        FROM calc""")
    results.append(CheckResult(
        "DQ-13", "Installment reconciles to amount, rate and term (within 2%)", "warn",
        mismatch <= 0.01, f"{mismatch:.2%} mismatched", "<= 1%"))

    return results


def write_report(results: list[CheckResult], out_dir: Path = config.REPORTS_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fails = sum(r.status == "FAIL" for r in results)
    warns = sum(r.status == "WARN" for r in results)

    lines = [
        "# Data quality report",
        "",
        f"Run: {stamp} · Table: `{TABLE}` · "
        f"**{len(results) - fails - warns} passed, {warns} warnings, {fails} failures**",
        "",
        "| ID | Check | Severity | Status | Observed | Expected |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    order = {"FAIL": 0, "WARN": 1, "PASS": 2}
    for r in sorted(results, key=lambda r: (order[r.status], r.check_id)):
        lines.append(f"| {r.check_id} | {r.description} | {r.severity} | {r.status} | {r.observed} | {r.expected} |")

    md_path = out_dir / "data_quality.md"
    md_path.write_text("\n".join(lines) + "\n")
    (out_dir / "data_quality.json").write_text(json.dumps(
        {"run_at": stamp, "results": [asdict(r) | {"status": r.status} for r in results]}, indent=2))
    return md_path
