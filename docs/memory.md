# User profiles and memory

Atlas separates **language capability** (the local model) from **personal
knowledge** (Atlas memory). No fact is written into model weights, and no
profile shares another profile's data.

## Schema (data/atlas.db)

```sql
profiles(id TEXT PRIMARY KEY, name TEXT, created TEXT)

memories(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT, category TEXT, content TEXT, source TEXT,
  created TEXT, updated TEXT, confidence REAL, importance REAL, expires TEXT
)

sessions(id TEXT PRIMARY KEY, title, mode, created, updated, model, user_id)
turns(id INTEGER PRIMARY KEY, mode, role, content, session_id, user_id, ts)
memories_fts  -- FTS5 over (content, category), rowid = memories.id
```

Migrations are additive and run on import; old databases get `user_id`,
`model` and `session_id` columns without losing rows.

## Isolation

- Every memory query includes `WHERE user_id = ?` with the **active profile**.
- Every session query is also scoped by `user_id`; a session from another
  profile does not exist for the current one.
- The Markdown vault is per profile: the default profile keeps `notes/`,
  other profiles get `notes/_profiles/<id>/`. `memory.notes_root()` enforces
  this, so retrieval, digests and note writes all follow the active profile.
- Embedding-cache keys are absolute paths, so two profiles cannot share a
  vector by filename.
- A profile with **no** memories and **no** notes gets a deterministic
  "I don't have that saved" for identity questions. The model never guesses
  an identity from git activity, the local username or file paths.

Secrets (API keys, passwords, bearer tokens, private keys, `.env`) are
rejected by `profiles.add()` before storage.

## Lifecycle

1. A message arrives; the active profile is read from `data/profile.json`.
2. `profiles.search()` ranks FTS5 hits by confidence, importance, recency,
   token overlap and category hints; a keyword scan is the fallback.
3. `memory.recall()` merges up to five structured facts with at most two
   Markdown notes, keeping the prompt compact for a 2B model.
4. After streaming the answer, `_journal()` runs `librarian.extract()`.
   Explicit "remember that …" statements are captured deterministically;
   uncertain ones go through the validating extractor.
5. The fact is written to the active profile's SQLite memory and Markdown
   vault. Similar facts are deduplicated or reconciled, not duplicated.
6. `remember`, `forget_memory`, `update_memory`, `list_memories` and
   `search_notes` tools let the model change memory explicitly, always
   scoped to the active profile.

Retrieved memories are presented as untrusted data in a labelled context
block, never as system instructions.

## Offline

Profiles, memory and retrieval use only local SQLite and files. The only
network calls in the whole app are to the selected local inference endpoint
and, optionally, a local embedding server. There is no telemetry, sync or
remote auth. `tests/test_core.py::OfflineMemory` blocks all socket connects
and verifies memory-backed retrieval still works.

## Commands

```bash
atlas user list | create NAME | switch ID
atlas memory list | search QUERY | add CATEGORY TEXT
atlas memory correct ID TEXT | forget ID
atlas memory import [FILE] | export | clear --yes
uv run python scripts/import_seed.py        # notes/*-seed-*.md -> active profile
```

GUI: profile selector in the sidebar footer, **mem** button opens the
inspector. Replies show a "used N saved memories" line when memory was used.
