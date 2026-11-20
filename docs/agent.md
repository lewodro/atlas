# Agent runtime

Atlas is a small agent loop, not a chat wrapper. Everything below runs locally.

## Tool registry

`registry.py` is the single source of truth. A provider registers a `ToolSpec`
with:

| Field | Meaning |
|---|---|
| `id` | stable tool name |
| `description` | short text shown to the model |
| `schema` | compact JSON schema for tool arguments |
| `availability` | callable/bool, checked at runtime |
| `category` | web / filesystem / git / memory / … |
| `permission` | `ALLOW`, `ASK` or `DENY` |
| `provider` | `atlas` today; MCP/GitHub/etc. later |

The same registry produces the model's tool list, `atlas tools`, the server's
`/api/tools`, and the GUI Tools page. A new provider can call
`registry.register(ToolSpec(...))` without touching the loop.

## Real tools

- `web_search` — DuckDuckGo (no key) or Brave via `ATLAS_BRAVE_KEY`
- `web_fetch` — SSRF-safe page text with source URL
- `filesystem` — read/write/list inside the configured workspace
- `git_status`, `git_diff`, `git_log` — read-only local Git, no network

No shell, delete, push, reset or rebase tool exists.

## Skills

Skills are instructions, not capabilities. Files live at
`skills/<skill-id>/SKILL.md` with frontmatter `name`, `description`, `tags`
and `tools`.

Only name/description/tags are advertised. `skills.load_skill()` reads the
full body only when the skill is selected by keyword match or opened in the UI.

Starter skills: **web-research**, **github-engineer**, **project-explorer**,
**personal-memory**.

For very small models the server adds one bounded follow-up after a skill's
first tool call so the workflow completes (e.g. research fetches the source it
found; Git inspection calls status and diff).

## Loop

```
request → select skill (lazy) → build compact system + workspace context
        → model → tool calls (≤4 rounds) → structured results
        → more tools if needed → answer → journal durable facts
```

Tool results are structured `{ok, data, error, duration_ms, permission}`.
Errors are returned to the model as text instead of crashing the loop.

## Permissions

`ALLOW` runs immediately. `ASK` pauses the stream and emits a permission event;
the GUI shows Allow/Deny and the CLI prompts on stdin. `DENY` is never
advertised. Overrides are stored locally in `data/permissions.json`.

Examples: web search ALLOW, filesystem read ALLOW, filesystem write ASK,
future shell DENY.

## Artifacts

Only explicit registrations become artifacts. A filesystem write registers a
file with its chat id; the chat shows an artifact card and the Artifacts page
lists it with a text/image preview. Artifacts are scoped to the active profile.

## Workspace context

Workspaces are configured with `atlas tools configure --workspace PATH`.
The system prompt gets one short line: root, repo name, branch and clean/dirty
state. Git is local only — there is no GitHub API in this runtime.

## Usage

`data/tool_activity.jsonl` records real tool calls with success, error and
duration. The Usage page aggregates these into small text bars. Tokens, tok/s
and prompt tokens are labelled unavailable because the local runtime does not
expose them; nothing is invented.

## CLI

```bash
atlas tools                         # registry-driven list
atlas tools permissions             # effective levels
atlas tools run web_search --args '{"query":"python lists"}'
atlas skills list | show web-research
atlas artifacts list | show a-xxxx
atlas workspace
```
