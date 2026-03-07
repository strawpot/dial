"""RM keyword relevance scoring — simple keyword overlap, no embeddings."""

from __future__ import annotations

import re

# Common English stop words to ignore during tokenization.
_STOP_WORDS = frozenset(
    "a an and are as at be by for from has have in is it of on or that the "
    "this to was were will with".split()
)

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def tokenize(text: str) -> set[str]:
    """Split text into lowercase tokens, stripping stop words."""
    tokens = set(_TOKEN_RE.findall(text.lower()))
    return tokens - _STOP_WORDS


def score_entry(entry: dict, task_text: str) -> float:
    """Score a knowledge entry against task text using keyword overlap.

    Returns a float between 0.0 and 1.0.  Higher means more relevant.
    """
    entry_keywords = entry.get("keywords", [])
    if not entry_keywords:
        return 0.0

    task_tokens = tokenize(task_text)
    kw_set = {kw.lower() for kw in entry_keywords}
    overlap = task_tokens & kw_set
    return len(overlap) / len(kw_set)


def score_and_filter(
    entries: list[dict], task_text: str, min_score: float = 0.3
) -> list[dict]:
    """Score entries and return those above *min_score*, sorted descending."""
    scored = []
    for entry in entries:
        s = score_entry(entry, task_text)
        if s >= min_score:
            scored.append((s, entry))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [entry for _, entry in scored]
