# Atlas

A local AI mentor that remembers you, sees what you've been working on, and
runs on hardware you already own. No account, no subscription, no cloud.

```
MacBook (or any client)                 GPU machine (optional)
atlas: harness + notes/ + memory  ───▶  ollama @ :11434
       local 3B fallback                qwen2.5:7b
```

One memory store (`notes/*.md`), any model to read it.

---

## Can someone else run it?

Yes. It's ~1,000 lines of Python, no database server, no web service, no
accounts. Requirements:

| Need | Why | Install |
|---|---|---|
| Python 3.12+ | runs the harness | `brew install python` |
| uv | deps + venv | `brew install uv` |
| Ollama | the model runtime | `brew install ollama` (or portable, below) |
| ~4 GB disk | 3B model + embeddings | — |

### macOS / Linux

```bash
git clone <repo> atlas && cd atlas
./install.sh            # uv, ollama, model, seed, verify
atlas                   # or: uv run python main.py
```

The installer is idempotent, needs no sudo, and never touches `notes/`.
For a fully portable Ollama inside the project folder (no Homebrew):

```bash
./install.sh --vendored
```

### Windows GPU box (optional)

`install.ps1` as Administrator: downloads portable Ollama into `vendor/`,
binds it to your LAN, opens the firewall for the **Private** profile only,
pulls `qwen2.5:7b`, and prints the line to paste into `.env`:

```
ATLAS_BASE_URL=http://192.168.1.42:11434/v1
```

### Verify

```bash
uv run python check.py       # 7 lines, at most one "warn"
uv run python eval/run_eval.py   # 5/5 = memory works
```

If `check.py` passes, it runs. That is the whole portability story.

---

## Why not just use a hosted assistant (Hermes et al.)?

Hosted assistants are better products. This one is a better *arrangement*.

| | Atlas | Hosted assistant |
|---|---|---|
| Cost | $0, forever | subscription or per-token |
| Works offline | yes | no |
| Your memory | files in `notes/`, editable, deletable | vendor's database |
| Who can read it | you | the vendor |
| Behaviour changes | when you edit the code | when they ship an update |
| Setup | ~10 min, once | none |
| Model quality | 3B–7B local | frontier |
| Maintenance | yours | theirs |

Honest trade-offs: a 7B model is not Claude. You will maintain it. It is not
multimodal, has no mobile app, and nobody will fix your bug.

What you get that a hosted product structurally cannot give you: memory you
can `cat`, an assistant that still works when the company is down, repriced,
or shut down, and a system whose behaviour you can read line by line.

**Note:** "Hermes" means several different things (a model family, a messaging
app, an agent product). If you meant a specific one, say which and this table
can be sharpened.

---

## Privacy

- Memory and notes never leave the machine by default.
- `activity.py` reads only `git log` and file timestamps under your projects
  folder. No screenshots, no keylogger, no shell history.
- If you set `ATLAS_BASE_URL` or a frontier key, prompts and retrieved notes
  go to that provider. Read `COSTS.md` first.
- `.env`, `data/` and `vendor/` are gitignored. **`notes/` is not** — it is
  your memory, and it is personal.

---

## Files

| | |
|---|---|
| `main.py` | the harness loop + chat commands |
| `memory.py` | notes, embeddings, keyword fallback |
| `modes.py` | coach / tutor / review / debug / plan |
| `activity.py` | what you've actually been doing |
| `librarian.py` | decides what is worth remembering |
| `COSTS.md` | why "always-on" costs more than it looks |
| `SETUP-MAC.md`, `SETUP-WINDOWS.md` | the long version |

No license file yet — add one before publishing (see `is it public?` below).
