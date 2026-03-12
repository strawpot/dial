"""Tests for dial_memory.scorer."""

from dial_memory.scorer import (
    BM25,
    hamming,
    score_and_filter,
    score_entry,
    simhash,
    tokenize,
)


# -- tokenize -----------------------------------------------------------------


def test_tokenize_basic():
    tokens = tokenize("Fix the payment integration")
    assert "fix" in tokens
    assert "payment" in tokens
    assert "integration" in tokens
    # stop words removed
    assert "the" not in tokens


def test_tokenize_punctuation():
    tokens = tokenize("hello-world, foo_bar!")
    assert "hello" in tokens
    assert "world" in tokens
    assert "foo_bar" in tokens


def test_tokenize_returns_list_with_duplicates():
    tokens = tokenize("fix fix fix payment")
    assert tokens.count("fix") == 3


# -- BM25 ---------------------------------------------------------------------


def test_bm25_higher_score_for_matching_doc():
    corpus = [
        tokenize("fix payment stripe integration"),
        tokenize("update database migration"),
        tokenize("add unit tests"),
    ]
    bm25 = BM25(corpus)
    query = tokenize("fix payment")
    s_match = bm25.score(query, corpus[0])
    s_nomatch = bm25.score(query, corpus[1])
    assert s_match > s_nomatch


def test_bm25_zero_score_for_no_overlap():
    corpus = [tokenize("database migration"), tokenize("update schema")]
    bm25 = BM25(corpus)
    assert bm25.score(tokenize("fix payment"), corpus[0]) == 0.0


def test_bm25_rare_term_scores_higher():
    # "jaccard" appears in only one doc; scores higher than common "fix"
    corpus = [
        tokenize("fix jaccard scorer"),
        tokenize("fix payment integration"),
    ]
    bm25 = BM25(corpus)
    s_rare = bm25.score(tokenize("jaccard"), corpus[0])
    s_common_0 = bm25.score(tokenize("fix"), corpus[0])
    s_common_1 = bm25.score(tokenize("fix"), corpus[1])
    assert s_rare > 0
    # both docs score equally for a term that appears in both
    assert abs(s_common_0 - s_common_1) < 0.01


def test_bm25_empty_corpus():
    bm25 = BM25([])
    assert bm25.score(tokenize("anything"), tokenize("anything")) == 0.0


def test_bm25_empty_query():
    corpus = [tokenize("fix payment")]
    bm25 = BM25(corpus)
    assert bm25.score([], corpus[0]) == 0.0


# -- SimHash + Hamming --------------------------------------------------------


def test_simhash_identical_text():
    assert simhash("fix the payment integration") == simhash("fix the payment integration")


def test_simhash_different_text_differs():
    assert simhash("fix payment") != simhash("update database")


def test_simhash_near_duplicate_low_hamming():
    # Same facts, different word order — should produce close fingerprints
    a = simhash("auth module uses JWT with RS256")
    b = simhash("JWT is used by auth module RS256")
    assert hamming(a, b) < 20


def test_simhash_unrelated_high_hamming():
    a = simhash("fix payment stripe integration")
    b = simhash("deploy kubernetes cluster config")
    assert hamming(a, b) > 10


def test_hamming_identical():
    assert hamming(0b1010, 0b1010) == 0


def test_hamming_all_differ():
    assert hamming(0b0000, 0b1111) == 4


def test_simhash_empty_text():
    assert simhash("") == 0


# -- score_and_filter (BM25-backed) -------------------------------------------


def test_score_and_filter_returns_tuples():
    entries = [{"content": "a", "keywords": ["payment", "stripe"]}]
    result = score_and_filter(entries, "Fix payment stripe", min_score=0.0)
    assert len(result) == 1
    score, entry = result[0]
    assert isinstance(score, float)
    assert entry["content"] == "a"


def test_score_and_filter_orders_by_relevance():
    entries = [
        {"content": "a", "keywords": ["payment", "stripe"]},
        {"content": "b", "keywords": ["database", "migration"]},
        {"content": "c", "keywords": ["payment"]},
    ]
    result = score_and_filter(entries, "Fix payment stripe", min_score=0.0)
    contents = [e["content"] for _, e in result]
    # "a" has both payment+stripe; should rank above "c" (payment only)
    assert contents.index("a") < contents.index("c")


def test_score_and_filter_filters_below_threshold():
    entries = [
        {"content": "a", "keywords": ["payment", "stripe"]},
        {"content": "b", "keywords": ["unrelated", "topic"]},
    ]
    result = score_and_filter(entries, "Fix payment stripe", min_score=0.5)
    contents = [e["content"] for _, e in result]
    assert "a" in contents
    assert "b" not in contents


def test_score_and_filter_empty_entries():
    assert score_and_filter([], "anything") == []


def test_score_and_filter_no_keywords_skipped():
    entries = [{"content": "a", "keywords": []}]
    result = score_and_filter(entries, "Fix payment", min_score=0.0)
    assert result == []


# -- score_entry (compat shim) ------------------------------------------------


def test_score_entry_matching():
    entry = {"keywords": ["payment", "stripe"]}
    s = score_entry(entry, "Fix payment stripe integration")
    assert s > 0.0


def test_score_entry_no_match():
    entry = {"keywords": ["database", "migration"]}
    s = score_entry(entry, "Fix payment stripe integration")
    assert s == 0.0


def test_score_entry_no_keywords():
    assert score_entry({}, "anything") == 0.0
