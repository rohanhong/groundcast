"""BM25 retrieval over chunks (spec section 5: no vector index in v1)."""

from __future__ import annotations

import math
import re
from collections import Counter

from groundcast.models import Chunk

_TOKEN = re.compile(r"[a-z0-9]+")

# Function words that carry no topical signal.
_STOPWORDS = frozenset(
    """a an and are as at be been but by can do does for from had has have he her his how i if in into is it its
    me my no not of on or our she so than that the their them then there these they this those to was we were what
    when where which who why will with you your""".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]


class BM25Index:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self._tf = [Counter(tokenize(c.text)) for c in chunks]
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg_len = (sum(self._len) / len(self._len)) if self._len else 0.0
        df: Counter[str] = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(chunks)
        self._idf = {term: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()}

    def scores(self, query: str) -> list[float]:
        terms = tokenize(query)
        out = []
        for tf, length in zip(self._tf, self._len):
            score = 0.0
            norm = self.k1 * (1 - self.b + self.b * length / self._avg_len) if self._avg_len else self.k1
            for term in terms:
                freq = tf.get(term)
                if freq:
                    score += self._idf[term] * freq * (self.k1 + 1) / (freq + norm)
            out.append(score)
        return out

    def top_k(self, query: str, k: int, exclude: set[str] | frozenset[str] = frozenset()) -> list[Chunk]:
        ranked = sorted(zip(self.scores(query), range(len(self.chunks))), key=lambda p: (-p[0], p[1]))
        out = []
        for score, i in ranked:
            if len(out) >= k or score <= 0:
                break
            if self.chunks[i].id not in exclude:
                out.append(self.chunks[i])
        return out
