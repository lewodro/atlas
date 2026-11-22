# Agent runtime

Atlas is a small agent loop, not a chat wrapper. Everything below runs locally.

## Slash palette and goals

Typing `/` in the composer opens a palette of installed skills and workspace
commands. Skills appear as `/skill:<id>` and load that exact SKILL.md for the
turn; actions include `/goal`, `/skills`, `/tools`, `/memory` and `/usage`.
Arrow keys and Enter select; Escape closes.

`/goal <objective>` creates a local goal and starts a bounded agent loop:

```
goal set → model chooses tools → results recorded as progress
         → more tools if needed → GOAL COMPLETE → goal marked done
```

Goals are stored per profile in `data/atlas.db`. The system prompt carries one
compact GOAL block (text, status, last six progress notes), so even a 3B model
can keep the objective in view. Tool rounds are capped, permissions still apply,
and the loop emits real `goal` events to the UI. CLI equivalents:
`atlas goal set "..."`, `atlas goal status`, `atlas goal clear`.

## Local workers and orchestration

A worker is a separate Atlas server process with its own model, workspace,
SQLite memory, notes folder and port. It runs the same server code, so all
security rules (SSRF guard, workspace confinement, permissions) still apply.

```bash
atlas workers create Research --workspace ~/devAI/AtlasWSPC \
  --model qwen2.5:3b --role research
atlas workers create Engineer --workspace /tmp/project \
  --model qwen-local:latest --role engineer
atlas workers start <id>
atlas workers ask <id> "inspect this repo"
atlas orchestrate "research game releases and compare with the local demo"
atlas workers stop <id>
```

`dispatch.py` runs workers in parallel (bounded to six), gives each a role-
specific task, and asks the main local model to synthesize their reports. It
never invents a source: worker failures are reported as failures. An empty
tool turn is recovered with one final text-only answer so small models do not
return "(no answer)" after using tools.

Workers are local processes only. There is no cloud coordinator, no account and
no billing. An OpenAI-compatible endpoint can be supplied with `--base-url`,
so other local runtimes (or a self-hosted OpenAI-compatible service) can be
registered as workers without changing the core loop. The Workers page in the
GUI lists, starts and stops workers and runs goals with streaming output.

## Why one file tool

Early Atlas had `filesystem` (read/write/list) and `file_manager` (write/mkdir/
move/delete). They overlapped, cost two schemas and confused a 3B model. They
are now one `files` tool with six actions. `atlas fs` and `atlas fm` are CLI
aliases to it.

The terminal is a fixed allowlist, not a Codex-style general shell. A small
model with an unrestricted shell can destroy data; the allowlist keeps every
command read-only, fixed-flag and confinable to the workspace. Larger local
models (12B–20B) do not need more tools — ten short schemas with clear names
usually outperform a large overlapping set, and the same registry scales.

## Local info vs public repo

The repo is clean by design: only tools, capabilities, skills, UI and docs.
All user-specific state lives in gitignored `data/` and `notes/`. `context.py`
assembles the model prompt from that state at runtime and contains no personal
facts. `tests/test_agent.py` checks tracked source files for local identifiers.

## One agent and orchestrator

There is one mode, `agent`. `modes.py` keeps old names as aliases but does not
advertise them. Skills are loaded on demand by `skills.select_skill()` or by
the orchestrator role plan.

`orchestrator.py` defines roles (`general`, `study`, `research`, `engineer`,
`memory`). A role is only a bundle of skill ids — never a separate model or
prompt family. `atlas agents plan "..."` shows the role and skills for a
request before any model call.

Instances are named workspace + data pairs. `atlas agents run ID --port N`
starts a server with `ATLAS_WORKSPACE`, `ATLAS_DATA_DIR` and `ATLAS_NOTES_DIR`
set, so chats, memories, artifacts and notes are fully isolated between
instances. This is the base for running several agents later.

## Rich chat rendering

`web/render.js` is a tiny offline renderer. It turns `\(...\)` and
`\[...\]` into readable Unicode/HTML math, formats Markdown headings,
lists, bold, inline code and fenced code, and drops fake image links. Real
`plot_function` output is displayed in its own result block so a text plot is
visible instead of a hallucinated `![...]` link.

Study prompts are bounded: question-only requests skip tools, pin the exact
topic from the user's words, and get one validated retry if the model answers
with the wrong topic or the wrong number of questions.

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

## Study tools

`plot_function` draws a real text plot with a safe AST parser (no `eval` of
arbitrary code). Supported: `x**2`, `sin(x)`, `sqrt(abs(x))`, constants
`pi`/`e`. The `study` skill uses it to draw functions and keep answers short.

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

## Fine-tuning for small models

No weights are changed. The prompt is tuned instead:

- `context.py` injects one bounded card: saved facts, workspace state and a
  small project map (only when relevant), capped at 1800 characters
- canonical facts are pulled by category when keyword retrieval is weak
- skill selection prefers `personal-memory` for "what do you know about me"
- `skills_list` / `skills_load` let the model load instructions on demand
- deterministic follow-ups complete research and Git workflows

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
