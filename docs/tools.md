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
