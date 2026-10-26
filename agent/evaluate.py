"""Evaluate the AI risk analyst.

Question set (answer keys are computed from the project's own result files and
tables, so they stay correct when the models are rerun):
  numeric   headline numbers from the module results          -> exact-answer accuracy
  sql       facts that need a portfolio query                 -> exact-answer accuracy
  abstain   questions the data cannot answer                  -> must reply NOT_FOUND
  filings   cross-lender questions on peer 10-K filings         -> must cite 2+ lenders; faithfulness judged

Metrics: accuracy, abstention accuracy, citation validity (every cited id was really
returned by a tool), citation faithfulness (an LLM judge checks each cited passage
supports its sentence), tool calls, tokens, latency.

Usage:
    python -m agent.evaluate                 # full run (about 30 questions)
    python -m agent.evaluate --limit 5       # quick check
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from agent.config import JUDGE_MODEL, RESULTS_FILES
from agent.core import CITE_RE
from models.train import md_table
from pipeline import config


# --- question set ----------------------------------------------------------------
def _pick(rows, **match):
    return next(r for r in rows if all(r.get(k) == v for k, v in match.items()))


def build_questions(root: Path = config.ROOT, data_dir: Path = config.PROCESSED_DIR) -> list[dict]:
    R = {k: json.loads((root / v).read_text()) for k, v in RESULTS_FILES.items() if (root / v).exists()}
    q = []

    def num(question, value, tol=0.02):
        q.append({"category": "numeric", "question": question, "answer": float(value), "tol": tol})

    if "model_metrics" in R:
        perf = R["model_metrics"]["performance"]
        num("What is the GBM's out-of-time AUC?", _pick(perf, model="GBM", split="oot")["auc"])
        num("What out-of-time AUC does Lending Club's sub-grade benchmark reach?",
            _pick(perf, model="Sub-grade benchmark", split="oot")["auc"])
        num("What is the WOE scorecard's out-of-time KS statistic?", _pick(perf, model="WOE scorecard", split="oot")["ks"])
        num("What is the population stability index of the GBM between training and out-of-time?",
            R["model_metrics"]["psi"]["GBM"], tol=0.05)
    if "stress_results" in R:
        s = R["stress_results"]
        sc = s["scenarios"]
        num("What is the expected loss on the 2015 book under the severe scenario, in $ millions?",
            _pick(sc, scenario="Severe")["expected_loss_usd_m"])
        num("What is the expected loss rate under the adverse scenario?", _pick(sc, scenario="Adverse")["loss_rate"])
        num("By what factor does a 1-point rise in unemployment multiply default odds?",
            s["sensitivity"]["odds_multiplier_per_pp"])
        num("What was the ratio of expected to actual losses in the stress-test backtest?", s["backtest"]["ratio"])
        num("What is the average loss given default used in the stress test?", s["lgd_overall"])
    if "optimization_results" in R:
        pol = R["optimization_results"]["policies"]
        num("What realized profit did the optimized credit policy earn, in $ millions?",
            _pick(pol, policy="Optimized")["realized_profit_usd_m"])
        num("What realized profit would approving every 2015 loan have earned, in $ millions?",
            _pick(pol, policy="Approve all")["realized_profit_usd_m"])
        num("What share of the 2015 book (by principal) does the optimized policy fund?",
            _pick(pol, policy="Optimized")["volume_share"])
    if "experiment_results" in R:
        e = R["experiment_results"]
        num("In the champion/challenger experiment, what was the profit uplift per applicant in dollars?",
            e["readout"]["uplift"])
        num("How many applicants per arm did the experiment's power calculation require?", e["design"]["n_per_arm"])
        num("What was the default rate of loans funded by the challenger policy?", e["readout"]["default_rate_challenger"])

    book_path = data_dir / "stressed_book.parquet"
    if book_path.exists():
        b = pd.read_parquet(book_path)
        sql = [
            ("How many loans of grade C are in the 2015 book?", (b["grade"] == "C").sum()),
            ("What is the average predicted default probability (pd_gbm) of grade E loans in the 2015 book?",
             b.loc[b["grade"] == "E", "pd_gbm"].mean()),
            ("What is the realized default rate of grade B loans in the 2015 book?",
             b.loc[b["grade"] == "B", "is_default"].mean()),
            ("What is the total principal of the 2015 book in $ millions?", b["loan_amnt"].sum() / 1e6),
        ]
        q += [{"category": "sql", "question": t, "answer": float(v), "tol": 0.01} for t, v in sql]

    q += [{"category": "abstain", "question": t, "answer": None} for t in (
        "What was the default rate of 60-month loans in the portfolio?",
        "What AUC did the GBM reach on loans issued in 2017?",
        "How many loans did the portfolio originate in Canada?",
        "What will the US unemployment rate be in 2027?",
    )]
    # Cross-lender questions: a good answer draws on more than one company's 10-K
    q += [{"category": "filings", "question": t, "answer": None} for t in (
        "How do consumer lenders in the peer filings describe the effect of unemployment on credit losses?",
        "How do the peer lenders estimate their allowance for credit losses?",
        "What risks do the peer lenders describe about lending to near-prime or subprime borrowers?",
        "How do the peer lenders describe the risk that rising interest rates raise their funding costs?",
        "What regulatory risks do the peer consumer lenders highlight in their 10-Ks?",
    )]
    return q


# --- scoring ----------------------------------------------------------------------
def parse_number(s: str | None) -> float | None:
    if not s or "NOT_FOUND" in s.upper():
        return None
    m = re.search(r"-?\$?\s*-?[\d,]*\.?\d+(?:e-?\d+)?", s.replace("−", "-"), re.IGNORECASE)
    if not m:
        return None
    v = float(m.group(0).replace("$", "").replace(",", "").replace(" ", ""))
    tail = s[m.end():].strip().lower()
    for pattern, mult in ((r"(m|mm|mn|million)\b", 1e6), (r"(b|bn|billion)\b", 1e9), (r"(k|thousand)\b", 1e3)):
        if re.match(pattern, tail):
            return v * mult
    return v


def numeric_correct(got: float | None, want: float, tol: float) -> bool:
    if got is None:
        return False
    # Accept the same quantity in other common units: % vs fraction, USD vs $M
    for scale in (1, 100, 0.01, 1e6, 1e-6):
        target = want * scale
        if abs(got - target) <= max(tol * abs(target), 1e-9 if target else 1e-6):
            return True
    return False


def claims_with_citations(answer: str) -> list[tuple[str, str]]:
    """(claim, citation) pairs: one claim per sentence, with each markdown list item treated on its own."""
    pairs = []
    for line in answer.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line).replace("**", "").strip()
        if not line or line.upper().startswith("FINAL:"):
            continue
        for sent in re.split(r"(?<=[.!?\]])\s+(?=[A-Z0-9])", line):
            for cid in CITE_RE.findall(sent):
                claim = re.sub(r"\s+([.,;:])", r"\1", CITE_RE.sub("", sent)).strip()
                if claim:
                    pairs.append((claim, cid))
    return pairs


JUDGE_PROMPT = """For each numbered item, decide whether the SOURCE text supports the CLAIM.
Supported means the claim's facts and numbers can be read from the source (rounding is fine).
Do not explain. Reply with only one JSON object per item, in order, like:
{"i": 1, "supported": true}

