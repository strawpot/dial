"""Dial — file-based MemoryProvider implementation."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from strawpot_memory.memory_protocol import (
    ContextCard,
    ControlSignal,
    DumpReceipt,
    GetResult,
    MemoryKind,
    RecallEntry,
    RecallResult,
    RememberResult,
)

from .scorer import BM25, hamming, score_and_filter, simhash, tokenize
from .storage import (
    append_jsonl,
    count_lines,
    em_dir,
    em_path,
    expand_path,
    knowledge_path,
    read_em_dir,
    read_jsonl,
    read_jsonl_tail,
    role_knowledge_path,
    truncate_jsonl,
)


class DialMemoryProvider:
    """Default file-based memory provider for StrawPot."""

    name = "dial"

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self._storage_dir = expand_path(
            cfg.get("storage_dir", ".strawpot/memory/dial-data")
        )
        self._global_dir = expand_path(
            cfg.get("global_storage_dir", "~/.strawpot/memory/dial-data")
        )
        self._em_tail_count: int = int(cfg.get("em_tail_count", 5))
        self._em_max_events: int = int(cfg.get("em_max_events", 10000))
        self._em_scope: str = cfg.get("em_scope", "project")
        self._rm_min_score: float = float(cfg.get("rm_min_score", 0.3))
        self._known_contents: dict[str, set[str]] = {}   # path -> content set
        self._known_hashes: dict[str, list[int]] = {}    # path -> simhash list

    # -- get ------------------------------------------------------------------

    def get(
        self,
        *,
        session_id: str,
        agent_id: str,
        role: str,
        behavior_ref: str,
        task: str,
        budget: int | None = None,
        parent_agent_id: str | None = None,
    ) -> GetResult:
        cards: list[ContextCard] = []
        sources: list[str] = []

        # 1. Collect knowledge from all scopes
        all_entries = self._collect_knowledge(role)

        # 2. SM — entries without keywords (always included)
        sm_entries = [e for e in all_entries if not e.get("keywords")]
        if sm_entries:
            cards.append(
                ContextCard(
                    kind=MemoryKind.SM,
                    content=_format_knowledge(sm_entries),
                    source="knowledge",
                )
            )
            sources.append("sm")

        # 3. RM — entries with keywords (conditionally included)
        rm_entries = [e for e in all_entries if e.get("keywords")]
        rm_scored = score_and_filter(rm_entries, task, self._rm_min_score)
        if rm_scored:
            cards.append(
                ContextCard(
                    kind=MemoryKind.RM,
                    content=_format_knowledge([e for _, e in rm_scored]),
                    source="knowledge",
                )
            )
            sources.append("rm")

        # 4. EM — recent events (scope: session, project, or global)
        em_events = self._collect_em(session_id)
        if em_events:
            processed = _process_em(em_events, task, self._em_tail_count)
            cards.append(
                ContextCard(
                    kind=MemoryKind.EM,
                    content=_format_em(processed),
                    source="em",
                )
            )
            sources.append("em")

        # 5. Budget trimming
        if budget is not None:
            cards = _trim_to_budget(cards, budget)

        return GetResult(
            context_cards=cards,
            control_signals=ControlSignal(),
            sources_used=sources,
        )

    # -- dump -----------------------------------------------------------------

    def dump(
        self,
        *,
        session_id: str,
        agent_id: str,
        role: str,
        behavior_ref: str,
        task: str,
        status: str,
        output: str,
        tool_trace: str = "",
        parent_agent_id: str | None = None,
        artifacts: dict[str, str] | None = None,
    ) -> DumpReceipt:
        event_id = _make_id("evt")
        event = {
            "event_id": event_id,
            "ts": _now_iso(),
            "session_id": session_id,
            "agent_id": agent_id,
            "role": role,
            "event_type": "AGENT_RESULT",
            "data": {
                "task": task,
                "status": status,
                "summary": _extract_summary(output) if output else "",
            },
        }
        path = em_path(self._storage_dir, session_id)
        append_jsonl(path, event)

        # Rotate if EM file exceeds max events
        if count_lines(path) > self._em_max_events:
            truncate_jsonl(path, self._em_max_events)

        return DumpReceipt(em_event_ids=[event_id])

    # -- remember -------------------------------------------------------------

    def remember(
        self,
        *,
        session_id: str,
        agent_id: str,
        role: str,
        content: str,
        keywords: list[str] | None = None,
        scope: str = "project",
    ) -> RememberResult:
        kw = keywords or []
        store_path = self._knowledge_store_path(scope, role)
        cache_key = str(store_path)

        # Build content cache on first access for this path
        if cache_key not in self._known_contents:
            existing = read_jsonl(store_path)
            self._known_contents[cache_key] = {
                e.get("content", "") for e in existing
            }
            self._known_hashes[cache_key] = [
                simhash(e.get("content", "")) for e in existing
            ]

        # Dedup: SimHash near-duplicate check (Hamming distance < threshold)
        new_hash = simhash(content)
        for existing_hash in self._known_hashes[cache_key]:
            if hamming(new_hash, existing_hash) < _SIMHASH_DEDUP_THRESHOLD:
                return RememberResult(status="duplicate", entry_id="")

        entry_id = _make_id("k")
        entry = {
            "entry_id": entry_id,
            "content": content,
            "keywords": kw,
            "source": agent_id,
            "ts": _now_iso(),
        }
        append_jsonl(store_path, entry)
        self._known_contents[cache_key].add(content)
        self._known_hashes[cache_key].append(new_hash)
        return RememberResult(status="accepted", entry_id=entry_id)

    # -- recall ---------------------------------------------------------------

    def recall(
        self,
        *,
        session_id: str,
        agent_id: str,
        role: str,
        query: str,
        keywords: list[str] | None = None,
        scope: str = "",
        max_results: int = 10,
    ) -> RecallResult:
        if scope:
            entries = self._collect_knowledge_by_scope(scope, role)
        else:
            entries = self._collect_knowledge(role)

        # Filter to entries with keywords for scoring
        kw_entries = [e for e in entries if e.get("keywords")]

        # If explicit keywords provided, narrow to entries matching any of them
        if keywords:
            kw_lower = {k.lower() for k in keywords}
            kw_entries = [
                e for e in kw_entries
                if kw_lower & {k.lower() for k in e.get("keywords", [])}
            ]

        # Also include keyword-less (SM) entries that match the query text
        sm_entries = [e for e in entries if not e.get("keywords")]

        # Score keyword entries against the query
        scored = score_and_filter(kw_entries, query, self._rm_min_score)

        # Prepend SM entries (always relevant, score 1.0)
        result_entries = []
        for e in sm_entries:
            if query.lower() in e.get("content", "").lower():
                result_entries.append(
                    RecallEntry(
                        entry_id=e.get("entry_id", ""),
                        content=e.get("content", ""),
                        keywords=e.get("keywords", []),
                        scope=e.get("_scope", "project"),
                        score=1.0,
                    )
                )
        for s, e in scored:
            result_entries.append(
                RecallEntry(
                    entry_id=e.get("entry_id", ""),
                    content=e.get("content", ""),
                    keywords=e.get("keywords", []),
                    scope=e.get("_scope", "project"),
                    score=s,
                )
            )

        return RecallResult(entries=result_entries[:max_results])

    # -- internal helpers -----------------------------------------------------

    def _collect_em(self, session_id: str) -> list[dict]:
        """Collect EM events based on configured scope."""
        if self._em_scope == "session":
            return read_jsonl_tail(
                em_path(self._storage_dir, session_id), self._em_tail_count
            )
        elif self._em_scope == "global":
            project = read_em_dir(em_dir(self._storage_dir), self._em_tail_count)
            global_ = read_em_dir(em_dir(self._global_dir), self._em_tail_count)
            merged = project + global_
            merged.sort(key=lambda e: e.get("ts", ""), reverse=True)
            return merged[: self._em_tail_count]
        else:  # "project" (default)
            return read_em_dir(em_dir(self._storage_dir), self._em_tail_count)

    def _collect_knowledge(self, role: str) -> list[dict]:
        """Merge knowledge from global, project, and role scopes; deduplicate."""
        global_entries = read_jsonl(knowledge_path(self._global_dir))
        for e in global_entries:
            e.setdefault("_scope", "global")
        project_entries = read_jsonl(knowledge_path(self._storage_dir))
        for e in project_entries:
            e.setdefault("_scope", "project")
        role_entries = read_jsonl(role_knowledge_path(self._storage_dir, role))
        for e in role_entries:
            e.setdefault("_scope", "role")

        all_entries = global_entries + project_entries + role_entries
        return _deduplicate(all_entries)

    def _collect_knowledge_by_scope(self, scope: str, role: str) -> list[dict]:
        """Collect knowledge from a single scope."""
        if scope == "global":
            entries = read_jsonl(knowledge_path(self._global_dir))
        elif scope == "role":
            entries = read_jsonl(role_knowledge_path(self._storage_dir, role))
        else:  # "project"
            entries = read_jsonl(knowledge_path(self._storage_dir))
        for e in entries:
            e.setdefault("_scope", scope)
        return entries

    def _knowledge_store_path(self, scope: str, role: str) -> Path:
        """Return the knowledge.jsonl path for the given scope."""
        if scope == "global":
            return knowledge_path(self._global_dir)
        elif scope == "role":
            return role_knowledge_path(self._storage_dir, role)
        else:  # "project" (default)
            return knowledge_path(self._storage_dir)


# -- Summary extraction -------------------------------------------------------

_RECAP_RE = re.compile(r"##\s+Session Recap\s*\n(.*?)(?=\n##\s|\Z)", re.IGNORECASE | re.DOTALL)
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_MD_STRIP_RE = re.compile(r"[#*_`\[\]()>|~]|-{2,}|={2,}")


def _extract_summary(output: str, max_len: int = 500) -> str:
    """Extract a meaningful summary from agent output.

    Priority order:
      1. ## Session Recap section — explicit, agent-authored
      2. Smart heuristic — first prose paragraph, skipping headers/tables/fences
      3. Strip-markdown fallback — strip syntax, take first max_len chars
    """
    if not output:
        return ""

    # Layer 1: ## Session Recap section
    m = _RECAP_RE.search(output)
    if m:
        recap = m.group(1).strip()
        if recap:
            return recap[:max_len]

    # Layer 2: smart heuristic — find first prose paragraph
    in_fence = False
    prose_lines: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not stripped:
            if prose_lines:
                break  # end of first prose paragraph
            continue
        # Skip headings, horizontal rules, table rows
        if stripped.startswith("#"):
            continue
        if re.match(r"^[-=]{3,}$", stripped):
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            continue
        prose_lines.append(stripped)

    if prose_lines:
        result = " ".join(prose_lines)
        if result:
            return result[:max_len]

    # Layer 3: strip markdown, take first max_len chars
    stripped = _FENCE_RE.sub(" ", output)
    stripped = _MD_STRIP_RE.sub("", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return stripped[:max_len]


# -- Formatting helpers -------------------------------------------------------


_FAILURE_STATUSES = frozenset({"error", "failure", "failed"})

# SimHash dedup: entries with Hamming distance below this threshold are
# treated as near-duplicates (out of 64 bits; 8 = ~12.5% bit difference).
_SIMHASH_DEDUP_THRESHOLD = 8


def _process_em(
    events: list[dict], task: str, tail_count: int
) -> list[dict]:
    """Consolidate, prioritize, and rank EM events.

    1. Consolidate — group by task text, keep latest per group with count.
    2. Prioritise — failures get a score boost.
    3. Relevance — token overlap between current task and event task.

    Returns up to *tail_count* consolidated entries, best-first.
    """
    if not events:
        return []

    # -- 1. Consolidate by task text ------------------------------------------
    from collections import OrderedDict

    groups: OrderedDict[str, list[dict]] = OrderedDict()
    for ev in events:
        key = ev.get("data", {}).get("task", "")
        groups.setdefault(key, []).append(ev)

    consolidated: list[dict] = []
    for _task_key, group in groups.items():
        group.sort(key=lambda e: e.get("ts", ""), reverse=True)
        latest = dict(group[0])  # shallow copy
        latest["_count"] = len(group)
        statuses = [e.get("data", {}).get("status", "") for e in group]
        latest["_failure_count"] = sum(
            1 for s in statuses if s in _FAILURE_STATUSES
        )
        consolidated.append(latest)

    # -- 2 + 3. Score: relevance + status boost + recency ---------------------
    n = len(consolidated)

    # Build BM25 corpus from all event task texts
    em_corpora = [tokenize(e.get("data", {}).get("task", "")) for e in consolidated]
    bm25 = BM25(em_corpora)
    query_tokens = tokenize(task)

    # Compute raw BM25 scores for normalisation
    raw_scores = [bm25.score(query_tokens, doc) for doc in em_corpora]
    max_raw = max(raw_scores) if raw_scores else 1.0

    scored: list[tuple[float, dict]] = []
    for idx, (entry, raw) in enumerate(zip(consolidated, raw_scores)):
        # Relevance: BM25 normalised to [0, 1]
        relevance = (raw / max_raw) if max_raw > 0 else 0.0

        # Status boost: any failure in the group
        status_boost = 1.0 if entry.get("_failure_count", 0) > 0 else 0.0

        # Recency: newest consolidated entry = 1.0, oldest = 0.0
        recency = 1.0 - (idx / n) if n > 1 else 1.0

        score = 0.4 * relevance + 0.3 * status_boost + 0.3 * recency
        scored.append((score, entry))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [entry for _, entry in scored[:tail_count]]


def _format_knowledge(entries: list[dict]) -> str:
    """Format knowledge entries as readable text for context cards."""
    lines = []
    for e in entries:
        lines.append(f"- {e['content']}")
    return "\n".join(lines)


def _format_em(events: list[dict]) -> str:
    """Format EM events as readable text for context cards."""
    lines = []
    for ev in events:
        data = ev.get("data", {})
        role = ev.get("role", "")
        status = data.get("status", "")
        task = data.get("task", "")
        summary = data.get("summary", "")
        count = ev.get("_count", 1)
        failure_count = ev.get("_failure_count", 0)

        ts = ev.get("ts", "")
        if ts:
            # Trim to minute precision: "2026-03-10T14:30"
            ts = ts[:16]
        line = f"[{ts}] [{role}] {task}" if ts else f"[{role}] {task}"
        if status:
            line += f" ({status})"
        if count > 1:
            line += f" [x{count}"
            if failure_count:
                line += f", {failure_count} failed"
            line += "]"
        if summary and summary != task:
            line += f": {summary[:200]}"
        lines.append(line)
    return "\n".join(lines)


def _trim_to_budget(cards: list[ContextCard], budget: int) -> list[ContextCard]:
    """Trim cards to fit within a character budget. EM trimmed first."""
    total = sum(len(c.content) for c in cards)
    if total <= budget:
        return cards

    # Trim EM first, then RM
    result = list(cards)
    for kind in (MemoryKind.EM, MemoryKind.RM, MemoryKind.SM):
        if total <= budget:
            break
        for i, card in enumerate(result):
            if card.kind == kind and total > budget:
                excess = total - budget
                if excess >= len(card.content):
                    total -= len(card.content)
                    result[i] = ContextCard(kind=card.kind, content="", source=card.source)
                else:
                    result[i] = ContextCard(
                        kind=card.kind,
                        content=card.content[: len(card.content) - excess],
                        source=card.source,
                    )
                    total = budget

    return [c for c in result if c.content]


def _deduplicate(entries: list[dict]) -> list[dict]:
    """Deduplicate entries by content, keeping first occurrence."""
    seen: set[str] = set()
    result = []
    for e in entries:
        content = e.get("content", "")
        if content not in seen:
            seen.add(content)
            result.append(e)
    return result


def _make_id(prefix: str) -> str:
    """Generate a short unique ID with prefix."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()
