"""
Keyword (BM25) index over the statute library -- the lexical half of
hybrid retrieval (Phase 5).

Why: with ~2,200 sections, embedding search alone drifts on legal terms
of art. Measured: "non-compete restraint of trade" didn't surface Indian
Contract Act s.27 ("Agreement in restraint of trade, void"), and
"penalty liquidated damages" missed s.74. Exact phrase overlap is what
BM25 is good at; retrieval.py fuses both rankings (reciprocal rank
fusion), so each covers the other's blind spots.

Pure Python, built in memory from data/statutes/*.json on first use
(~1 s for the current library); ids match the vector store's.
"""

import math
import re
import threading
from collections import Counter

from backend.rag.chunking import chunk_statute

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = set(
    "a an and are as at be by for from has have in is it its of on or shall such that the this to was were will with "
    "any all may not no other under said which who whom whose than then there these those be been being into".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


class BM25Index:
    _instance = None
    _lock = threading.Lock()
    K1, B = 1.4, 0.75
    TITLE_BOOST = 3   # section titles are short and precise: count their words 3x

    def __init__(self, chunks: list[dict]):
        self.ids = [c["id"] for c in chunks]
        docs = [tokenize(c.get("title", "")) * self.TITLE_BOOST + tokenize(c["text"]) for c in chunks]
        self.tf = [Counter(d) for d in docs]
        self.len = [len(d) for d in docs]
        self.avg_len = sum(self.len) / max(len(docs), 1)
        df = Counter(t for d in docs for t in set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    @classmethod
    def get(cls) -> "BM25Index":
        with cls._lock:
            if cls._instance is None:
                from backend.rag.ingest_laws import load_statute_files

                chunks = [c for s in load_statute_files() for c in chunk_statute(s["law"], s["sections"])]
                cls._instance = cls(chunks)
            return cls._instance

    def search(self, query: str, top_k: int = 20) -> list[tuple[str, float]]:
        terms = [t for t in tokenize(query) if t in self.idf]
        if not terms:
            return []
        scores = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            for t in terms:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.K1 + 1) / (f + self.K1 * (1 - self.B + self.B * self.len[i] / self.avg_len))
            if s > 0:
                scores.append((self.ids[i], s))
        scores.sort(key=lambda x: -x[1])
        return scores[:top_k]
