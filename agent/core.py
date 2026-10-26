"""Claude tool-use loop that answers risk questions with citations.

Every factual sentence must cite the tool output it came from:
  [Q1], [Q2] ...           a portfolio SQL result
  [R:stress_results] ...   a module results file
  [ATLC-10K-2025#0123]     a filing passage
  [project/stress_report#scenarios]   a project report section
Citations are then checked against what the tools actually returned, so an
invented citation is caught deterministically.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from agent.config import MAX_TOKENS, MAX_TOOL_ROUNDS, MODEL
from agent.tools import TOOL_SCHEMAS, Toolbox

SYSTEM = """You are a credit risk analyst at a consumer lender. You answer questions about a
Lending Club loan portfolio and its models (default model, stress test, credit policy, experiment),
and you compare it with peer lenders' 10-K filings.

Scope of the data: 36-month Lending Club loans issued 2007-2015 that reached a final outcome
(no 60-month loans). The default model is trained on 2013-2014 loans and tested on the 2015 book.

Rules:
- Use the tools to find facts. Never state a number or fact that did not come from a tool result.
- Put a citation in square brackets right after every factual sentence, using the exact citation id
  returned by the tool: [Q1], [R:stress_results], [ATLC-10K-2025#0123], [project/model_report#performance].
- Cite the passage that actually contains each fact. If one sentence combines facts from two
  sources (for example a count and the period it covers), cite both.
- Do not describe the scope of a number beyond what its source says.
- Prefer get_results for headline numbers and query_portfolio for anything else about loans.
- If the tools do not contain the answer, say so plainly. Do not guess.
- Be concise and specific: numbers with units, and the period they refer to."""

EVAL_SUFFIX = """
End your reply with one final line in exactly this form:
FINAL: <the single number that answers the question, in the units of the source, or NOT_FOUND>"""

MEMO_SUFFIX = """
Write a risk memo in markdown with these sections: Summary (3 bullets), Portfolio risk, Stress test,
Credit policy, Peer context (from the 10-K filings), Recommendations. Cite every factual sentence."""

CITE_RE = re.compile(r"\[((?:Q\d+)|(?:R:[a-z_]+)|(?:[A-Za-z]+-10K-\d{4}#\d{4})|(?:project/[\w\-]+#[\w\-]+))\]")


@dataclass
class AgentResult:
    answer: str
    citations: list[str]
    invalid_citations: list[str]
    tool_calls: list[dict] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    sources: dict[str, str] = field(default_factory=dict)

    @property
    def final(self) -> str | None:
        m = re.search(r"FINAL:\s*(.+)\s*$", self.answer.strip())
        return m.group(1).strip() if m else None


def check_citations(text: str, issued: dict[str, str]) -> tuple[list[str], list[str]]:
    cited = list(dict.fromkeys(CITE_RE.findall(text)))
    return cited, [c for c in cited if c not in issued]


class Analyst:
    def __init__(self, toolbox: Toolbox, client=None, model: str = MODEL):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        self.client, self.toolbox, self.model = client, toolbox, model

    def ask(self, question: str, mode: str = "answer") -> AgentResult:
        system = SYSTEM + (EVAL_SUFFIX if mode == "eval" else MEMO_SUFFIX if mode == "memo" else "")
        messages = [{"role": "user", "content": question}]
        calls, tin, tout, t0 = [], 0, 0, time.time()
        self.toolbox.issued, self.toolbox.n_queries = {}, 0
        for _ in range(MAX_TOOL_ROUNDS + 1):
            resp = self.client.messages.create(model=self.model, max_tokens=MAX_TOKENS * (2 if mode == "memo" else 1),
                                               system=system, tools=TOOL_SCHEMAS, messages=messages)
            tin += getattr(resp.usage, "input_tokens", 0)
            tout += getattr(resp.usage, "output_tokens", 0)
            if resp.stop_reason != "tool_use":
                break
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    out = self.toolbox.run(block.name, dict(block.input))
                    calls.append({"tool": block.name, "input": dict(block.input)})
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
            messages.append({"role": "user", "content": results})
        text = "\n".join(b.text for b in resp.content if b.type == "text").strip()
        cited, invalid = check_citations(text, self.toolbox.issued)
        return AgentResult(text, cited, invalid, calls, tin, tout, time.time() - t0,
                           {c: self.toolbox.issued[c] for c in cited if c in self.toolbox.issued})
