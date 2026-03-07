"""File I/O helpers for dial — JSONL read/write, directory setup."""

from __future__ import annotations

import json
import os
from collections import deque
from pathlib import Path


def ensure_dir(path: Path) -> None:
    """Create directory (and parents) if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)


def append_jsonl(path: Path, record: dict) -> None:
    """Append a single JSON record to a JSONL file."""
    ensure_dir(path.parent)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    """Read all records from a JSONL file. Returns [] if file doesn't exist."""
    if not path.is_file():
        return []
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def read_jsonl_tail(path: Path, count: int) -> list[dict]:
    """Read the last *count* records from a JSONL file."""
    if not path.is_file():
        return []
    buf: deque[str] = deque(maxlen=count or None)
    with open(path, encoding="utf-8") as f:
        for raw in f:
            stripped = raw.strip()
            if stripped:
                buf.append(stripped)
    records = []
    for line in buf:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def expand_path(path_str: str) -> Path:
    """Expand ~ and env vars in a path string."""
    return Path(os.path.expandvars(os.path.expanduser(path_str)))


# -- Path builders -----------------------------------------------------------


def em_path(storage_dir: Path, session_id: str) -> Path:
    """Path to the EM event log for a session."""
    return storage_dir / "em" / f"{session_id}.jsonl"


def knowledge_path(storage_dir: Path) -> Path:
    """Path to the knowledge JSONL at a given scope root."""
    return storage_dir / "knowledge" / "knowledge.jsonl"


def role_knowledge_path(storage_dir: Path, role: str) -> Path:
    """Path to role-scoped knowledge JSONL."""
    return storage_dir / "knowledge" / "roles" / role / "knowledge.jsonl"


def count_lines(path: Path) -> int:
    """Count non-empty lines in a file. Returns 0 if file doesn't exist."""
    if not path.is_file():
        return 0
    count = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def truncate_jsonl(path: Path, keep: int) -> None:
    """Keep only the last *keep* lines of a JSONL file."""
    if not path.is_file():
        return
    buf: deque[str] = deque(maxlen=keep)
    with open(path, encoding="utf-8") as f:
        for raw in f:
            stripped = raw.strip()
            if stripped:
                buf.append(stripped)
    with open(path, "w", encoding="utf-8") as f:
        for line in buf:
            f.write(line + "\n")
