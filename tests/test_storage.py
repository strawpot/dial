"""Tests for dial_memory.storage."""

from dial_memory.storage import (
    append_jsonl,
    count_lines,
    em_path,
    expand_path,
    knowledge_path,
    read_jsonl,
    read_jsonl_tail,
    role_knowledge_path,
    truncate_jsonl,
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


def test_read_jsonl_skips_corrupted_lines(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text('{"a": 1}\nNOT JSON\n{"b": 2}\n')
    records = read_jsonl(path)
    assert records == [{"a": 1}, {"b": 2}]


def test_read_jsonl_tail_skips_corrupted_lines(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text('{"i": 0}\nBAD\n{"i": 1}\n{"i": 2}\n')
    tail = read_jsonl_tail(path, 3)
    # deque keeps last 3 raw lines: "BAD", {"i":1}, {"i":2}
    # but BAD is skipped in parsing
    assert tail == [{"i": 1}, {"i": 2}]


def test_count_lines(tmp_path):
    path = tmp_path / "data.jsonl"
    for i in range(5):
        append_jsonl(path, {"i": i})
    assert count_lines(path) == 5


def test_count_lines_missing_file(tmp_path):
    assert count_lines(tmp_path / "nope.jsonl") == 0


def test_truncate_jsonl(tmp_path):
    path = tmp_path / "data.jsonl"
    for i in range(10):
        append_jsonl(path, {"i": i})
    truncate_jsonl(path, 3)
    records = read_jsonl(path)
    assert records == [{"i": 7}, {"i": 8}, {"i": 9}]


def test_truncate_jsonl_missing_file(tmp_path):
    truncate_jsonl(tmp_path / "nope.jsonl", 5)  # should not raise
