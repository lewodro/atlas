# docs

| File | What |
|---|---|
| `architecture.md` | the two diagrams, explained |
| `architecture.svg` | client ↔ GPU box |
| `memory.svg` | the two-pass write path + guards |

## Recording the demo GIF

A 15-second recording beats any paragraph. GitHub renders `.gif` and `.mp4`
directly; keep it under 5 MB.

**Option A — asciinema (text, tiny, no editing):**

```bash
brew install asciinema
asciinema rec docs/media/demo.cast
#   atlas
#   I'm a first-year CS student learning Python and C.
#   /quit
#   atlas
#   what do you know about me?
#   /quit
# Ctrl-D to stop
agg docs/media/demo.cast docs/media/demo.gif
```

**Option B — screen recording:**

- macOS: `Cmd+Shift+5` → record selection → stop → `ffmpeg -i in.mov -vf
  "fps=12,scale=900:-1" docs/media/demo.gif`
- Keep the terminal at ~100×30, font ≥ 14pt, dark theme.

**Then** uncomment the two lines in the root `README.md` under `## Demo`:

```markdown
![demo](docs/media/demo.gif)
```

Tips that make it watchable:

1. Don't record the install. Record the *payoff*: the second session
   remembering you.
2. Type fast or paste; nobody watches keystrokes.
3. Cut every pause where a model loads.
4. End on the answer, not on a prompt.
