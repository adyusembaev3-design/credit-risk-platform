"""The three tools the analyst can call, plus their JSON schemas for the Claude API.

  query_portfolio   read-only SQL over the portfolio tables (DuckDB, in memory, no file access)
  search_documents  BM25 search over project reports and SEC 10-K filings
  get_results       exact numbers from the modules' results files
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from agent.config import RESULTS_FILES, SQL_ROW_LIMIT, SQL_TABLES
from agent.retrieval import BM25Index
from pipeline import config

FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|create|alter|attach|detach|copy|export|import|install|load|"
                       r"pragma|set|call|checkpoint|vacuum)\b|read_\w+\s*\(|glob\s*\(|['\"]/", re.IGNORECASE)

TOOL_SCHEMAS = [
    {
        "name": "query_portfolio",
        "description": (
            "Run one read-only SQL SELECT (DuckDB dialect) over the loan portfolio. Tables: "
            "scored_loans (every 2013-2015 loan: loan_id, issue_date, split ['train','valid','oot'], is_default, "
            "grade, sub_grade, int_rate, loan_amnt, pd_gbm, pd_scorecard, scorecard_points, reason_1..reason_3); "
            "stressed_book (2015 book: loan_id, grade, loan_amnt, is_default, pd_gbm, lgd, pd_baseline, pd_adverse, "
            "pd_severe, pd_realized, el_baseline, el_adverse, el_severe, el_realized in USD); "
            "policy_segments (grade, risk_band 1-10, loans, exposure, profit, severe_loss, realized, approve); "
            "policy_loans (loan_id, grade, risk_band, approve, loan_amnt, is_default, profit_baseline, profit_realized). "
            f"Returns at most {SQL_ROW_LIMIT} rows; aggregate in SQL."),
        "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]},
    },
    {
        "name": "search_documents",
        "description": (
            "Keyword search over (a) this project's model, stress, policy and experiment reports and data "
            "dictionary (source='project') and (b) the latest 10-K filings of Atlanticus (ATLC), Synchrony (SYF), "
            "Capital One (COF) and LendingClub (LC) (source='filings'). Returns passages with citation ids."),
        "input_schema": {"type": "object", "properties": {
            "query": {"type": "string"},
            "source": {"type": "string", "enum": ["all", "project", "filings"]},
            "company": {"type": "string", "description": "Optional ticker filter for filings, e.g. ATLC"},
            "k": {"type": "integer", "minimum": 1, "maximum": 8}},
            "required": ["query"]},
    },
    {
        "name": "get_results",
        "description": "Exact results of a module as JSON. names: " + ", ".join(RESULTS_FILES) + ".",
        "input_schema": {"type": "object", "properties": {"name": {"type": "string", "enum": list(RESULTS_FILES)}},
                         "required": ["name"]},
    },
]


class Portfolio:
    def __init__(self, data_dir: Path = config.PROCESSED_DIR):
        import duckdb

        # File access is disabled from the start; tables are loaded from pandas, not from SQL
        self.con = duckdb.connect(":memory:", config={"enable_external_access": False})
        self.tables = []
        for name, file in SQL_TABLES.items():
            p = data_dir / file
            if p.exists():
                df = pd.read_parquet(p)
                self.con.register(f"_{name}_df", df)
                self.con.execute(f"CREATE TABLE {name} AS SELECT * FROM _{name}_df")
                self.con.unregister(f"_{name}_df")
                self.tables.append(name)
        self.con.execute("SET lock_configuration = true")   # SQL cannot turn file access back on

    def query(self, sql: str) -> dict:
        sql = sql.strip().rstrip(";")
        if ";" in sql or not re.match(r"(?is)^\s*(select|with)\b", sql) or FORBIDDEN.search(sql):
            return {"error": "Only a single read-only SELECT statement is allowed."}
        try:
            df = self.con.execute(f"SELECT * FROM ({sql}) LIMIT {SQL_ROW_LIMIT + 1}").df()
        except Exception as e:  # noqa: BLE001 - errors go back to the model so it can fix its SQL
            return {"error": str(e).splitlines()[0][:300]}
        truncated = len(df) > SQL_ROW_LIMIT
        df = df.head(SQL_ROW_LIMIT)
        return {"columns": list(df.columns), "rows": json.loads(df.to_json(orient="values", date_format="iso")),
                "truncated": truncated}


class Toolbox:
    """Executes tool calls and remembers every citation id handed to the model."""

    def __init__(self, index: BM25Index, portfolio: Portfolio | None, root: Path = config.ROOT):
        self.index, self.portfolio, self.root = index, portfolio, root
        self.issued: dict[str, str] = {}      # citation id -> text the model was shown
        self.n_queries = 0

    def run(self, name: str, args: dict) -> str:
        if name == "query_portfolio":
            if self.portfolio is None:
                return json.dumps({"error": "Portfolio tables are not available."})
            self.n_queries += 1
            cid = f"Q{self.n_queries}"
            sql = args.get("sql", "")
            res = self.portfolio.query(sql)
            if "error" not in res:
                # the query is part of the evidence: "77,423" only means something next to its WHERE clause
                self.issued[cid] = f"SQL: {sql}\nRESULT: {json.dumps(res)[:4000]}"
            return json.dumps({"citation": cid, **res})
        if name == "search_documents":
            hits = self.index.search(args["query"], k=int(args.get("k", 5)), source=args.get("source", "all"),
                                     company=args.get("company"))
            out = []
            for h in hits:
                self.issued[h["id"]] = h["text"]
                label = h.get("company", h.get("path", ""))
                out.append({"citation": h["id"], "source": h["source"], "document": label,
                            "section": h["section"], "filed": h.get("filed"), "text": h["text"]})
            return json.dumps({"results": out} if out else {"results": [], "note": "No matching passages."})
        if name == "get_results":
            key = args.get("name")
            p = self.root / RESULTS_FILES.get(key, "")
            if key not in RESULTS_FILES or not p.exists():
                return json.dumps({"error": f"No results named {key!r}."})
            text = p.read_text()
            cid = f"R:{key}"
            self.issued[cid] = text
            return json.dumps({"citation": cid, "results": json.loads(text)})
        return json.dumps({"error": f"Unknown tool {name!r}."})