"""
VERDICT_RE = re.compile(r'\{[^{}]*\}')
ITEM_RE = re.compile(r'"?i"?\s*:\s*"?(\d+)"?', re.IGNORECASE)
SUPPORTED_RE = re.compile(r'"?supported"?\s*:\s*"?(true|false|yes|no)"?', re.IGNORECASE)
SOURCE_CHARS = 15000   # results files are long; the cited number must be visible to the judge


def judge_faithfulness(client, pairs: list[tuple[str, str]], sources: dict[str, str], model: str = JUDGE_MODEL,
                       max_pairs: int = 12) -> list[dict]:
    """One verdict per (claim, citation) pair: {"claim", "citation", "supported"}."""
    pairs = [(c, cid) for c, cid in pairs if cid in sources][:max_pairs]
    if not pairs:
        return []
    body = "\n\n".join(f"{i}. CLAIM: {c}\nSOURCE: {sources[cid][:SOURCE_CHARS]}" for i, (c, cid) in enumerate(pairs, 1))
    resp = client.messages.create(model=model, max_tokens=2000, messages=[{"role": "user", "content": JUDGE_PROMPT + body}])
    text = "".join(b.text for b in resp.content if b.type == "text")
    found = {}
    for obj in VERDICT_RE.findall(text):          # any key order, quoted or not
        i, sup = ITEM_RE.search(obj), SUPPORTED_RE.search(obj)
        if i and sup:
            found[int(i.group(1))] = sup.group(1).lower() in ("true", "yes")
    if not found:
        # unparseable reply: counted as not judged (never as unsupported); keep it for debugging
        judge_faithfulness.last_unparsed = text[:2000]
        return []
    return [{"claim": c, "citation": cid, "supported": found[i]}
            for i, (c, cid) in enumerate(pairs, 1) if i in found]


def score(item: dict, res, client, judge: bool = True) -> dict:
    final = res.final
    row = {"category": item["category"], "question": item["question"], "final": final,
           "tool_calls": len(res.tool_calls), "citations": len(res.citations),
           "invalid_citations": len(res.invalid_citations), "input_tokens": res.input_tokens,
           "output_tokens": res.output_tokens, "seconds": round(res.seconds, 1)}
    if item["category"] in ("numeric", "sql"):
        row["correct"] = numeric_correct(parse_number(final), item["answer"], item["tol"])
        row["expected"] = item["answer"]
    elif item["category"] == "abstain":
        row["correct"] = final is not None and "NOT_FOUND" in final.upper()
    else:
        # cross-lender question: must cite 10-K passages from at least two different lenders
        lenders = {c.split("-10K-")[0] for c in res.citations if "-10K-" in c}
        row["correct"] = len(lenders) >= 2
        row["lenders_cited"] = len(lenders)
    if judge:
        verdicts = judge_faithfulness(client, claims_with_citations(res.answer), res.sources)
        row["judged_claims"] = len(verdicts)
        row["supported_claims"] = int(sum(v["supported"] for v in verdicts))
        row["unsupported"] = [v for v in verdicts if not v["supported"]]   # kept for inspection
        if not verdicts and getattr(judge_faithfulness, "last_unparsed", None):
            row["judge_raw"] = judge_faithfulness.last_unparsed
            judge_faithfulness.last_unparsed = None
        row["answer"] = res.answer
    return row


def summarize(rows: pd.DataFrame) -> pd.DataFrame:
    out = rows.groupby("category").agg(questions=("question", "size"), accuracy=("correct", "mean"),
                                       avg_tool_calls=("tool_calls", "mean"),
                                       answers_with_invalid_citation=("invalid_citations", lambda s: (s > 0).mean()))
    if "judged_claims" in rows:
        g = rows.groupby("category")[["supported_claims", "judged_claims"]].sum()
        out["faithfulness"] = g["supported_claims"] / g["judged_claims"].replace(0, float("nan"))
    order = ["numeric", "sql", "abstain", "filings"]
    return out.reindex([c for c in order if c in out.index]).reset_index()


def write_report(path: Path, rows: pd.DataFrame, summary: pd.DataFrame, model: str) -> None:
    total = rows["correct"].mean()
    inv = (rows["invalid_citations"] > 0).mean()
    faith = (rows["supported_claims"].sum() / rows["judged_claims"].sum()) if "judged_claims" in rows and \
        rows["judged_claims"].sum() else float("nan")
    lines = [
        "# AI risk analyst evaluation",
        "",
        f"The analyst ({model}) passed **{total:.0%}** of {len(rows)} test questions; "
        f"**{faith:.0%}** of its cited claims were supported by the cited passage (judged by {JUDGE_MODEL}), and "
        f"{inv:.0%} of answers contained a citation the tools never returned.",
        "",
        "| Category | What passes |",
        "| --- | --- |",
        "| numeric | Final number matches the module's results file (2% tolerance) |",
        "| sql | Final number matches a value computed directly from the portfolio table (1%) |",
        "| abstain | Says NOT_FOUND for a question the data cannot answer |",
        "| filings | Answers a cross-lender question citing 10-K passages from at least two lenders |",
        "",
        md_table(summary, {"accuracy": ".0%", "avg_tool_calls": ".1f", "answers_with_invalid_citation": ".0%",
                           "faithfulness": ".0%"}),
        "",
        f"Tokens: {rows['input_tokens'].sum():,} in, {rows['output_tokens'].sum():,} out · "
        f"median {rows['seconds'].median():.0f}s per question.",
        "",
        "## Claims the judge marked unsupported",
        "",
        *([f"- {v['claim'][:200]} [{v['citation']}]" for r in rows.get("unsupported", pd.Series(dtype=object)).dropna()
           for v in r] or ["None."]),
        "",
        "## Every question",
        "",
        md_table(rows[["category", "question", "final", "correct", "tool_calls", "citations", "invalid_citations"]]
                 .assign(correct=lambda d: d["correct"].map({True: "pass", False: "FAIL"}))),
        "",
    ]
    path.write_text("\n".join(lines))


def run(analyst, limit: int | None = None, judge: bool = True, reports: Path = config.REPORTS_DIR) -> pd.DataFrame:
    qs = build_questions()
    if limit:
        # round-robin across categories so a short run still covers each kind of question
        by_cat: dict[str, list] = {}
        for item in qs:
            by_cat.setdefault(item["category"], []).append(item)
        mixed = [grp[i] for i in range(max(map(len, by_cat.values()))) for grp in by_cat.values() if i < len(grp)]
        qs = mixed[:limit]
    rows = []
    for i, item in enumerate(qs, 1):
        res = analyst.ask(item["question"], mode="eval" if item["category"] != "filings" else "answer")
        row = score(item, res, analyst.client, judge)
        rows.append(row)
        print(f"[{i:2}/{len(qs)}] {'pass' if row['correct'] else 'FAIL'}  {item['category']:8} {item['question'][:70]}")
    df = pd.DataFrame(rows)
    summary = summarize(df)
    reports.mkdir(parents=True, exist_ok=True)
    write_report(reports / "agent_eval.md", df, summary, analyst.model)
    df.to_json(reports / "agent_eval.json", orient="records", indent=2)
    print(summary.to_string(index=False))
    print(f"Report: {reports / 'agent_eval.md'}")
    return df


def main() -> None:
    from agent.ask import load_env, make_analyst

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--limit", type=int)
    p.add_argument("--no-judge", action="store_true")
    a = p.parse_args()
    load_env()
    run(make_analyst(), a.limit, not a.no_judge)


if __name__ == "__main__":
    main()
