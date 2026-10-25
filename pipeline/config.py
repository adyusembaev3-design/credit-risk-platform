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

# Time-based split used by Module 2 (out-of-time validation), by issue month.
# The extended credit-bureau fields (BUREAU_FIELDS) are only reported from 2013,
# so the PD model is built on 2013-2015. Earlier loans are kept as 'history':
# they span the 2008-09 recession and feed the macro stress test (Module 3).
SPLIT_PERIODS = {            # split: (first issue month, last issue month), inclusive
    "history": ("2007-01-01", "2012-12-01"),
    "train": ("2013-01-01", "2014-06-01"),
    "valid": ("2014-07-01", "2014-12-01"),
    "oot": ("2015-01-01", "2015-12-01"),
}
MODEL_SPLITS = ("train", "valid", "oot")

# Extended bureau attributes at application (99-100% populated from 2013).
BUREAU_FIELDS = (
    "acc_open_past_24mths", "bc_util", "bc_open_to_buy", "num_tl_op_past_12m",
    "percent_bc_gt_75", "tot_hi_cred_lim", "total_rev_hi_lim", "tot_cur_bal",
    "avg_cur_bal", "mo_sin_old_rev_tl_op", "mo_sin_rcnt_tl", "num_actv_rev_tl",
    "pct_tl_nvr_dlq",
)
# Null here means "no such event on file" (no delinquency / no recent inquiry),
# which is information, not missing data. Excluded from null-share warnings.
NULL_MEANS_NONE = ("mths_since_last_delinq", "mths_since_recent_inq")
MIN_BUREAU_FILL = 0.95       # DQ-14: share of model-split loans with each bureau field

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
MIN_ROWS = 100_000            # real sample is ~618K rows; tests override this
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
    "bc_util": (0, 200, "warn"),
    "percent_bc_gt_75": (0, 100, "warn"),
    "pct_tl_nvr_dlq": (0, 100, "warn"),
}
