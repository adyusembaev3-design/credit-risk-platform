"""BM25 keyword retrieval over chunks (no embedding API or GPU needed)."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

STOP = set("""a an and are as at be by for from has have in is it its of on or that the this to was were will
with which who what when where how does do did our we they their than then there these those not no""".split())


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower()) if t not in STOP and len(t) > 1]


class BM25Index:
    def __init__(self, chunks: list[dict], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.tf = [Counter(tokenize(c["section"] + " " + c["text"])) for c in chunks]
        self.len = [sum(t.values()) for t in self.tf]
        self.avg = sum(self.len) / max(1, len(self.len))
        df = Counter(term for t in self.tf for term in t)
        n = len(chunks)
        self.idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}
        self.by_id = {c["id"]: c for c in chunks}

    def search(self, query: str, k: int = 5, source: str = "all", company: str | None = None) -> list[dict]:
        q = tokenize(query)
        scored = []
        for i, c in enumerate(self.chunks):
            if source != "all" and c.get("source") != source:
                continue
            if company and c.get("ticker", "").upper() != company.upper():
                continue
            tf, s = self.tf[i], 0.0
            for term in q:
                f = tf.get(term)
                if f:
                    s += self.idf[term] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
            if s > 0:
                scored.append((s, i))
        scored.sort(reverse=True)
        return [{**self.chunks[i], "score": round(s, 3)} for s, i in scored[:k]]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.chunks))

    @classmethod
    def load(cls, path: Path) -> "BM25Index":
        return cls(json.loads(path.read_text()))
