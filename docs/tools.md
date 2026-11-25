# Tools

Atlas has three working tools. All of them are available in chat and from the
CLI. They share one rule: tool output is **untrusted data**, never instructions.

## Web search

```bash
atlas net search "Python lists tutorial" --limit 5
```

Uses DuckDuckGo's lightweight HTML endpoint by default — no account, no API
key. Set `ATLAS_BRAVE_KEY` to use Brave Search instead.

Results are titles, URLs and snippets. Every URL is re-vetted before display:
private, loopback, link-local and reserved addresses are rejected.

## Web fetch

```bash
atlas net fetch https://example.com
```

Returns the page title, final URL, content type and readable text. Scripts,
styles and markup are stripped.

`netguard.py` enforces the network boundary:

- http(s) only, ports 80/443 only, no credentials in URLs
- DNS is resolved once and the TCP connection is pinned to a public IP, so
  DNS rebinding cannot redirect the request to an internal host
- redirects are capped and every hop is re-vetted
- response size is capped at 256 KB; unsupported content types are refused
- certificate verification stays on (including the macOS system CA bundle)

## Filesystem

```bash
atlas tools configure --workspace ~/dev/my-project
atlas fs list
atlas fs read src/main.py
printf 'hello\n' | atlas fs write notes/hello.md
```

Nothing outside the configured workspace is reachable. Refused:

- paths that resolve outside the workspace, including `..`
- symlinks
- hidden files/directories (`.env`, `.git`, `.ssh`, …)
- key/credential files (`.pem`, `.key`, `.p12`, `id_rsa`, …)
- binary files and content with NUL bytes

Only `read`, `write` and `list` exist. There is no delete, move, glob or shell
primitive. Writes are atomic and inherit the existing file mode.

## One file tool

`filesystem` and `file_manager` were two overlapping tools. They are now one
tool, `files`. Keeping both confused small models and doubled the schema cost.
All workspace file operations live in `files`, and `atlas fs` / `atlas fm` are
both CLI shortcuts to it.

## File manager

```bash
atlas fm list
atlas fm read src/main.py
atlas fm write notes/hello.md --text "hello"
atlas fm mkdir drafts
atlas fm move drafts/hello.md notes/hello.md
atlas fm delete drafts
```

Actions `write`, `mkdir`, `move` and `delete` require an `ASK` approval. Paths
are confined to the workspace; hidden files, keys, symlinks and the workspace
root itself are refused. Writes register a real artifact.

## Terminal (allowlisted, not a shell)

Codex-style agents use a general shell. Atlas deliberately does **not**: a 3B
model with an unrestricted shell is a security risk. The terminal here is a
fixed allowlist with no pipes, redirects or arbitrary executables. On a larger
local model (12B–20B) the same small tool set still works — fewer, clearer
tools usually beat many overlapping ones. The whole registry is 10 tools with
short descriptions so it fits a small context window.

```bash
atlas term ls
atlas term git status
atlas term git log --oneline
atlas term tree
```

Only these run: `ls`, `pwd`, `cat`, `tree`, `git status`, `git log`,
`git diff`, `git branch`. There are **no pipes, redirects, chaining, globs,
env vars or arbitrary executables**. Every command runs with `shell=False`,
a timeout and capped output, with `cwd` fixed to the configured workspace.

## Company research

`company_research` (CLI: `atlas company "Nvidia"`) runs four query groups —
overview, financials, recent news and market — and fetches real pages. Source
count and page length scale with the configured local model: 4 sources on a 3B,
6 on a 7B, 8 on a 12B+, with an optional `sources` override (2-10). The digest
carries source URLs and untrusted page text; the model is nudged to cite at
least two URLs and a bounded retry restores URLs if it drops them.

The `/company` slash action inserts a ready-made research prompt in the
composer.

## Status and configuration

```bash
atlas tools          # list tools and status
atlas tools status   # one JSON object per tool
atlas tools configure --workspace PATH
```

The GUI Tools page shows the same status and lets you set the workspace without
leaving the browser.

## Goal execution and learned tool use

