---
name: dial
description: Default file-based memory provider for StrawPot
metadata:
  version: "0.1.0"
  strawpot:
    pip: dial-memory
    memory_module: dial_memory.provider
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

# Dial

Default file-based memory provider for StrawPot. Zero external dependencies.

Two memory layers:
- **Event Memory (EM)** — automatic session history (append-only JSONL per session)
- **Knowledge Store (SM + RM)** — facts and domain knowledge at three scopes (global, project, role)
