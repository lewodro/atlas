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

## Recent research

`recent_research` runs several dated queries in parallel, fetches the top
pages and returns a digest with real URLs. Categories: `finance`, `news`,
`gaming`, `ai`, `general`. Default window is 60 days; results are cached for
six hours in gitignored `data/research.json`.

```bash
atlas research "stock market" --category finance --days 60
atlas research "game releases" --category gaming
atlas research "AI models" --category ai --json
```

The `recent-events` skill teaches the agent to use this tool, answer briefly,
name sources and never invent headlines. Every URL is re-checked against the
SSRF guard before it enters the digest.

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

## GitHub (read-only)

Uses the installed `gh` CLI and an allowlist in `data/github.json` (defaults
to `lewodro/atlas`). No writes, no shell, fixed GET requests.

```bash
atlas github issues --limit 5
atlas github prs --limit 5
atlas github repo
```

## Code execution

Runs Python in a restricted subprocess: `-I -S`, an audit hook that blocks
network imports and outside-file access, CPU/file-size limits, a 12s timeout
and capped output. Writes inside the workspace only. Permission: ASK.

```bash
printf 'print(6*7)' | atlas code
```

## Images

SVG images are generated locally and deterministically from a prompt, with
simple edits (background, caption, scale). They are registered as artifacts
and previewable in the GUI. Permission: ASK for writes.

```bash
atlas image generate "teal hills" --path images/hills.svg
atlas image edit images/hills.svg --caption "edited locally"
```

## External providers

A provider is a local HTTP service with `/invoke`. Its manifest lists tool ids
and JSON schemas. Registered tools join the same registry and need no core
changes. Permission defaults to ASK.

```json
{
  "name": "Local tools",
  "base_url": "http://127.0.0.1:9999",
  "tools": [
    {"id": "ping", "description": "Ping the local service", "parameters": {"type": "object", "properties": {}}}
  ]
}
```

```bash
atlas providers register local-tools ./provider.json
atlas providers list
```

Last Seat MCP is intentionally not included; it is a separate project.

## Status and configuration

```bash
atlas tools          # list tools and status
atlas tools status   # one JSON object per tool
atlas tools configure --workspace PATH
```

The GUI Tools page shows the same status and lets you set the workspace without
leaving the browser.

## Tests

```bash
uv run python -m unittest discover -s tests -v
```

`tests/test_tools.py` covers SSRF rejection (including DNS rebinding), body
caps, result sanitisation, workspace confinement, symlink and secret refusal,
and tool dispatch. No test needs network access.
