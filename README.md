# brain — a harness with a memory

A ~500-line Python "second brain". No frameworks, no magic, every line
readable. Built so you learn by *changing* it, not by configuring it.

---

## 1. What is already installed

| Thing | Where | Why |
|---|---|---|
| Python 3.13 | system | the language |
| `uv` | `/opt/homebrew/bin/uv` | runs the project, manages deps |
| Ollama 0.40 | `brew services` (starts at login) | runs the model locally — free, private |
| `qwen2.5:3b` | `~/.ollama/models` | the model (1.9 GB), fits an 8 GB M1 |
| This project | `~/dev/brain` | the harness |

No API key. No cost. Nothing leaves your Mac.

---

## 2. Tomorrow morning, in this order (≈10 minutes)

```bash
cd ~/dev/brain
uv run python check.py            # 1. six green lines (one "warn" is fine)
uv run python seed.py             # 2. five starter notes
uv run python eval/run_eval.py    # 3. expect: 3/3 passed
uv run python main.py             # 4. start talking
```

Then type these three things, in order:

```
you> I'm learning Python and I use VS Code.
     ^ watch the "· noted -> notes/..." line: it just wrote a file

you> /quit
$ uv run python main.py          # <- restart. this is the whole point
you> what do you know about me?
```

If the second session answers from memory, the harness works. That is the
entire milestone. Everything else is refinement.

**Then prove it's real:** open a file in `notes/`, edit it by hand, restart,
and ask about it. Memory is just Markdown. That's the trick, and it's why
you can always fix a wrong memory with a text editor.

---

## 3. The map

```
brain/
├── main.py         the harness: the while-loop. READ THIS FIRST.
├── llm.py          ~35 lines. the only file that talks to a model.
├── memory.py       SQLite log + notes/ vault + keyword search + dedupe.
├── librarian.py    second small call: "what here is worth remembering?"
├── consolidate.py  the "sleep" job: compresses notes into _digest.md.
├── check.py        doctor. run it whenever something feels broken.
├── seed.py         starter notes.
├── notes/          YOUR BRAIN. open with any text editor.
├── brain.db        every turn ever, one table.
└── eval/           questions + the script that scores your memory.
```

Read order: `llm.py` → `memory.py` → `main.py` → `librarian.py` →
`consolidate.py`. About an hour, and you'll understand every moving part.

---

## 4. Why there are *two* model calls

This is the one design decision worth understanding, because it teaches the
most important lesson in agent-building.

```
user message
     │
     ├──▶ chat(messages, tools)   ← answers you, may call remember()
     │
     └──▶ librarian(message)      ← JSON: "what is durable here?"
              │
              ▼
          notes/*.md  (deduped, grounded, filtered)
```

A 3B model calls tools correctly only about half the time. If memory depended
on it *choosing* to call `remember()`, you'd silently lose facts and never
know why. So the harness keeps tools (they're the lesson, and they work
when the model is in the mood) and adds a guaranteed second pass.

Three guards sit between the model and your vault, in `librarian.plausible()`:

1. a fact must be *stated* ("The user…", "I…"), not an instruction;
2. it must not describe the conversation or infer a motive;
3. it must share a real word with what you actually typed.

Without those, a small model will happily write "The user wants to know how
to create a virtual environment" into your permanent memory. That is the
single most common way personal AI systems rot.

---

## 5. How memory actually works here

```
         every message
              │
              ▼
      ┌───────────────┐        ┌──────────────────┐
      │  brain.db     │        │  notes/*.md      │
      │  raw history  │        │  one fact / file │
      └───────────────┘        └────────┬─────────┘
                                        │ consolidate.py
                                        ▼
                               notes/_digest.md
                                        │
   new message ──▶ recall() ──┬─────────┘
                    │         │
                    ▼         ▼
              ┌──────────────────────┐
              │   SYSTEM PROMPT      │  <- "the brain" at runtime
              └──────────┬───────────┘
                         ▼
                     the model
```

Three facts worth memorizing:

1. **The model never learns.** Close the app and the weights are unchanged.
   All continuity is what your code puts in the prompt.
2. **Context is a desk, not a cabinet.** Anything not on disk is gone.
3. **Bad memory is worse than none.** A wrong note, confidently retrieved,
   is the main failure mode. Hence: plain files, visible writes, cheap guards.

`recall()` is keyword matching (Jaccard-ish, no dependencies). When the vault
is small it falls back to your three newest notes so "what do you know about
me?" still works. Delete that fallback once you pass ~50 notes.

---

## 6. Commands

```bash
uv run python main.py              # chat (loads the last 20 turns)
uv run python main.py --once "hi"  # one-shot, no loop

uv run python check.py             # is everything alive?
uv run python memory.py --stats    # how much do I remember?
uv run python memory.py python     # search notes from the shell
uv run python librarian.py "..."   # what would it remember from this?
uv run python consolidate.py       # compress notes -> notes/_digest.md
uv run python consolidate.py --dry-run
uv run python seed.py              # add starter notes
uv run python eval/run_eval.py     # score retrieval (fast, no model call)
```

Inside the chat: `/notes`, `/stats`, `/quit`.

---

## 7. Upgrading — in the order it's actually worth doing

**a) A cloud model** (fastest quality jump, needs a key):

```bash
export OPENAI_API_KEY=sk-...
BRAIN_PROVIDER=openai uv run python main.py
```

**b) A bigger local model.** You have 8 GB of RAM, so stay ≤4B:

```bash
ollama pull qwen3:4b
BRAIN_MODEL=qwen3:4b uv run python main.py
```

Expect a slower first token and noticeably better tool calling. If it swaps
and crawls, you went too big — that's a hardware limit, not a bug.

**c) Semantic search.** Only `recall()` changes: embed notes, store vectors
in numpy, rank by cosine similarity. Same signature, so `eval/run_eval.py`
tells you whether it actually helped. Add an eval question *first*.

**d) Reflection.** `reflect.py`: "what patterns do you see in these notes?",
written back as a note. Fun, and it shows where self-referential memory
gets weird.

**e) Fine-tuning.** Skip it. It teaches *style*, not *knowledge*, needs
hundreds of clean examples, and goes stale immediately. Retrieval wins.

---

## 8. When it breaks

| Symptom | Cause | Fix |
|---|---|---|
| `Connection refused` | Ollama not running | `brew services start ollama` |
| `model not found` | not pulled | `ollama pull qwen2.5:3b` |
| "Already known" loop, then no answer | 3B model tool-spamming | harness caps it at 2 rounds; it will still answer |
| Replies are slow | first token after idle | ~5–10 s once, then fast |
| It "forgot" | never written to `notes/` | `uv run python memory.py --stats` |
| It remembers something wrong | a bad note | edit/delete the file in `notes/` |
| It saved something silly | guards too loose | tighten `librarian.plausible()` |

When in doubt: `uv run python check.py`, which tells you *which layer* broke
— python, venv, storage, model, tools, or extraction.

---

## 9. Privacy

`notes/` and `brain.db` are your life in plain text. They never leave the
machine unless you set `BRAIN_PROVIDER=openai`, which sends retrieved notes
to OpenAI. Local Ollama means nothing ever leaves. If you push this to git,
keep the repo private — `brain.db` is ignored, `notes/` is not.
