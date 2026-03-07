"""Tests for dial_memory.scorer."""

from dial.scorer import score_and_filter, score_entry, tokenize


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


def test_score_entry_full_match():
    entry = {"keywords": ["payment", "stripe"]}
    score = score_entry(entry, "Fix payment stripe integration")
    assert score == 1.0


def test_score_entry_partial_match():
    entry = {"keywords": ["payment", "stripe", "webhook"]}
    score = score_entry(entry, "Fix payment stripe integration")
    assert abs(score - 2 / 3) < 0.01


def test_score_entry_no_match():
    entry = {"keywords": ["database", "migration"]}
    score = score_entry(entry, "Fix payment stripe integration")
    assert score == 0.0


def test_score_entry_no_keywords():
    entry = {"keywords": []}
    assert score_entry(entry, "anything") == 0.0


def test_score_entry_missing_keywords():
    entry = {}
    assert score_entry(entry, "anything") == 0.0


def test_score_and_filter():
    entries = [
        {"content": "a", "keywords": ["payment", "stripe"]},
        {"content": "b", "keywords": ["database", "migration"]},
        {"content": "c", "keywords": ["payment"]},
    ]
    result = score_and_filter(entries, "Fix payment stripe", min_score=0.3)
    assert len(result) == 2
    assert result[0]["content"] == "a"  # full match first
    assert result[1]["content"] == "c"


def test_score_and_filter_none_above_threshold():
    entries = [{"content": "a", "keywords": ["unrelated"]}]
    result = score_and_filter(entries, "Fix payment", min_score=0.3)
    assert result == []
