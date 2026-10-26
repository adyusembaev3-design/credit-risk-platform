"""Turn filings and reports into citable chunks."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from agent.config import CHUNK_OVERLAP, CHUNK_WORDS

BLOCK_TAGS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"}
ITEM_RE = re.compile(r"^\s*item\s+(\d{1,2}[a-c]?)\.?\s*(.{0,80})$", re.IGNORECASE)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    # Inline XBRL headers hold thousands of hidden facts; drop them before parsing
    raw = re.sub(r"<ix:header>.*?</ix:header>", " ", raw, flags=re.S | re.I)
    p = _TextExtractor()
    p.feed(raw)
    text = html.unescape("".join(p.parts)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def chunk_filing(text: str, doc_id: str, meta: dict) -> list[dict]:
    """Word windows that remember the 10-K Item (e.g. 'Item 1A Risk Factors') they fall in."""
    words_with_item: list[tuple[str, str]] = []
    item = "Cover"
    for line in text.splitlines():
        m = ITEM_RE.match(line)
        if m and len(line) < 100:
            item = f"Item {m.group(1).upper()} {m.group(2).strip(' .')}".strip()
        for w in line.split():
            words_with_item.append((w, item))
    chunks, step, i, k = [], CHUNK_WORDS - CHUNK_OVERLAP, 0, 0
    while i < len(words_with_item):
        window = words_with_item[i:i + CHUNK_WORDS]
        chunks.append({"id": f"{doc_id}#{k:04d}", "doc": doc_id, "section": window[0][1],
                       "text": " ".join(w for w, _ in window), **meta})
        i, k = i + step, k + 1
    return chunks


def chunk_markdown(text: str, doc_id: str, meta: dict) -> list[dict]:
    """One chunk per '## ' section (long sections are split into word windows)."""
    sections = re.split(r"(?m)^(?=#{1,2} )", text)
    chunks = []
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        title = sec.splitlines()[0].lstrip("# ").strip()
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "section"
        words = sec.split()
        if len(words) <= CHUNK_WORDS * 2:
            chunks.append({"id": f"{doc_id}#{slug}", "doc": doc_id, "section": title, "text": sec, **meta})
        else:
            step = CHUNK_WORDS - CHUNK_OVERLAP
            for j, start in enumerate(range(0, len(words), step)):
                chunks.append({"id": f"{doc_id}#{slug}-{j}", "doc": doc_id, "section": title,
                               "text": " ".join(words[start:start + CHUNK_WORDS]), **meta})
    return chunks
