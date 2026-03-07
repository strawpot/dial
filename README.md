# Dial

Default file-based memory provider for [StrawPot](https://github.com/strawpot/strawpot).

Two memory layers — **Event Memory** and a unified **Knowledge store** —
using local JSON/JSONL files. Zero external dependencies.

## Quick Start

```toml
# strawpot.toml
memory = "dial"
```

## How It Works

- **EM** — Append-only event log per session. Fully automatic, no agent cooperation needed.
- **Knowledge (SM)** — Facts and conventions, always included. Scoped to global, project, or role.
- **Knowledge (RM)** — Domain-specific entries, included only when the task keywords match.

Knowledge is scoped at three levels:

| Scope | Example |
|-------|---------|
| **Global** | "Always use conventional commits" |
| **Project** | "This project uses pytest" |
| **Role** | "Check migration dir before modifying models" |

Agents write knowledge via the denden `remember` RPC during execution:

```bash
denden send '{"remember": {"content": "This project uses pytest", "scope": "project"}}'
denden send '{"remember": {"content": "Payments API needs idempotency keys", "keywords": ["payment", "stripe"]}}'
```

Entries are deduplicated and written directly to the knowledge store.

See [DESIGN.md](DESIGN.md) for architecture details.

## License

[MIT](LICENSE)
