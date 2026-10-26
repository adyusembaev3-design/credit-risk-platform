"""Ask the AI risk analyst a question, or have it write a cited risk memo.

Needs ANTHROPIC_API_KEY (in the environment or a .env file at the repo root).

Usage:
    python -m agent.ask "How much would the 2015 book lose in a severe recession?"
    python -m agent.ask --memo "Q4 risk review of the 2015 book and peers"
"""

from __future__ import annotations

import argparse
import re

from agent.config import INDEX_PATH, MEMO_DIR
from agent.core import Analyst
from agent.retrieval import BM25Index
from agent.tools import Portfolio, Toolbox
from pipeline import config


def load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(config.ROOT / ".env")
    except ImportError:
        pass


def make_analyst(client=None) -> Analyst:
    if not INDEX_PATH.exists():
        raise SystemExit("No search index yet. Run: python -m agent.ingest --email you@school.edu")
    return Analyst(Toolbox(BM25Index.load(INDEX_PATH), Portfolio()), client=client)


def sources_footer(res) -> str:
    lines = ["", "---", "Sources"]
    for cid, text in res.sources.items():
        lines.append(f"- [{cid}] {text[:160].replace(chr(10), ' ')}...")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("question")
    p.add_argument("--memo", action="store_true", help="Write a full cited risk memo to reports/memos/")
    a = p.parse_args()
    load_env()
    res = make_analyst().ask(a.question, mode="memo" if a.memo else "answer")
    print(res.answer)
    print(sources_footer(res))
    flag = f"  ⚠ invalid citations: {', '.join(res.invalid_citations)}" if res.invalid_citations else ""
    print(f"\n{len(res.tool_calls)} tool calls · {res.input_tokens:,} in / {res.output_tokens:,} out tokens · "
          f"{res.seconds:.0f}s{flag}")
    if a.memo:
        MEMO_DIR.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", a.question.lower()).strip("-")[:50]
        out = MEMO_DIR / f"{slug}.md"
        out.write_text(f"# {a.question}\n\n{res.answer}\n{sources_footer(res)}\n")
        print(f"Memo: {out}")


if __name__ == "__main__":
    main()
