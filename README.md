# Atlas

**A local AI mentor that actually remembers you — running on your own laptop, no account, no cloud, $0/month.**

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)]()
[![Local](https://img.shields.io/badge/runs-100%25%20local-brightgreen)]()
[![License](https://img.shields.io/badge/license-MIT-black)]()

Atlas keeps durable memories in a local SQLite database and plain Markdown,
retrieves the relevant ones next time, and never sends them anywhere. Memory
survives model swaps: choose Ollama, LM Studio, llama.cpp or vLLM and your
private data stays yours.

```
you> I'm learning Python on an M4, prefer short answers.
     · noted -> notes/the-user-prefers-short-answers.md

$ atlas                       # restart, any model
you> what do you know about me?
atlas> You prefer short answers. You're learning Python on an M4.
```

---

## Requirements

- **Python 3.12+** (the repo pins 3.13 in `.python-version`; `uv` installs it for you)
- **[uv](https://docs.astral.sh/uv/)** for dependencies
- **One local model runtime**, optional but recommended:
  - [Ollama](https://ollama.com) — easiest; default port `11434`
  - [LM Studio](https://lmstudio.ai) — default port `1234`
  - llama.cpp server (`:8080`) or vLLM (`:8000`)
- No API key for local runtimes. No cloud account. No authentication.

Everything else is in `uv.lock`. Nothing is downloaded from this repo except code.

---

## Quick start

```bash
git clone https://github.com/lewodro/atlas && cd atlas
uv sync                       # creates .venv, installs openai + numpy
cp .env.example .env          # choose runtime + model here
```

Pick a model and install it (Ollama example):

```bash
ollama pull deepseek-r1:7b    # no API key needed for local Ollama
# Low-memory machine (e.g. 8 GB M1): use a 3B model instead:
# ollama pull qwen2.5:3b
```

The `.env` you copied already selects the Ollama runtime:

```ini
ATLAS_MODEL_PROVIDER=ollama
ATLAS_OLLAMA_URL=http://127.0.0.1:11434
ATLAS_API_KEY=ollama
```

`ATLAS_MODEL` is intentionally left unset in the example. Atlas then
**auto-detects the first installed local model on whichever machine you run
it on**. That means the same repo works on an 8 GB M1 with a small 3B model and
on a bigger machine with DeepSeek R1 7B — no source edits, no per-machine
hardcoding. To force a model on a particular machine, set it in `.env` (this
file is gitignored) or use `atlas use <model>`:

```ini
# 8 GB M1
ATLAS_MODEL=qwen2.5:3b
# bigger machine (after `ollama pull deepseek-r1:7b`)
ATLAS_MODEL=deepseek-r1:7b
```

Diagnose the install, then start:

```bash
uv run python check.py        # should end with "All good"
uv run python main.py         # interactive chat in the terminal
```

Prefer a browser? `uv run python server.py` serves `http://localhost:7777`
(or `atlas web`, which opens it and stops the server when the tab closes).

**Code agent out of the box.** On a fresh clone the workspace defaults to the
Atlas checkout, so the agent can read and write files, list directories and run
allowlisted commands (`ls`, `cat`, `git status`, `python <script.py>`,
`uv run python <script.py>`) with no extra setup. Point it at another project
with `atlas tools configure --workspace ~/dev/project` or `ATLAS_WORKSPACE`.
Writes stay inside that workspace; hidden files and keys are refused, and
destructive moves/deletes still need an explicit Allow. Models that cannot
emit native tool calls (e.g. DeepSeek R1 on Ollama) use a bounded JSON action
planner — one plan per turn, max three validated actions — so they can still
create and run code. Research topics and code tasks are never saved as memory.

**Deep reasoning, still bounded.** Reasoning checkpoints (DeepSeek R1, QwQ,
thinking models) get a 4096-token generation ceiling automatically instead of
the normal 1024, with one bounded retry if they spend it all thinking. Override
with `ATLAS_REASONING_TOKENS` / `ATLAS_MAX_TOKENS` in `.env`. Generation is
never unbounded, so a slow model cannot saturate Ollama.

**Current questions actually search the web.** Ask about "latest releases",
"current prices", "this week's breaches" or "November 2026" and Atlas loads
`web-research`, runs `web_search` (and `web_fetch` where useful), and grounds
the answer in those results. If the web is unreachable it says so instead of
inventing a "latest" list. Ordinary questions (e.g. "what is a list
comprehension?") never trigger a search. See [docs/agent.md](docs/agent.md).

Optional: put the `atlas` launcher on your PATH for the short commands used
below and in the docs:

```bash
mkdir -p ~/.local/bin
ln -sf "$(pwd)/atlas" ~/.local/bin/atlas   # ensure ~/.local/bin is on PATH
atlas check
```

`./install.sh` is an alternative all-in-one installer (uv + Ollama + model +
doctor). It is idempotent and never touches `data/` or `notes/`. On Windows use
`install.ps1`; see [SETUP-WINDOWS.md](SETUP-WINDOWS.md).

---

## `check.py` — the doctor

```bash
uv run python check.py        # or: atlas check
```

It reports Python version, dependencies, venv, `.env` and environment variables,
provider registry, selected runtime/model, local data dir, memory store,
workspace config, listening ports, Ollama/LM Studio reachability, installed
model, a real generation, tool calling, memory extraction, embeddings and notes.
Failures explain the fix instead of dumping a traceback, e.g.:

```
[ FAIL ] selected model installed — Ollama is running, but deepseek-r1:7b
         is not installed. Run: ollama pull deepseek-r1:7b
```

Nothing is printed from `ATLAS_API_KEY` or any other secret.

Verify the memory path separately with the offline suite:

```bash
uv run python -m unittest discover -s tests -v
```

---

## Model configuration

Atlas talks to anything that speaks the OpenAI chat-completions API. The
runtime list is one registry (`config.PROVIDERS`) shared by `.env`, the CLI
and the Web UI, so they never disagree.

| Provider | `.env` value | Default endpoint |
|---|---|---|
| Ollama | `ollama` | `http://127.0.0.1:11434/v1` |
| LM Studio | `lmstudio` | `http://127.0.0.1:1234/v1` |
| llama.cpp | `llamacpp` | `http://127.0.0.1:8080/v1` |
| vLLM | `vllm` | `http://127.0.0.1:8000/v1` |
| Any compatible endpoint | `ATLAS_BASE_URL=...` | your URL |

Existing names still work: `ATLAS_BASE_URL` overrides the provider URL, and
`ATLAS_MODEL` chooses the model. `ATLAS_OLLAMA_URL` sets Ollama's root; sibling
variables (`ATLAS_LM_STUDIO_URL`, `ATLAS_LLAMACPP_URL`, `ATLAS_VLLM_URL`) do the
same for the others. Local servers ignore the API key — any non-empty value is
fine (`ollama` is the default).

### Switching models without editing source

```bash
atlas models                         # detected runtimes + installed models
atlas models --runtime lmstudio      # point at LM Studio
atlas use qwen2.5:7b                 # change the default model
atlas models --pull qwen2.5:7b       # download with Ollama, then use it
atlas models --endpoint http://127.0.0.1:1234/v1 --use local-model
```

Choices live in `data/settings.json` (gitignored) and win over `.env`, so the
Web UI can switch models with no restart. Click **⚙** in the UI to pick a
runtime and model; the top-bar dropdown switches models per chat. Embedding
models are hidden from the picker. See [docs/custom-models.md](docs/custom-models.md).

If no `.env`, no `data/settings.json` and no `ATLAS_MODEL` are present, Atlas
auto-detects the first local runtime that answers and uses its first chat model.
That is why a bare clone can still pass `check.py`.

### Qwen instead of DeepSeek, or any other local model

```bash
ollama pull qwen2.5-coder:7b
atlas use qwen2.5-coder:7b          # or edit ATLAS_MODEL in .env
```

---

## Running Atlas

```bash
uv run python main.py                # unified agent, interactive
uv run python main.py --once "explain pointers"
atlas study "explain derivatives"   # one-shot study session
uv run python server.py              # Web UI on :7777
uv run python server.py --stay-open # keep it running until Ctrl+C
```

Useful commands (see [docs/tools.md](docs/tools.md) for the security model):

```bash
atlas tools                          # registry-driven tool list + permissions
atlas skills list | show web-research
atlas artifacts list
atlas workspace                      # root, repo, branch, clean/dirty
atlas goal set "summarize the last commit"
atlas agents roles
atlas bench
```

The agent loop selects a skill, calls tools, inspects results and answers.
Writes require an explicit Allow; DENY tools are never advertised. See
[docs/agent.md](docs/agent.md).

---

## Memory — local, private, portable

Durable memories live in:

- **`data/atlas.db`** — SQLite: profiles, structured memories, chat sessions/turns, FTS index
- **`notes/`** — human-readable Markdown, one fact per file (`_`-prefixed files are generated)

Both are **gitignored**. The repository ships the engine, schema, migrations,
tests, example docs and seed tooling — never personal memories, chats, profile
data, paths or secrets. On import, Atlas creates the data/notes directories and
an **empty** memory store by default. There is no built-in identity: Atlas never
assumes who you are until your own memories say so.

Profile isolation: every memory and session query is scoped to `user_id`.
Switching models never changes what you remember; switching profiles isolates it.

```bash
atlas user list | create "Friend" | switch u-xxxxxxxx
atlas memory list | search "tennis" | add projects "Side project: grid renderer"
atlas memory correct 19 "Updated fact" | forget 19
atlas remember "I am learning Rust."     # explicit write, no model call
```

### Move your memories to another machine (private, no GitHub)

```bash
atlas memory export atlas-memory.json   # one profile's durable memories
# copy atlas-memory.json privately (USB, encrypted drive, password manager…)
atlas memory import atlas-memory.json
```

The file is versioned JSON (`format: atlas-memory`, `version: 1`) containing the
profile id/name and memories with their ids, categories, timestamps and scores.
Import validates the format/version, preserves ids and categories, rejects
secrets, and skips rows already present (by id or near-identical content), so
re-importing is safe. Without a filename, `atlas memory export` prints JSON to
stdout, and `atlas memory import` reads legacy `notes/*-seed-*.md` notes.
Full schema: [docs/memory.md](docs/memory.md).

---

## Web UI

Same harness, same memory, saved sessions. On first launch Atlas probes
Ollama, LM Studio, llama.cpp and vLLM in parallel — click ⚙ to switch runtimes
and models without editing files. Vanilla HTML/CSS/JS, no build step.

`⌘K` new chat · `↵` send · `⇧↵` newline · `esc` stop. Themes and UI preferences
live in browser local storage. The sidebar has chats, Tools, Skills, Artifacts,
Usage and Memory; every non-chat view has a **← Chat** arrow.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Missing credentials` / `OpenAIError` on startup | Update to this version (empty API keys are now replaced with a local placeholder). For local Ollama set `ATLAS_API_KEY=ollama` in `.env`. |
| `Ollama is not reachable` | `ollama serve` or `brew services start ollama`; confirm `curl http://127.0.0.1:11434/api/tags` |
| `... is not installed. Run: ollama pull ...` | Run the exact `ollama pull <model>` line from `check.py`, then re-run the doctor |
| Port occupied (`11434`, `1234`, `8080`, `8000`) | Stop the conflicting process, or set `ATLAS_OLLAMA_URL` / another provider URL / `ATLAS_BASE_URL` to a free port |
| `no .env` / config missing | `cp .env.example .env`, set `ATLAS_MODEL` and your provider, then `uv run python check.py` |
| Model answers but never remembers | Check the `memory extraction` line; use `atlas remember "..."` for explicit writes |
| Recall feels weak | `ollama pull nomic-embed-text`, or use `ATLAS_RETRIEVAL=keyword` offline |
| Filesystem/terminal tools say *not configured* | `atlas tools configure --workspace ~/dev` or set `ATLAS_WORKSPACE`; this is by design |
| Empty reply from a reasoning model | Raise `ATLAS_MAX_TOKENS` (e.g. `1024`); thinking consumes output tokens |
| `uv: command not found` | Install [uv](https://docs.astral.sh/uv/) (`brew install uv`) |

For older platform notes see [SETUP-MAC.md](SETUP-MAC.md) and
[SETUP-WINDOWS.md](SETUP-WINDOWS.md).

---

## Privacy & security

`data/` and `notes/` are gitignored; Git history contains no `.env`, database,
chat history, personal memory or model weights. Network calls are pinned with
SSRF checks on redirects; filesystem access is confined to an explicit
workspace. Secrets are rejected before they can be stored as memory. No
telemetry, sync or remote auth. `COSTS.md` explains the optional frontier tier.

## License

MIT. Take it, change it, ship it.
