"""Tests for dial_memory.storage."""

from dial_memory.storage import (
    append_jsonl,
    em_path,
    expand_path,
    knowledge_path,
    read_jsonl,
    read_jsonl_tail,
    role_knowledge_path,
)


def test_append_and_read_jsonl(tmp_path):
    path = tmp_path / "data.jsonl"
    append_jsonl(path, {"a": 1})
    append_jsonl(path, {"b": 2})
    records = read_jsonl(path)
    assert records == [{"a": 1}, {"b": 2}]


def test_read_jsonl_missing_file(tmp_path):
    assert read_jsonl(tmp_path / "nope.jsonl") == []


def test_read_jsonl_tail(tmp_path):
    path = tmp_path / "data.jsonl"
    for i in range(10):
        append_jsonl(path, {"i": i})
    tail = read_jsonl_tail(path, 3)
    assert tail == [{"i": 7}, {"i": 8}, {"i": 9}]


def test_read_jsonl_tail_missing_file(tmp_path):
    assert read_jsonl_tail(tmp_path / "nope.jsonl", 5) == []


def test_append_creates_parent_dirs(tmp_path):
    path = tmp_path / "a" / "b" / "c.jsonl"
    append_jsonl(path, {"x": 1})
    assert read_jsonl(path) == [{"x": 1}]


def test_expand_path_tilde():
    p = expand_path("~/foo")
    assert "~" not in str(p)
    assert str(p).endswith("/foo")


def test_em_path(tmp_path):
    p = em_path(tmp_path, "session123")
    assert p == tmp_path / "em" / "session123.jsonl"


def test_knowledge_path(tmp_path):
    p = knowledge_path(tmp_path)
    assert p == tmp_path / "knowledge" / "knowledge.jsonl"


def test_role_knowledge_path(tmp_path):
    p = role_knowledge_path(tmp_path, "impl")
    assert p == tmp_path / "knowledge" / "roles" / "impl" / "knowledge.jsonl"
