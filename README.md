# brain — a harness with a memory

A ~400-line Python "second brain". No frameworks, no magic, every line
readable. Built so you can learn by *changing* it, not by configuring it.

---

## 1. What is already installed

| Thing | Where | Why |
|---|---|---|
| Python 3.13 | system | the language |
| `uv` | `/opt/homebrew/bin/uv` | runs the project, manages deps |
| Ollama 0.40 | `brew services` (always on) | runs the model locally, free, private |
| `qwen2.5:3b` | `~/.ollama/models` | the model — small and fast, supports tool calls |
| This project | `~/dev/brain` | the harness |

Nothing needs an API key. Nothing costs money. Everything runs on your Mac.

---

## 2. Tomorrow morning, in this order (≈10 minutes)

```bash
cd ~/dev/brain
uv run python check.py      # 1. all six lines should be green
uv run python seed.py       # 2. puts 5 starter notes in the vault
uv run python eval/run_eval.py   # 3. should print 3/3 passed
uv run python main.py       # 4. start talking
```

Then type these, in this order — they teach you what the thing does:

```
you> I'm learning Python. I build with VS Code and I hate long answers.
      ^ watch for the "· remember -> ..." line: it just wrote a file
you> /quit

you> uv run python main.py      # ← restart it. this is the whole point
you> what do you know about me?
```

If the second session answers from memory, the harness works. That's the
entire milestone.

---

## 3. The map

```
brain/
├── main.py         the harness: the while-loop. READ THIS FIRST.
├── llm.py          ~30 lines. the only file that talks to a model.
├── memory.py       SQLite log + the notes/ vault + keyword search.
├── consolidate.py  the "sleep" job: compresses notes into _digest.md.
├── check.py        doctor. run it whenever something feels broken.
├── seed.py         starter notes.
├── notes/          YOUR BRAIN. open these in any text editor.
├── brain.db        every turn ever, in one table. delete it anytime.
└── eval/           questions + the script that scores your memory.
```

Read order for learning: `llm.py` → `memory.py` → `main.py` → `consolidate.py`.
One hour total, and you'll understand every moving part.

**Try this to feel it:** open `notes/`, edit a note by hand, restart, and ask
about it. Memory is just files. That's the trick.

---

## 4. Week 1 — one small change per day

Don't rewrite. Make one edit, run it, see what happens.

| Day | Task | File | What you learn |
|---|---|---|---|
| 1 | Run it. Break it. Fix it. | — | the loop |
| 2 | Add a `forget(text)` tool that deletes a note | `main.py`, `memory.py` | tools, file IO |
| 3 | Add a 5th item to `eval/questions.json` that *fails*, then fix `recall()` until it passes | `memory.py` | test-driven memory |
| 4 | Change `SYSTEM` to give it a different personality | `main.py` | prompting |
| 5 | Run `consolidate.py`, read `notes/_digest.md`, decide if it's accurate | — | why summaries drift |
| 6 | Swap `recall()` for embeddings (see §7) | `memory.py` | semantic search |
| 7 | Add `/export` that dumps the conversation to Markdown | `main.py` | sqlite queries |

---

## 5. How memory actually works here

```
         every message
              │
              ▼
      ┌───────────────┐        ┌──────────────────┐
      │  brain.db     │◀──────▶│  notes/*.md      │
      │  raw history  │        │  one fact / file │
      └───────────────┘        └────────┬─────────┘
                                        │ nightly
                                        ▼
                               notes/_digest.md
                                        │
   new message ──▶ recall() ──┬─────────┘
                    │         │
                    ▼         ▼
              ┌──────────────────────┐
              │   SYSTEM PROMPT      │  <- this is "the brain" at runtime
              └──────────┬───────────┘
                         ▼
                     the model
```

Three facts worth memorizing:

1. **The model never learns.** Close the app and the model is unchanged.
   All continuity comes from what your code puts in the prompt.
2. **Context is a desk, not a cabinet.** Anything not on disk is gone.
3. **Bad memory is worse than none.** A wrong note confidently retrieved
   is the main failure mode. That's why you can read and edit every note.

---

## 6. Commands

```bash
uv run python main.py              # chat (memory loads automatically)
uv run python main.py --once "hi"  # one-shot, no interactive loop

uv run python check.py             # is everything alive?
uv run python memory.py --stats    # how much do I remember?
uv run python memory.py python     # search notes from the shell
uv run python consolidate.py       # compress notes -> _digest.md
uv run python consolidate.py --dry-run
uv run python seed.py              # add starter notes (idempotent-ish)
uv run python eval/run_eval.py     # score retrieval
```

Inside the chat: `/notes`, `/stats`, `/quit`.

---

## 7. Upgrading — in the order it's actually worth doing

**a) Better model.** Bigger is slower but smarter on your Mac:

```bash
ollama pull qwen3:8b
BRAIN_MODEL=qwen3:8b uv run python main.py
```

**b) A cloud model** (needs a key):

```bash
export OPENAI_API_KEY=sk-...
BRAIN_PROVIDER=openai uv run python main.py
```

**c) Semantic search** instead of keyword matching. Only `recall()` changes:
embed each note with `openai.embeddings` (or `ollama`'s `/api/embeddings`),
store the vectors in a numpy array, and rank by cosine similarity. Keep
`recall()`'s signature identical and `eval/run_eval.py` will tell you
whether it actually helped.

**d) Reflection.** A `reflect.py` that asks the model "what patterns do you
notice in these notes?" and writes the answer back as a note. Cute, and it
shows you where self-referential memory gets weird.

**e) Fine-tuning.** Skip it. It teaches *style*, not *knowledge*, needs
hundreds of examples, and goes stale the moment your life changes. RAG
gets you further for a fraction of the work.

---

## 8. When it breaks

| Symptom | Cause | Fix |
|---|---|---|
| `Connection refused` | Ollama not running | `brew services start ollama` |
| `model not found` | not pulled | `ollama pull qwen2.5:3b` |
| Model answers but never calls tools | small model being lazy | try `qwen3:8b`, or ask more explicitly |
| Replies are slow | 3b on a cold start | first token takes ~10s; later ones are fast |
| It "forgot" | not in `notes/` | check `uv run python memory.py --stats` |
| It remembers something wrong | a bad note | edit/delete the file in `notes/` |

When in doubt: `uv run python check.py`. It tells you which layer is broken.

---

## 9. Privacy

`notes/` and `brain.db` are your life in plain text. They never leave this
machine unless you set `BRAIN_PROVIDER=openai`, which sends the retrieved
notes to OpenAI. Local Ollama means nothing ever leaves. Commit the notes
to git if you want history; keep the repo private.
