---
name: dial
description: Default file-based memory provider for StrawPot
metadata:
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
        default: 5
        description: Number of recent EM events to include in get
      em_max_events:
        type: int
        default: 10000
        description: Max events per session before rotation
      em_scope:
        type: string
        default: project
        description: "EM retrieval scope: session (current only), project (all sessions in project), or global (all sessions everywhere)"
      rm_min_score:
        type: float
        default: 0.3
        description: "Minimum BM25 relevance score for RM entries, relative to the top result in the batch (0.0 = include all, 1.0 = top result only)"
      simhash_dedup_threshold:
        type: int
        default: 8
        description: "SimHash Hamming distance threshold for near-duplicate detection in remember() (out of 64 bits; lower = stricter dedup)"
---

# Dial

Default file-based memory provider for StrawPot. Zero external dependencies.

Two memory layers:
- **Event Memory (EM)** — automatic session history (append-only JSONL per session)
- **Knowledge Store (SM + RM)** — facts and domain knowledge at three scopes (global, project, role)
