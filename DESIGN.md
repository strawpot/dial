# Dial — Design

Default file-based memory provider for [StrawPot](https://github.com/strawpot/strawpot).
Zero external dependencies.

Dial implements the `MemoryProvider` protocol with two memory layers:
**Event Memory (EM)** for automatic session history and a unified
**Knowledge store** for facts and domain-specific retrieval. Knowledge
is scoped at three levels (global, project, role). Agents write
knowledge through a `remember` RPC on denden.

---

## Why Not Five Types?

StrawPot's protocol defines five memory kinds (EM, STM, SM, RM, PM).
Dial implements three (EM, SM, RM) and intentionally drops two.

### STM (Short-Term Memory) — Dropped

StrawPot's memory hooks fire only at delegation boundaries —
`get()` before agent spawn and `dump()` after agent completion.
There is no hook during the agent's internal tool-call loop.

This means STM can only pass notes *between* agents (A finishes →
dump → B starts → get), never *within* a single agent's execution.
But inter-agent context already flows through two existing channels:

1. **The orchestrator** relays agent A's result summary in agent B's
   task text — it is the natural context bridge between delegated agents.
2. **EM tail** shows recent session events, covering what happened
   and in what order.

STM would add a fragile side-channel (tagged output extraction) for a
narrow use case already served by the orchestrator and EM. Dropped to
keep the design simple. Can be reconsidered if a clear need emerges.

### PM (Procedural Memory) — Dropped

PM would accumulate per-role instructions across sessions ("always
lint before committing"). The concept is appealing, but:

1. **Overlaps with the static role/skill system.** ROLE.md and SKILL.md
   already define role-specific instructions. PM would be a dynamic
   shadow of what should be codified in those files.
2. **Same fragile write mechanism.** Relies on agents producing
   `[PM]` tagged lines — requires agent cooperation with no guarantee
   of quality.
3. **Real PM needs pattern detection.** Useful procedural lessons
   ("this role fails when it skips linting") require analyzing EM
   history across sessions — not simple line extraction. That level
   of analysis belongs in a more sophisticated provider.

Dropped in favor of keeping role instructions in ROLE.md where they
are version-controlled, reviewed, and deterministic. Note that
role-scoped knowledge entries (see [Knowledge Scopes](#knowledge-scopes))
partially address this need — they allow runtime-discovered,
role-specific facts without the overhead of a separate memory type.

---

## Overview

```
strawpot delegation flow
  │
  ├─ memory.get(session_id, agent_id, role, task, ...)
  │   │
  │   ├─ Knowledge (SM) → global + project + role facts (always included)
  │   ├─ Knowledge (RM) → keyword-matched entries (when task matches)
  │   └─ EM             → recent events from this session (last N)
  │
  │   Returns: GetResult(context_cards, control_signals)
  │
  ├─ [agent runs]
  │   │
  │   └─ denden remember ──→ memory.remember() ──→ dedup + write
  │      (real-time, during agent execution)
  │
  └─ memory.dump(session_id, agent_id, role, task, status, output, ...)
      │
      └─ EM  → append event (always, automatic)

      Returns: DumpReceipt
```

---

## Knowledge Write: The `remember` RPC

Agents write knowledge through denden — a new `remember` action
alongside the existing `delegate` and `ask_user` actions.

```
Agent                    DenDen                   StrawPot
  │                        │                        │
  │  remember(content,     │                        │
  │    keywords, scope)    │                        │
  │ ─────────────────────► │                        │
  │                        │  on_remember callback  │
  │                        │ ─────────────────────► │
  │                        │                        │  memory.remember()
  │                        │                        │  → dedup + write
  │                        │       ok / error       │
  │                        │ ◄───────────────────── │
  │       response         │                        │
  │ ◄───────────────────── │                        │
```

### Why a tool, not tagged output?

The previous design extracted `[MEMORY]` tagged lines from agent
output during `dump()`. This had fundamental problems:

1. **Post-hoc.** Extraction happens after the agent finishes — the
   agent gets no confirmation that its knowledge was captured.
2. **Fragile.** Depends on agents formatting output correctly.
   Subtle formatting differences could cause missed or garbled entries.
3. **Boundary-only.** Only runs at `dump()` time. An agent that
   discovers something mid-task can't persist it until completion.

The `remember` RPC solves all three:

- **Explicit.** The agent deliberately calls `remember` — clear intent.
- **Real-time.** Works during the agent's execution, not just at boundaries.
- **Confirmed.** The agent gets a response (accepted/duplicate).
- **Structured.** Content, keywords, and scope are separate fields — no parsing.

### Protocol Changes Required

**denden** — Add `Remember` message to protobuf:

```protobuf
message RememberRequest {
  string content = 1;
  repeated string keywords = 2;
  string scope = 3;            // "global" | "project" | "role"
}

message RememberResult {
  string status = 1;           // "accepted" | "duplicate"
  string entry_id = 2;
}
```

The `DenDenRequest.oneof` gains a `remember` field alongside
`delegate` and `ask_user`.

**strawpot** — Add `remember` method to `MemoryProvider` protocol:

```python
class MemoryProvider(Protocol):
    name: str
    def get(self, ...) -> GetResult: ...
    def dump(self, ...) -> DumpReceipt: ...
    def remember(
        self,
        *,
        session_id: str,
        agent_id: str,
        role: str,
        content: str,
        keywords: list[str] | None = None,
        scope: str = "project",
    ) -> RememberResult: ...
```

`Session._handle_remember` routes the denden callback to
`memory_provider.remember()`, similar to how `_handle_delegate`
routes to `handle_delegate()`.

**dial** — Implements `remember()` with dedup and direct write.

### Agent-Facing UX

From the agent's perspective, remembering is a denden command:

```bash
denden send '{"remember": {"content": "This project uses pytest", "scope": "project"}}'
denden send '{"remember": {"content": "Payments API needs idempotency keys", "keywords": ["payment", "stripe"]}}'
```

Agents learn about this via a **denden skill** (installed alongside
the agent wrapper). The skill's SKILL.md includes instructions for
when and how to use `remember`. No memory-specific instructions
needed in `get()` — the skill system handles agent onboarding.

---

## Knowledge Scopes

Knowledge entries live at three levels. On `get()`, all applicable
scopes are merged. On `remember()`, the agent specifies the scope
(defaults to `project`).

| Scope | Included when | Example |
|-------|---------------|---------|
| **Global** | Every agent, every project | "Always use conventional commits" |
| **Project** | Every agent in this project | "This project uses pytest" |
| **Role** | Only agents with matching role | "Check migration dir before modifying models" |

Global knowledge lives under the strawpot home directory. Project and
role knowledge live under the project's storage directory.

```
# Global
~/.strawpot/memory/dial-data/
  knowledge/
    knowledge.jsonl

# Project
<project>/.strawpot/memory/dial-data/
  knowledge/
    knowledge.jsonl

# Per-role (within project)
<project>/.strawpot/memory/dial-data/
  knowledge/
    roles/
      <role_slug>/
        knowledge.jsonl
```

**Merge order on `get()`:** global → project → role. All entries are
collected, deduplicated by content, then split into SM (no keywords)
and RM (has keywords) cards.

---

## Storage Layout

```
# Global storage
~/.strawpot/memory/dial-data/
  knowledge/
    knowledge.jsonl              Global knowledge entries

# Project storage (default storage_dir)
<project>/.strawpot/memory/dial-data/
  em/
    <session_id>.jsonl           Append-only event log per session
  knowledge/
    knowledge.jsonl              Project knowledge entries
    roles/
      <role_slug>/
        knowledge.jsonl          Role-scoped knowledge entries
```

All files are human-readable and inspectable with standard tools
(`cat`, `jq`). No database, no binary formats.

EM is always project-scoped. Knowledge entries span multiple scopes.

---

## Memory Types

### Event Memory (EM)

Append-only log of agent lifecycle events within a session.
Fully automatic — no agent cooperation required.

**Storage:** `em/<session_id>.jsonl` — one JSON object per line.

**Schema:**

```json
{
  "event_id": "evt_a1b2c3d4",
  "ts": "2026-01-01T12:00:00+00:00",
  "session_id": "run_abc123",
  "agent_id": "agent_def456",
  "role": "implementer",
  "event_type": "AGENT_RESULT",
  "data": {
    "task": "Implement login form",
    "status": "success",
    "summary": "Created LoginForm component with validation"
  }
}
```

**Event types:**

| Type | When | Data fields |
|------|------|-------------|
| `AGENT_RESULT` | `dump` called | `task`, `status`, `summary` |
| `MEMORY_GET` | `get` called | `card_count`, `sources` |

**Write rule:** Always append, no gate.

**Read rule:** On `get`, return the last `em_tail_count` events from
the current session as a single EM context card. Provides recency
context so agents know what has already happened.

### Knowledge Store (SM + RM unified)

A single store of project knowledge with two read modes, spanning
three scopes (global, project, role).

- **Entries without keywords** → always included (SM behavior).
  Facts and conventions.
- **Entries with keywords** → included only when the task matches
  (RM behavior). Domain-specific knowledge that would be noise for
  unrelated tasks.

**Storage:** `knowledge/knowledge.jsonl` at each scope level —
append-only.

```json
{
  "entry_id": "k_x1y2z3",
  "content": "This project uses pytest with coverage threshold 80%",
  "keywords": [],
  "source": "agent_def456",
  "ts": "2026-01-01T12:10:00+00:00"
}
```

```json
{
  "entry_id": "k_a1b2c3",
  "content": "The payments API requires idempotency keys for all POST requests",
  "keywords": ["payment", "payments", "idempotency", "stripe"],
  "source": "agent_def456",
  "ts": "2026-01-01T12:15:00+00:00"
}
```

**Write:** Agents call `remember` during execution. Content is
deduplicated (exact match) and written directly to the appropriate
`knowledge.jsonl` file based on scope.

**Read rules:**

- Entries with empty `keywords` → always included as SM context cards.
- Entries with `keywords` → scored against the task text using keyword
  overlap. Only entries scoring above `rm_min_score` are included, as
  RM context cards, ranked by score.
- Entries from all applicable scopes (global + project + role) are
  merged and deduplicated before card generation.

---

## `get` Flow

```python
def get(*, session_id, agent_id, role, behavior_ref, task, budget, parent_agent_id):
    cards = []
    sources = []

    # 1. Collect knowledge from all scopes
    global_entries = read_knowledge(global_dir)
    project_entries = read_knowledge(project_dir)
    role_entries = read_knowledge(project_dir / "roles" / role)
    all_entries = deduplicate(global_entries + project_entries + role_entries)

    # 2. Knowledge (SM) — entries without keywords, always included
    sm_entries = [e for e in all_entries if not e["keywords"]]
    if sm_entries:
        cards.append(ContextCard(kind=SM, content=format_entries(sm_entries)))
        sources.append("sm")

    # 3. Knowledge (RM) — entries with keywords, conditionally included
    rm_entries = [e for e in all_entries if e["keywords"]]
    rm_matches = score_and_filter(rm_entries, task, min_score=rm_min_score)
    if rm_matches:
        cards.append(ContextCard(kind=RM, content=format_entries(rm_matches)))
        sources.append("rm")

    # 4. EM — recent session events
    em_events = read_em_tail(session_id, count=em_tail_count)
    if em_events:
        cards.append(ContextCard(kind=EM, content=format_em(em_events)))
        sources.append("em")

    # 5. Budget trimming (if budget is set)
    if budget:
        cards = trim_to_budget(cards, budget)

    return GetResult(
        context_cards=cards,
        control_signals=ControlSignal(),
        sources_used=sources,
    )
```

**Card ordering:** SM → RM → EM. Most stable context first, most
ephemeral last. When trimming for budget, EM is trimmed first, then
RM entries with the lowest scores.

---

## `dump` Flow

```python
def dump(*, session_id, agent_id, role, behavior_ref, task,
         status, output, tool_trace, parent_agent_id, artifacts):
    receipt = DumpReceipt()

    # 1. EM — always append
    event_id = append_em(session_id, agent_id, role, task, status, output)
    receipt.em_event_ids.append(event_id)

    return receipt
```

---

## `remember` Flow

```python
def remember(*, session_id, agent_id, role, content, keywords=None, scope="project"):
    # 1. Deduplicate (exact match against existing entries)
    if exact_duplicate_exists(content, scope, role):
        return RememberResult(status="duplicate")

    # 2. Write directly to knowledge store
    entry = create_entry(content, keywords or [], role, agent_id, session_id)
    append_knowledge(entry, scope, role)

    return RememberResult(status="accepted", entry_id=entry["entry_id"])
```

The `remember()` flow is designed to be extensible. A future gating
layer (e.g., proposal review) can be inserted between dedup and write
without changing the `RememberResult` contract — it would return
`status="queued"` instead of `"accepted"` and write to a proposals
store instead of directly to `knowledge.jsonl`. The protobuf already
includes `"queued"` as a valid status for forward compatibility.

---

## Relevance Scoring (RM)

Simple keyword overlap scoring — no embeddings, no external services.

```python
def score_entry(entry, task_text):
    task_tokens = set(tokenize(task_text.lower()))
    entry_keywords = set(kw.lower() for kw in entry["keywords"])

    if not entry_keywords:
        return 0.0

    overlap = task_tokens & entry_keywords
    score = len(overlap) / len(entry_keywords)
    return score
```

`tokenize` splits on whitespace and punctuation, strips common stop
words. Intentionally simple — good enough for keyword matching without
ML dependencies.

---

## Configuration

### MEMORY.md Manifest

```yaml
---
name: dial
description: Default file-based memory provider for StrawPot
metadata:
  version: "0.1.0"
  strawpot:
    memory_module: provider.py
    params:
      storage_dir:
        type: string
        default: .strawpot/memory/dial-data
        description: Project-level storage directory
      global_storage_dir:
        type: string
        default: ~/.strawpot/memory/dial-data
        description: Global storage directory
      em_tail_count:
        type: int
        default: 20
        description: Number of recent EM events to include in get
      em_max_events:
        type: int
        default: 10000
        description: Max events per session before rotation
      rm_min_score:
        type: float
        default: 0.3
        description: Minimum relevance score for RM entries
---
```

### strawpot.toml

```toml
memory = "dial"

[memory_config]
storage_dir = ".strawpot/memory/dial-data"
em_tail_count = 20
```

---

## Cross-Repo Changes

Adding the `remember` RPC requires coordinated changes across three
repositories:

| Repo | Changes |
|------|---------|
| **denden** | Add `RememberRequest`/`RememberResult` to protobuf. Add `on_remember` callback to `DenDenServer`. Add `remember` command to `denden` CLI. |
| **strawpot** | Add `remember()` to `MemoryProvider` protocol. Add `_handle_remember` to `Session`. Add noop `remember()` to `NoopMemoryProvider`. |
| **dial** | Implement `remember()` with dedup and direct write. |

The denden CLI change means agents can call `remember` the same way
they call `delegate` — no wrapper changes needed. The skill that
teaches agents about denden just needs a new section for `remember`.

---

## Package Structure

```
dial/
  MEMORY.md              Manifest (YAML frontmatter + description)
  provider.py            MemoryProvider implementation (get + dump + remember)
  storage.py             File I/O: read/write JSONL, atomic writes
  scorer.py              RM keyword relevance scoring
  __init__.py
```

5 files. Core functionality requires only Python stdlib + strawpot
protocol types.

---

## Future Extensions

Deferred from v1. The architecture accommodates these without
changing the core protocol:

**Proposal gating.** Insert a review step between `remember()` dedup
and write. Entries go to a `proposals/` directory instead of directly
to `knowledge.jsonl`. The `RememberResult` contract already supports
`status="queued"` for this. Useful for team workflows where untrusted
agent knowledge should be reviewed before becoming permanent.

**LLM enhancement.** Add an optional LLM layer (`llm.py`) for:
- Implicit knowledge extraction from `dump()` output
- Semantic deduplication on `remember()` (catch near-duplicates)
- Auto keyword extraction when agents don't provide keywords

The `remember` RPC alone is the high-value path — the calling agent
is already an LLM with full context. LLM post-processing becomes
valuable at scale but is premature for v1.

---

## Installation

```bash
# Install from StrawHub (once memory package type is added)
strawpot install memory dial

# Or manually: copy to global memory dir
cp -r dial/ ~/.strawpot/memory/dial/

# Or project-local
cp -r dial/ .strawpot/memory/dial/
```

---

## Design Decisions

**Why file-based?** Dial is the default provider. It must work
everywhere with zero setup — no databases, no API keys, no Docker.
Files are inspectable, version-controllable, and trivially backupable.

**Why a `remember` RPC instead of tagged output?** Tagged output
extraction (`[MEMORY] fact`) is post-hoc, fragile, and boundary-only.
The `remember` RPC is explicit (clear agent intent), real-time (works
mid-task), confirmed (agent gets a response), and structured
(no text parsing). Since we own the full stack (denden + strawpot +
dial), adding a new RPC is straightforward.

**Why direct write without gating?** For v1, simplicity wins. The
agent is an LLM that deliberately chose to call `remember` — that's
already a quality signal. Exact-match dedup prevents repeats. Gating
adds friction (who reviews?) without clear benefit at low volume. The
architecture supports adding a proposal gate later without protocol
changes.

**Why three scopes?** Different knowledge has different lifetimes and
audiences. Org conventions (global) shouldn't be re-entered per
project. Project facts shouldn't leak to unrelated projects. Role
discoveries shouldn't clutter other roles' context. Three scopes map
cleanly to strawpot's existing directory hierarchy
(`~/.strawpot/` → `<project>/.strawpot/`), with per-role as a
natural subdivision.

**Why a unified knowledge store?** SM and RM differ only in the read
filter (always vs keyword-scored). One store with two read modes is
simpler than two separate stores with identical schemas.

**Why per-session EM files?** Avoids contention when multiple sessions
run concurrently. Each session appends to its own file. Cross-session
queries (future) can merge files at read time.

**Why JSONL?** Append-friendly (no need to parse/rewrite the whole
file), streamable, and each line is independently parseable. Standard
tooling (`jq`, `wc -l`) works out of the box.

**Why defer LLM and gating?** Build the minimum that's useful, validate
with real usage, then add complexity where data shows it's needed.
