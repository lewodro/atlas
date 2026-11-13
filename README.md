<<<<<<< HEAD
# Atlas

**A local AI mentor that actually remembers you — running on your own laptop, no account, no cloud, $0/month.**

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)]()
[![Local](https://img.shields.io/badge/runs-100%25%20local-brightgreen)]()
[![License](https://img.shields.io/badge/license-MIT-black)]()

```
you> I'm a first-year CS student, 8 GB M1, learning Python and C.
     · noted -> notes/the-user-is-learning-python-and-c.md

you> /quit
$ atlas
you> what do you know about me?

atlas> First-year CS student on an 8 GB M1, learning Python and C.
       You prefer short answers. You own a Windows laptop with a 2060.
```

Every other assistant forgets you when the tab closes. Atlas writes to plain
Markdown files, retrieves the relevant ones next time, and never sends them
anywhere.

---

## Demo

<!-- Record it: see docs/README.md, then uncomment.
![Atlas demo](docs/media/demo.gif)
-->

```console
$ atlas
atlas · life + habits + focus. Keeps you honest.
      · qwen2.5:7b on remote GPU @ http://192.168.1.42:11434/v1 · 18 notes

[coach]> I'm behind on my C assignment and I keep avoiding it.

atlas> What's the first 10 minutes of it look like — not the whole
       assignment, just the part you're avoiding.

[coach]> probably just setting up the toolchain again

atlas> Then that's today's task. Setup only. Nothing else.
       You avoided it because it's boring, not because it's hard.

[coach]> /quit
```

Two diagrams and the design reasoning: **[docs/architecture.md](docs/architecture.md)**.

---

## Why another AI assistant?

Because the interesting problem isn't the model. It's **memory you can trust.**

| | Atlas | Hosted assistants |
|---|---|---|
| Cost | $0 forever | subscription / per-token |
| Offline | yes | no |
| Your memory | files in `notes/` you can edit and delete | vendor's database |
| Who can read it | you | the vendor |
| Behaviour changes when | *you* edit the code | *they* ship an update |
| Model quality | 3B–7B local | frontier |

Atlas is not smarter than Claude. It's **yours** — and it can't be repriced,
shut down, or trained on your data.

---

## Features

- **Persistent memory** in plain Markdown. One fact per file. Delete a wrong
  one with `rm`.
- **Two-pass memory writes.** A chat call plus a cheap JSON "librarian" pass,
  because small models only call tools correctly ~50% of the time.
- **Three guards against invented memories.** No guesses, no meta-facts, no
  ungrounded notes. This is the part most personal-AI projects get wrong.
- **Semantic recall** via `nomic-embed-text`, with keyword fallback that works
  on a plane.
- **Five modes**: `coach`, `tutor`, `review`, `debug`, `plan`.
- **Activity awareness**: reads your `git log` and edited files. No screenshots,
  no keylogger, no cloud.
- **Runs on 8 GB of RAM.** Or offload the model to a gaming laptop over Wi-Fi.
- **~1,000 lines of Python.** No frameworks. You can read all of it.

---

## Quickstart

```bash
git clone https://github.com/YOU/atlas && cd atlas
./install.sh          # uv + ollama + model + seed + verify (~5 min)
atlas                 # talk to it
```

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), and
[Ollama](https://ollama.com) — or let the installer fetch a portable copy:

```bash
./install.sh --vendored    # no Homebrew, everything inside ./vendor
```

Verify:

```bash
uv run python check.py        # 7 checks
uv run python eval/run_eval.py  # 5/5 = memory works
```

---

## Web UI

Same harness, same memory, saved sessions. Browser optional.

```bash
uv run python server.py     # http://localhost:7777
atlas web                   # starts the server and opens it
```

<!-- ![web](docs/media/web.png) -->

One stdlib HTTP server, one HTML file, vanilla JS, no build step. Streams
tokens over SSE, keeps every chat in SQLite, shows notes/chats/turns in the
sidebar.

`⌘K` new chat · `↵` send · `⇧↵` newline · `esc` stop · double-click a title
to rename.

---

## How memory works

```
your message
   ├─▶ chat(messages, tools)      answers you; may call remember()
   └─▶ librarian(message)         JSON: "what is durable here?"   (guaranteed)
             │
             ▼  3 guards: stated · not meta · grounded in your words
        notes/*.md  ← human-readable, editable, one fact each
             │
             ▼  consolidate.py (nightly)
        notes/_digest.md  ← compressed, always in context
```

Why two calls? A 3B model calls tools reliably about half the time. If memory
depended on it *choosing* to save something, facts would vanish silently.

Why guards? Without them a small model writes *"the user wants to learn about
pointers"* into permanent memory — and then believes it forever.

Generated files start with `_` and are excluded from recall. **Inference never
becomes memory.**

---

## Modes

| Mode | Use it when |
|---|---|
| `coach` | you need to be honest about how the week went |
| `tutor` | learning something and want to be quizzed, not lectured at |
| `review` | Sunday: what the commits say vs. what you say |
| `debug` | stuck; hypotheses before fixes |
| `plan` | the week has no shape |

```
atlas tutor          # switch hat
/mode debug          # or mid-conversation
/frontier            # optional: send just this question to a paid model
```

---

## Use a GPU on your LAN (optional)

Better answers, same memory:

```powershell
# Windows laptop with an RTX 2060
.\install.ps1        # portable ollama, LAN bind, firewall, model
```

It prints one line for the client's `.env`:

```ini
ATLAS_BASE_URL=http://192.168.1.42:11434/v1
ATLAS_MODEL=qwen2.5:7b
```

Mac stays the brain, GPU becomes the muscle. Laptop asleep? Falls back to the
local 3B.

---

## Six-month program

`training/` contains a 26-week plan for turning the vault into a model of you:
daily prompts, weekly reviews, prediction scoring, and a 20-question eval.
No fine-tuning — just better memory.

Start with [`training/README.md`](training/README.md).

---

## FAQ

**Does it send my data anywhere?** Not by default. Ollama is local, memory is
local. Only if you configure a frontier provider.

**Will it run on 8 GB?** Yes — that's the target machine. A 3B model plus
embeddings fits comfortably.

**Is this a fine-tune?** No. Memory, not weights. That's why swapping models
doesn't lose your history.

**Why not LangChain?** You can't debug a harness you didn't write.

**Is it production-ready?** No. It's a single-user tool that you maintain.
That's the trade for owning it.

---

## Privacy

`notes/` and `data/` are gitignored. **This repo ships code, not memories.**
If you fork it, keep your vault private.

## License

MIT. Take it, change it, ship it.
=======
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
$ brain                          # <- restart. this is the whole point
you> what do you know about me?

$ brain reflect                  # optional: what patterns does it see?
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
├── reflect.py      looks at your notes for patterns -> _reflection.md.
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

`brain` is installed at `~/.local/bin/brain`, which is already on your PATH:

```bash
brain                     # chat
brain "what do you know about me?"   # one-shot, no loop
brain check               # doctor
brain notes               # how much do I remember?
brain search python       # search notes from the shell
brain sleep               # compress notes -> notes/_digest.md
brain reflect             # find patterns -> notes/_reflection.md
brain show                # print the reflection
brain eval                # score retrieval
brain seed                # add starter notes
```

The raw equivalents, if you'd rather see what's happening:

```bash
cd ~/dev/brain
uv run python main.py [--once "..."]
uv run python check.py
uv run python memory.py --stats
uv run python memory.py <query>
uv run python librarian.py "..."     # what would it remember from this?
uv run python consolidate.py [--dry-run]
uv run python reflect.py [--show]
uv run python eval/run_eval.py
```

Inside the chat: `/notes`, `/stats`, `/quit`.

### Generated files are walled off

`notes/_digest.md` and `notes/_reflection.md` start with `_` and are
**excluded from recall**. The digest is a compression of your facts, the
reflection is the model guessing about your personality. Neither is allowed
to masquerade as something you said. That separation is the whole reason
`reflect.py` is safe to run.

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

**d) Let it sleep on its own.** Add a `launchd` job (macOS cron) that runs
`brain sleep` and `brain reflect` at 3am. Then your brain consolidates while
you're asleep, which is when the metaphor earns its keep:

```bash
# ~/Library/LaunchAgents/com.miro.brain.plist  ->  run brain sleep + brain reflect
```

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
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
