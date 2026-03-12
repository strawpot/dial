"""RM keyword relevance scoring — BM25 + SimHash, no model, no dependencies."""

from __future__ import annotations

import math
import re

# Common English stop words to ignore during tokenization.
_STOP_WORDS = frozenset(
    "a an and are as at be by for from has have in is it of on or that the "
    "this to was were will with".split()
)

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens, stripping stop words.

    Returns a list (preserving duplicates) for BM25 term-frequency counting.
    Use set(tokenize(text)) when a token set is needed.
    """
    tokens = _TOKEN_RE.findall(text.lower())
    return [t for t in tokens if t not in _STOP_WORDS]


# -- BM25 ---------------------------------------------------------------------


class BM25:
    """Corpus-aware BM25 scorer (Okapi BM25, k1=1.5, b=0.75).

    Build once over a corpus of token lists, then call score() per document.
    """

    _K1 = 1.5
    _B = 0.75

    def __init__(self, corpus: list[list[str]]) -> None:
        n = len(corpus)
        self._avgdl = sum(len(doc) for doc in corpus) / n if n else 1.0

        # Document frequency: how many docs contain each term
        df: dict[str, int] = {}
        for doc in corpus:
            for term in set(doc):
                df[term] = df.get(term, 0) + 1

        # IDF: log((N - df + 0.5) / (df + 0.5) + 1) — always positive
        self._idf: dict[str, float] = {
            term: math.log((n - freq + 0.5) / (freq + 0.5) + 1)
            for term, freq in df.items()
        }

    def score(self, query_tokens: list[str], doc_tokens: list[str]) -> float:
        """BM25 score of doc_tokens against query_tokens."""
        dl = len(doc_tokens)
        tf_map: dict[str, int] = {}
        for t in doc_tokens:
            tf_map[t] = tf_map.get(t, 0) + 1

        s = 0.0
        for term in query_tokens:
            tf = tf_map.get(term, 0)
            idf = self._idf.get(term, 0.0)
            denom = tf + self._K1 * (1 - self._B + self._B * dl / self._avgdl)
            s += idf * (tf * (self._K1 + 1)) / denom
        return s


# -- SimHash ------------------------------------------------------------------


def _fnv1a_64(token: str) -> int:
    """Deterministic 64-bit FNV-1a hash of a token."""
    h = 14695981039346656037
    for byte in token.encode():
        h ^= byte
        h = (h * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return h


def simhash(text: str, bits: int = 64) -> int:
    """Compute a SimHash fingerprint for text.

    Tokens are hashed with FNV-1a; bit positions are accumulated (+1/-1)
    and the sign of each position forms the final fingerprint.
    """
    v = [0] * bits
    for token in tokenize(text):
        h = _fnv1a_64(token)
        for i in range(bits):
            v[i] += 1 if (h >> i) & 1 else -1
    result = 0
    for i in range(bits):
        if v[i] > 0:
            result |= 1 << i
    return result


def hamming(a: int, b: int) -> int:
    """Number of differing bits between two integers."""
    return bin(a ^ b).count("1")


# -- RM scoring ---------------------------------------------------------------


def score_and_filter(
    entries: list[dict],
    task_text: str,
    min_score: float = 0.3,
) -> list[tuple[float, dict]]:
    """Score keyword entries against task_text using BM25 and filter by min_score.

    Builds a BM25 corpus from all entry keywords, then scores each entry.
    Returns (score, entry) pairs sorted descending, above min_score.
    """
    if not entries:
        return []

    # Build corpus: each entry's keywords as a token list
    corpora: list[list[str]] = [
        tokenize(" ".join(e.get("keywords", []))) for e in entries
    ]

    bm25 = BM25(corpora)
    query_tokens = tokenize(task_text)

    raw: list[tuple[float, dict]] = []
    for entry, doc_tokens in zip(entries, corpora):
        if not doc_tokens:
            continue
        s = bm25.score(query_tokens, doc_tokens)
        raw.append((s, entry))

    if not raw:
        return []

    # Normalise to [0, 1] so min_score is comparable to the old Jaccard scale
    max_s = max(s for s, _ in raw)
    scored = [
        (s / max_s if max_s > 0 else 0.0, e)
        for s, e in raw
        if (s / max_s if max_s > 0 else 0.0) >= min_score
    ]

    scored.sort(key=lambda t: t[0], reverse=True)
    return scored


# -- Backward-compat helpers --------------------------------------------------


def score_entry(entry: dict, task_text: str) -> float:
    """Score a single knowledge entry against task text.

    Uses single-document BM25 (degrades gracefully without corpus context).
    Kept for call sites that need a standalone score.
    """
    result = score_and_filter([entry], task_text, min_score=0.0)
    return result[0][0] if result else 0.0