Action requests always use `goalrunner.py` first — including models that can
emit native tool calls. Set `ATLAS_USE_GOALRUNNER=0` to keep the older native
loop. When a request needs several actions, `goalrunner.py` runs a bounded loop:
short plan → registry validation → real tool calls → compact observations →
goal check → bounded replan. Steps are deduplicated, read-only steps are safe
to run in sequence, and writes stay inside the workspace. If a step fails, the
model gets one bounded repair attempt; if nothing works, the run reports the
observed failure instead of claiming success. Native tool calls from capable
models still go through the original loop in `main.py` / `server.py`.

Two lightweight learning mechanisms improve tool choice over time:

- `toolpolicy.py` keeps a Beta posterior of success for each
  *(task signature, tool)* pair, updated after every real tool observation.
  `rank()` uses Thompson sampling (small epsilon) to favour tools that work on
  similar goals while still exploring. `atlas policy` shows the learned scores.
- `examples.py` stores plans that reached their goal and retrieves similar
  ones with **TF-IDF plus semantic embeddings** (the local `nomic-embed-text`
  model, cached on disk). This lets "make a script" match "write a program".
  Set `ATLAS_EXAMPLE_SEMANTIC=0` to use keywords only.
- `feedback.py` grades answers from observed tool output and folds the next
  user message into the reward: "thanks" is positive, "that's wrong" is a
  correction. Set `ATLAS_FEEDBACK_MODEL_GRADE=1` to add an optional small-model
  grader; the deterministic grader is always on. Rewards update both the tool
  policy and the stored plan quality.

All stores live in the gitignored local `data/atlas.db` and are per profile.
Learning data is portable:

```bash
atlas policy                                   # overall tool success
atlas policy "write a parser, then test it"    # signature, history, examples
atlas policy --export ~/atlas-learning.json    # back up everything learned
atlas policy --import ~/atlas-learning.json    # restore on another device
```

## Providers and data egress

Atlas speaks one API shape (OpenAI-compatible chat completions), so local
runtimes and hosted APIs use the same code path. List them with:

```bash
atlas models --list-providers
```

Local runtimes (Ollama, LM Studio, llama.cpp, vLLM) need no key and keep data on
the machine. Hosted presets are ordered by ease: **OpenRouter** (one key, many
models), **Groq** (fast free tier), **Gemini** (free tier), then DeepSeek,
Together, Mistral and OpenAI. Connect with:

```bash
atlas models --provider openrouter --use openai/gpt-4o-mini
```

Keys are read from environment variables listed in `.env.example`; Atlas never
writes them into tracked source. Selecting a hosted preset records explicit
egress approval. A manually entered remote `--endpoint` is blocked until
`ATLAS_ALLOW_REMOTE=1` is set.

Every call appends a redacted line to `data/egress.jsonl`: destination host,
provider, model, message role counts and character counts, tool names, and
flags for local paths / URLs / emails / memory markers. Message contents are
not stored. Inspect it with `atlas models --egress`, or preview a payload
before sending with `atlas models --dry-run "question"`.

## Your own tools

```bash
atlas tools custom-init       # writes data/custom_tools.json with an example
atlas tools custom-list       # validate and list definitions
```

Each entry is a small JSON record:

```json
{
  "name": "echo_args",
  "kind": "echo",
  "description": "Return the arguments I pass",
  "args": {"text": {"type": "string"}},
  "required": ["text"]
}
```

Kinds:

- `echo` — returns its arguments; safest way to test a schema.
- `command` — runs a **fixed** allowlisted read-only command (`git`, `ls`,
  `pwd`, `cat`, `tree`, `echo`) with `{arg}` placeholders; no shell chaining.
- `http` — GETs a **fixed** public URL with query parameters, checked by the
  SSRF guard; requires approval because data leaves the machine.

Custom tools are registered through the same registry, so the CLI, API, GUI
and model tool list all see them. Their calls are recorded in the egress ledger
when they make an HTTP request.

## Tests

```bash
uv run python -m unittest discover -s tests -v
```

`tests/test_tools.py` covers SSRF rejection (including DNS rebinding), body
caps, result sanitisation, workspace confinement, symlink and secret refusal,
and tool dispatch. No test needs network access.
