"""Settings for Module 1: paths, sample definition, and data-quality thresholds."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
REPORTS_DIR = ROOT / "reports"
SQL_DIR = Path(__file__).resolve().parent / "sql"
DB_PATH = ROOT / "data" / "credit.duckdb"

# --- Sample definition -------------------------------------------------------
# 36-month loans issued 2007-2015 have all matured by the 2018Q4 snapshot,
# so almost every loan has a final outcome (paid off or charged off).
# Using later vintages would bias the default rate down, because their
# bad loans have not had time to default yet.
TERM_MONTHS = 36
ISSUE_YEAR_MIN = 2007
ISSUE_YEAR_MAX = 2015

# Final outcomes only. "Current" and "Late" loans have no final outcome yet.
GOOD_STATUSES = ("Fully Paid",)
BAD_STATUSES = ("Charged Off", "Default")

# Time-based split used by Module 2 (out-of-time validation).
TRAIN_YEARS = (2007, 2012)
VALID_YEARS = (2013, 2013)
OOT_YEARS = (2014, 2015)

# --- Leakage -----------------------------------------------------------------
# Fields only known AFTER the loan is issued. None may enter the model table.
LEAKAGE_COLUMNS = (
    "total_pymnt", "total_pymnt_inv", "total_rec_prncp", "total_rec_int",
    "total_rec_late_fee", "recoveries", "collection_recovery_fee",
    "last_pymnt_d", "last_pymnt_amnt", "next_pymnt_d", "last_credit_pull_d",
    "last_fico_range_high", "last_fico_range_low", "out_prncp", "out_prncp_inv",
    "funded_amnt_inv", "pymnt_plan", "hardship_flag", "debt_settlement_flag",
    "settlement_status", "loan_status",
)

# --- Data-quality thresholds -------------------------------------------------
MIN_ROWS = 100_000            # real sample is ~600K rows; tests override this
DEFAULT_RATE_RANGE = (0.05, 0.30)
MAX_OUT_OF_RANGE_SHARE = 0.001  # hard checks tolerate 0.1% odd rows
MAX_NULL_SHARE = 0.20           # warning threshold per feature

REQUIRED_NOT_NULL = (
    "loan_id", "issue_date", "is_default", "loan_amnt", "int_rate",
    "grade", "annual_inc", "fico_mid",
)

# column: (low, high, severity)
RANGE_CHECKS = {
    "loan_amnt": (500, 40_000, "fail"),
    "int_rate": (5, 31, "fail"),
    "fico_mid": (600, 850, "fail"),
    "annual_inc": (0, 10_000_000, "fail"),
    "dti": (0, 60, "warn"),
    "revol_util": (0, 150, "warn"),
    "credit_history_years": (0, 70, "warn"),
}
