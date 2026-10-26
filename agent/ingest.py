"""Download the latest 10-K for each lender from SEC EDGAR and build the search index.

SEC asks every client to identify itself with a name and email in the User-Agent.

Usage:
    python -m agent.ingest --email you@school.edu
    python -m agent.ingest --skip-download          # re-index files already downloaded
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from agent.config import FILINGS_DIR, INDEX_PATH, PROJECT_DOCS, TICKERS
from agent.retrieval import BM25Index
from agent.text import chunk_filing, chunk_markdown, html_to_text
from pipeline import config

TICKER_MAP = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
# Fallback SEC IDs (CIKs) for lenders whose ticker is missing from SEC's ticker list
KNOWN_CIKS = {"LC": 1409970, "ATLC": 1464343, "SYF": 1601712, "COF": 927628}


def _get(session, url: str):
    time.sleep(0.15)  # stay well under SEC's 10 requests/second limit
    r = session.get(url, timeout=60)
    r.raise_for_status()
    return r


def download_10k(tickers, email: str, out_dir: Path = FILINGS_DIR) -> list[dict]:
    import requests

    s = requests.Session()
    s.headers.update({"User-Agent": f"credit-risk-platform research {email}", "Accept-Encoding": "gzip, deflate"})
    ciks = {v["ticker"].upper(): int(v["cik_str"]) for v in _get(s, TICKER_MAP).json().values()}
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = []
    for t in tickers:
        cik = ciks.get(t.upper()) or KNOWN_CIKS.get(t.upper())
        if cik is None:
            print(f"  {t.upper():5} not found at SEC, skipped")
            continue
        sub = _get(s, SUBMISSIONS.format(cik=cik)).json()
        recent = sub["filings"]["recent"]
        i = next(j for j, form in enumerate(recent["form"]) if form == "10-K")
        acc, doc, date = recent["accessionNumber"][i], recent["primaryDocument"][i], recent["filingDate"][i]
        url = ARCHIVE.format(cik=cik, acc=acc.replace("-", ""), doc=doc)
        raw = _get(s, url).text
        path = out_dir / f"{t.upper()}_10-K_{date}.htm"
        path.write_text(raw)
        m = {"ticker": t.upper(), "company": sub.get("name", t), "form": "10-K", "filed": date, "url": url,
             "file": path.name}
        meta.append(m)
        print(f"  {t.upper():5} {sub.get('name', '')[:40]:40} 10-K filed {date}  ({len(raw) / 1e6:.1f} MB)")
    (out_dir / "filings.json").write_text(json.dumps(meta, indent=2))
    return meta


def build_index(root: Path = config.ROOT, filings_dir: Path = FILINGS_DIR, out: Path = INDEX_PATH) -> BM25Index:
    chunks = []
    for rel in PROJECT_DOCS:
        p = root / rel
        if p.exists():
            doc_id = "project/" + p.stem
            chunks += chunk_markdown(p.read_text(), doc_id, {"source": "project", "path": rel})
    meta_path = filings_dir / "filings.json"
    if meta_path.exists():
        for m in json.loads(meta_path.read_text()):
            text = html_to_text((filings_dir / m["file"]).read_text(errors="ignore"))
            doc_id = f"{m['ticker']}-10K-{m['filed'][:4]}"
            chunks += chunk_filing(text, doc_id, {"source": "filings", "ticker": m["ticker"],
                                                  "company": m["company"], "filed": m["filed"], "url": m["url"]})
    index = BM25Index(chunks)
    index.save(out)
    n_proj = sum(c["source"] == "project" for c in chunks)
    print(f"Indexed {len(chunks):,} chunks ({n_proj} from project reports, {len(chunks) - n_proj:,} from filings) -> {out}")
    return index


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--email", help="Your email, sent to SEC in the User-Agent header (required to download)")
    p.add_argument("--tickers", nargs="+", default=list(TICKERS))
    p.add_argument("--skip-download", action="store_true")
    a = p.parse_args()
    if not a.skip_download:
        if not a.email:
            raise SystemExit("SEC requires contact details: pass --email you@school.edu")
        download_10k(a.tickers, a.email)
    build_index()


if __name__ == "__main__":
    main()
