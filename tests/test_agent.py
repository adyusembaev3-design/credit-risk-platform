"""Tests for Module 8 (AI risk analyst). No API key needed: a scripted fake client
stands in for Claude, so the tool loop, citation checks and scoring are tested offline."""

import json
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from agent.core import Analyst, check_citations
from agent.evaluate import build_questions, claims_with_citations, judge_faithfulness, numeric_correct, parse_number
from agent.retrieval import BM25Index
from agent.text import chunk_filing, chunk_markdown, html_to_text
from agent.tools import Toolbox

FILING_HTML = """<html><head><style>.x{}</style></head><body>
<ix:header><ix:hidden>hidden xbrl facts 123</ix:hidden></ix:header>
<p>Item 1A. Risk Factors</p>
<p>Our customers are near-prime consumers. Rising unemployment increases charge-offs and delinquencies
on our credit card receivables.</p>
<p>Item 7. Management&#8217;s Discussion and Analysis</p>
<p>Net interest margin rose because of higher yields on receivables.</p>
<script>var tracking = 1;</script></body></html>"""


def make_index():
    text = html_to_text(FILING_HTML)
    chunks = chunk_filing(text, "ATLC-10K-2026", {"source": "filings", "ticker": "ATLC", "company": "Atlanticus"})
    chunks += chunk_markdown("# Stress test report\n\nIntro.\n\n## Scenarios\n\nSevere loss $474M.",
                             "project/stress_report", {"source": "project", "path": "reports/stress_report.md"})
    return BM25Index(chunks)


def test_html_and_chunking():
    text = html_to_text(FILING_HTML)
    assert "hidden xbrl" not in text and "tracking" not in text
    assert "Management’s Discussion" in text
    chunks = chunk_filing(text * 1, "X-10K-2026", {})
    assert chunks[0]["id"] == "X-10K-2026#0000"
    md = chunk_markdown("# T\n\nx\n\n## Scenarios\n\ny", "project/r", {})
    assert [c["id"] for c in md] == ["project/r#t", "project/r#scenarios"]


def test_text_after_hidden_div_is_kept():
    # Inline-XBRL filings wrap metadata in hidden divs; text after them must not be dropped
    raw = '<div style="display:none">meta</div><p>Item 1A. Risk Factors</p><p>Charge-offs may rise.</p>'
    assert "Charge-offs may rise." in html_to_text(raw)


def test_bm25_finds_relevant_passage():
    idx = make_index()
    hit = idx.search("unemployment charge-offs near-prime", k=1)[0]
    assert hit["ticker"] == "ATLC"
    assert idx.search("severe loss scenarios", source="project", k=1)[0]["id"] == "project/stress_report#scenarios"
    assert idx.search("unemployment", company="SYF") == []


class FakeClient:
    """Plays back scripted Claude responses and records what it was sent."""

    def __init__(self, script):
        self.script, self.sent = list(script), []
        self.messages = self

    def create(self, **kw):
        self.sent.append(kw)
        return self.script.pop(0)


def tool_use(id_, name, inp):
    return NS(stop_reason="tool_use", usage=NS(input_tokens=100, output_tokens=20),
              content=[NS(type="tool_use", id=id_, name=name, input=inp)])


def final(text):
    return NS(stop_reason="end_turn", usage=NS(input_tokens=150, output_tokens=60), content=[NS(type="text", text=text)])


def test_agent_loop_and_citation_check():
    idx = make_index()
    real_id = idx.search("unemployment charge-offs", k=1)[0]["id"]
    client = FakeClient([
        tool_use("t1", "search_documents", {"query": "unemployment charge-offs", "source": "filings"}),
        final(f"Atlanticus says rising unemployment increases charge-offs [{real_id}]. "
              "It also reports a 9% loss rate [ATLC-10K-2026#0999].\nFINAL: NOT_FOUND"),
    ])
    res = Analyst(Toolbox(idx, None), client=client).ask("What drives Atlanticus charge-offs?", mode="eval")
    assert res.citations == [real_id, "ATLC-10K-2026#0999"]
    assert res.invalid_citations == ["ATLC-10K-2026#0999"]          # never returned by a tool
    assert res.final == "NOT_FOUND"
    assert res.input_tokens == 250 and len(res.tool_calls) == 1
    tool_msg = client.sent[1]["messages"][-1]["content"][0]
    assert tool_msg["type"] == "tool_result" and tool_msg["tool_use_id"] == "t1"
    assert real_id in tool_msg["content"]


def test_results_tool_and_unknown_tool(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "stress_results.json").write_text(json.dumps({"lgd_overall": 0.8}))
    tb = Toolbox(make_index(), None, root=tmp_path)
    out = json.loads(tb.run("get_results", {"name": "stress_results"}))
    assert out["citation"] == "R:stress_results" and out["results"]["lgd_overall"] == 0.8
    assert "error" in json.loads(tb.run("query_portfolio", {"sql": "SELECT 1"}))

    class FakePortfolio:
        def query(self, sql):
            return {"columns": ["n"], "rows": [[77423]], "truncated": False}
    tb2 = Toolbox(make_index(), FakePortfolio(), root=tmp_path)
    tb2.run("query_portfolio", {"sql": "SELECT count(*) AS n FROM stressed_book WHERE grade = 'C'"})
    assert "grade = 'C'" in tb2.issued["Q1"] and "77423" in tb2.issued["Q1"]
    assert "error" in json.loads(tb.run("delete_everything", {}))
    cited, invalid = check_citations("Loss given default is 80% [R:stress_results] [Q7].", tb.issued)
    assert cited == ["R:stress_results", "Q7"] and invalid == ["Q7"]


