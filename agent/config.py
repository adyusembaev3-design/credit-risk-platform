"""Settings for the AI risk analyst (Module 8)."""

import os

from pipeline import config

AGENT_DIR = config.ROOT / "data" / "agent"
FILINGS_DIR = AGENT_DIR / "filings"
INDEX_PATH = AGENT_DIR / "index.json"
MEMO_DIR = config.REPORTS_DIR / "memos"

# Consumer lenders whose latest 10-K the analyst can read
TICKERS = ("ATLC", "SYF", "COF", "LC")

# Project documents the analyst can read (markdown reports written by Modules 1-5)
PROJECT_DOCS = (
    "reports/data_quality.md",
    "reports/model_report.md",
    "reports/stress_report.md",
    "reports/policy_report.md",
    "reports/experiment_report.md",
    "docs/data_dictionary.md",
    "README.md",
)

# Machine-readable results the analyst can quote exactly
RESULTS_FILES = {
    "model_metrics": "reports/model_metrics.json",
    "stress_results": "reports/stress_results.json",
    "optimization_results": "reports/optimization_results.json",
    "experiment_results": "reports/experiment_results.json",
}

# Portfolio tables exposed to the SQL tool (loaded into memory; no file access from SQL)
SQL_TABLES = {
    "scored_loans": "scored_loans.parquet",
    "stressed_book": "stressed_book.parquet",
    "policy_segments": "policy_segments.parquet",
    "policy_loans": "policy_loans.parquet",
}

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
JUDGE_MODEL = os.environ.get("ANTHROPIC_JUDGE_MODEL", "claude-haiku-5-5")
MAX_TOKENS = 2000
MAX_TOOL_ROUNDS = 8
CHUNK_WORDS = 350
CHUNK_OVERLAP = 60
SQL_ROW_LIMIT = 50
