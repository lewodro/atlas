# Atlas + Obsidian

Atlas memory is already Markdown, so Obsidian is a storage choice rather than
an export step. Set one variable and new memories appear in your vault:

```ini
# .env
ATLAS_VAULT=/Users/you/Documents/My Vault
```

Atlas creates this structure on first use:

```text
My Vault/
└── Atlas/
    └── Memory/
        ├── 20261117-143022-the-user-is-learning-rust.md
        ├── 20261117-144105-the-user-prefers-examples.md
        └── _digest.md
```

Each durable fact is one note with Obsidian-compatible properties:

```markdown
---
created: 2026-11-17T14:30:22
updated: 2026-11-17T14:30:22
type: atlas-memory
tags: [learning, rust]
---

The user is learning Rust.
```

Files beginning with `_` are generated summaries. Atlas does not return them
as individual search results; `_digest.md` is loaded separately as compact
background context.

## How updates work

- Tell Atlas a durable fact naturally. A guarded librarian pass extracts up to
  three facts after the answer and writes them to the vault.
- Use `atlas remember "I use Fedora on my desktop."` when you want an explicit,
  deterministic write without relying on model extraction.
- Correct Atlas in chat and it can update the exact matching note through a
  guarded `update_memory` tool. You can also edit or delete any memory in
  Obsidian. Atlas reads the files again on the next turn, and changed files
  are re-embedded automatically.
- Run `atlas sleep` after a larger cleanup to regenerate `_digest.md`.

Atlas never watches the entire vault and never changes unrelated notes. Only
`Atlas/Memory/` is managed. To use another folder exactly, set
`ATLAS_NOTES_DIR` instead of `ATLAS_VAULT`.

## Keep private data private

The Markdown files and `data/atlas.db` can contain personal information. Keep
the vault private, encrypt device backups, and do not publish either folder.
The repo ignores its default `notes/` and `data/`, but your Obsidian sync and
backup rules are outside Atlas.