def test_sql_sandbox(tmp_path):
    pytest.importorskip("duckdb")
    from agent.tools import Portfolio

    pd.DataFrame({"loan_id": ["1", "2", "3"], "grade": ["A", "C", "C"], "loan_amnt": [1000.0, 2000.0, 3000.0]}) \
        .to_parquet(tmp_path / "stressed_book.parquet")
    p = Portfolio(tmp_path)
    ok = p.query("SELECT grade, count(*) AS n FROM stressed_book GROUP BY grade ORDER BY grade")
    assert ok["rows"] == [["A", 1], ["C", 2]]
    for bad in ("DROP TABLE stressed_book", "SELECT 1; DROP TABLE stressed_book",
                "SELECT * FROM read_csv('/etc/passwd')", "COPY stressed_book TO 'out.csv'"):
        assert "error" in p.query(bad), bad
    with pytest.raises(Exception):                     # file access is off even if the guard were bypassed
        p.con.execute(f"SELECT * FROM '{tmp_path / 'stressed_book.parquet'}'")


def test_scoring_helpers():
    assert parse_number("$474.0M") == pytest.approx(474e6)
    assert parse_number("0.688") == pytest.approx(0.688)
    assert parse_number("12.1%") == pytest.approx(12.1)
    assert parse_number("NOT_FOUND") is None
    assert parse_number("24 months") == pytest.approx(24)
    assert numeric_correct(474e6, 474.0, 0.02)            # USD vs $M
    assert numeric_correct(12.1, 0.121, 0.02)             # percent vs fraction
    assert not numeric_correct(0.70, 0.688, 0.01)
    pairs = claims_with_citations("Loss is $474M [R:stress_results]. AUC is 0.688 [Q1].")
    assert [c for _, c in pairs] == ["R:stress_results", "Q1"]
    bullets = claims_with_citations("The GBM AUC by split:\n- **Train**: 0.745 [Q1]\n- **Validation**: 0.685 [Q1]\nFINAL: 0.688")
    assert bullets == [("Train: 0.745", "Q1"), ("Validation: 0.685", "Q1")]


def test_judge_parses_verdicts():
    reply = 'Checked [1] and [2]:\n```json\n{"i": 1, "supported": true}\n{"i": 2, "supported": false}\n```'
    client = FakeClient([final(reply)])
    v = judge_faithfulness(client, [("Loss is $474M", "a"), ("AUC is 0.9", "b"), ("x", "missing")],
                           {"a": "severe loss 474", "b": "auc 0.688"})
    assert [x["supported"] for x in v] == [True, False]
    assert judge_faithfulness(FakeClient([final("no verdicts here")]), [("c", "a")], {"a": "s"}) == []
    reordered = FakeClient([final('{"supported": "false", "i": "1"}')])
    assert judge_faithfulness(reordered, [("c", "a")], {"a": "s"})[0]["supported"] is False


def test_judge_sees_long_sources():
    client = FakeClient([final('{"i": 1, "supported": true}')])
    long_source = "x" * 5000 + " auc 0.688"
    judge_faithfulness(client, [("AUC is 0.688", "a")], {"a": long_source})
    assert "auc 0.688" in client.sent[0]["messages"][0]["content"]


def test_question_set_from_results(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "stress_results.json").write_text(json.dumps({
        "scenarios": [{"scenario": "Severe", "expected_loss_usd_m": 474.0, "loss_rate": 0.13},
                      {"scenario": "Adverse", "expected_loss_usd_m": 365.0, "loss_rate": 0.10}],
        "sensitivity": {"odds_multiplier_per_pp": 1.16}, "backtest": {"ratio": 0.95}, "lgd_overall": 0.8}))
    qs = build_questions(root=tmp_path, data_dir=tmp_path)
    cats = {q["category"] for q in qs}
    assert {"numeric", "abstain", "filings"} <= cats
    severe = next(q for q in qs if "severe scenario" in q["question"])
    assert severe["answer"] == 474.0
    filings = [q["question"] for q in qs if q["category"] == "filings"]
    assert all("Atlanticus" not in f and "Synchrony" not in f for f in filings)   # generic, not company-specific


def test_filings_question_needs_two_lenders():
    from agent.evaluate import score
    item = {"category": "filings", "question": "q", "answer": None}
    one = NS(final=None, tool_calls=[], citations=["ATLC-10K-2026#0001", "ATLC-10K-2026#0002"], invalid_citations=[],
             input_tokens=0, output_tokens=0, seconds=0, answer="", sources={})
    two = NS(**{**vars(one), "citations": ["ATLC-10K-2026#0001", "SYF-10K-2026#0010"]})
    assert not score(item, one, None, judge=False)["correct"]
    assert score(item, two, None, judge=False)["correct"]
