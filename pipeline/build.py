"""Module 1: build the modeling table from the raw Lending Club file.

Usage:
    python -m pipeline.build                     # finds the file in data/raw/
    python -m pipeline.build --raw path/to/accepted_2007_to_2018Q4.csv.gz
    python -m pipeline.build --raw tests/sample.csv --min-rows 100 --db :memory:

Stages: raw_loans -> stg_loans -> loans_model -> data-quality checks -> Parquet.
Exits with code 1 if any hard data-quality check fails.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb

from pipeline import config
from pipeline.quality_checks import run_checks, write_report

STAGES = ("01_raw_loans.sql", "02_stg_loans.sql", "03_loans_model.sql")


def _sql_list(values) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)


def split_case() -> str:
    whens = " ".join(f"WHEN issue_date BETWEEN DATE '{lo}' AND DATE '{hi}' THEN '{name}'"
                     for name, (lo, hi) in config.SPLIT_PERIODS.items())
    return f"CASE {whens} END"


def render(sql: str, raw_path: Path) -> str:
    replacements = {
        "__RAW_PATH__": str(raw_path).replace("'", "''"),
        "__TERM__": str(config.TERM_MONTHS),
        "__YEAR_MIN__": str(config.ISSUE_YEAR_MIN),
        "__YEAR_MAX__": str(config.ISSUE_YEAR_MAX),
        "__BAD_STATUSES__": _sql_list(config.BAD_STATUSES),
        "__FINAL_STATUSES__": _sql_list(config.GOOD_STATUSES + config.BAD_STATUSES),
        "__SPLIT_CASE__": split_case(),
    }
    for key, value in replacements.items():
        sql = sql.replace(key, value)
    return sql


def find_raw_file() -> Path:
    candidates = sorted(config.RAW_DIR.rglob("accepted_2007_to_2018*.csv*"))
    if not candidates:
        sys.exit(
            f"No Lending Club file found in {config.RAW_DIR}.\n"
            "Run: kaggle datasets download -d wordsforthewise/lending-club -p data/raw --unzip\n"
            "or pass --raw <path>."
        )
    return candidates[0]


def build(raw_path: Path, db_path: str, min_rows: int, out_dir: Path,
          processed_dir: Path = config.PROCESSED_DIR) -> int:
    con = duckdb.connect(db_path)

    for stage in STAGES:
        t0 = time.time()
        con.execute(render((config.SQL_DIR / stage).read_text(), raw_path))
        table = stage.split("_", 1)[1].removesuffix(".sql")
        rows = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        print(f"  {table:<12} {rows:>12,} rows  ({time.time() - t0:.1f}s)")

    results = run_checks(con, min_rows=min_rows)
    report = write_report(results, out_dir)
    fails = [r for r in results if r.status == "FAIL"]
    warns = [r for r in results if r.status == "WARN"]
    print(f"\nData quality: {len(results) - len(fails) - len(warns)} passed, "
          f"{len(warns)} warnings, {len(fails)} failures -> {report}")

    if fails:
        for r in fails:
            print(f"  FAIL {r.check_id}: {r.description} (observed {r.observed}, expected {r.expected})")
        print("Pipeline stopped: the model table was NOT written.")
        con.close()
        return 1

    processed_dir.mkdir(parents=True, exist_ok=True)
    out = processed_dir / "loans_model.parquet"
    con.execute(f"COPY loans_model TO '{out.as_posix()}' (FORMAT PARQUET)")
    print(f"Wrote {out}")
    con.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, help="Path to the Lending Club accepted-loans CSV (.csv or .csv.gz)")
    parser.add_argument("--db", default=str(config.DB_PATH), help="DuckDB file, or :memory:")
    parser.add_argument("--min-rows", type=int, default=config.MIN_ROWS)
    parser.add_argument("--reports", type=Path, default=config.REPORTS_DIR)
    parser.add_argument("--out", type=Path, default=config.PROCESSED_DIR, help="Folder for loans_model.parquet")
    args = parser.parse_args()

    raw = args.raw or find_raw_file()
    if args.db != ":memory:":
        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    print(f"Building from {raw}")
    sys.exit(build(raw, args.db, args.min_rows, args.reports, args.out))


if __name__ == "__main__":
    main()
