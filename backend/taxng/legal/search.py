"""Keyword search (BM25) over provisions and guides.

Annex A ADR-04 specifies hybrid keyword plus vector retrieval in PostgreSQL.
The demo implements the keyword half in memory, behind the same interface, so
a pgvector-backed index can replace it without touching callers.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for", "from", "how",
    "i", "if", "in", "is", "it", "much", "my", "of", "on", "or", "pay", "the", "to",
    "under", "what", "when", "which", "who", "will", "with", "you", "your", "tax",
}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


@dataclass(frozen=True)
class Document:
    id: str
    kind: str  # "provision" | "guide"
    title: str
    text: str


@dataclass(frozen=True)
class Hit:
    document: Document
    score: float


class SearchIndex:
    def __init__(self, documents: list[Document], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.documents = documents
        self.k1, self.b = k1, b
        self._tf = [Counter(tokenize(d.title + " " + d.text)) for d in documents]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg = sum(self._len) / len(self._len) if documents else 0.0
        df: Counter[str] = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(documents)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, *, limit: int = 5, kinds: set[str] | None = None) -> list[Hit]:
        terms = tokenize(query)
        hits: list[Hit] = []
        for i, doc in enumerate(self.documents):
            if kinds and doc.kind not in kinds:
                continue
            tf, length = self._tf[i], self._len[i]
            score = 0.0
            for term in terms:
                f = tf.get(term)
                if not f:
                    continue
                norm = f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / self._avg))
                score += self._idf[term] * norm
            if score > 0:
                hits.append(Hit(doc, score))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]
