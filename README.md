# Atlas

A local AI mentor that remembers you, sees what you're actually working on,
and runs on hardware you already own: an 8 GB M1 MacBook, or a Windows laptop
with an RTX 2060 on the same Wi-Fi.

```
MacBook (8 GB)                          Windows laptop (RTX 2060, 6 GB VRAM)
┌──────────────────────┐   Wi-Fi LAN   ┌──────────────────────────────┐
│ atlas  (harness)     │──────────────▶│ ollama serve --host 0.0.0.0  │
│ notes/  data/        │  :11434       │ qwen2.5:7b  (~30 tok/s)      │
│ 3B fallback local    │               │                              │
└──────────────────────┘                └──────────────────────────────┘
```

The harness is tiny and lives on whichever machine you're typing on. The
heavy model lives wherever the GPU is. Swapping between them is one line in
`.env` — that's the entire point of the design.

---

## What it does

| Mode | Job |
|---|---|
| `coach` | life, habits, focus. Asks what you're avoiding. |
| `tutor` | CS/engineering teacher. First principles, then a quiz. |
| `review` | reads your git commits + edited files, tells you the truth |
| `debug` | pair programmer. Hypotheses before fixes. |
| `plan` | turns goals into 3 items a tired human can do |

Plus persistent memory: facts go to `notes/*.md`, the model gets the relevant
ones back by keyword on every turn. Nothing leaves your machine.

---

## Quickstart (MacBook)

```bash
cd ~/dev/atlas
./install.sh              # uv, ollama, model, seed, verify
uv run python check.py    # six green lines
uv run python main.py
```

Or, after the installer:

```bash
ln -sf ~/dev/atlas/atlas ~/.local/bin/atlas
atlas            # chat
atlas tutor      # switch hat
atlas today      # what did I do in the last 24h
```

First session, type:

```
I'm a first-year CS student. I'm learning Python and C. I have 8 GB of RAM
and a 2060 laptop. I prefer short answers.

/quit
atlas
what do you know about me?
```

If the second session knows you, memory works.

---

## Using the GPU machine

On Windows, see **[SETUP-WINDOWS.md](SETUP-WINDOWS.md)**. Short version:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

It prints one line to paste into `.env` on the Mac:

```
ATLAS_BASE_URL=http://192.168.1.42:11434/v1
ATLAS_MODEL=qwen2.5:7b
```

On the Mac, see **[SETUP-MAC.md](SETUP-MAC.md)** for the local 3B fallback
and the launchd job that keeps the harness available.

---

## How memory works (the part worth learning)

```
user message
   ├─▶ chat(messages, tools)      answers you; may call remember()
   └─▶ librarian(message)         JSON: "what is durable here?"  (guaranteed)
             │
             ▼  3 guards
        notes/*.md   ← plain files you can read and delete
             │
             ▼  consolidate.py (nightly)
        notes/_digest.md  ← compressed, always in context
```

Why two model calls? Because a 3B model calls tools correctly about half the
time. If memory depended on it *choosing* to save something, facts would
disappear silently. The second call is cheap and constrained to JSON.

Why the guards? Without them a small model writes *"The user wants to learn
about pointers"* into permanent memory, and then believes it forever. A fact
must be **stated** ("The user…"), **not meta** (no "asked", "interested"),
and must **share a real word** with what you typed.

Generated files (`_digest.md`, `_reflection.md`) start with `_` and are
excluded from recall. Inference never becomes memory.

---

## Activity, not surveillance

`activity.py` reads exactly two things:

- `git log` in every repo under `~/dev`
- files with a code-ish extension modified in the last N hours

No screenshots, no keyloggers, no cloud, no shell history. You can run it
standalone to see exactly what the model sees:

```bash
uv run python activity.py
```

The model can also call it as a tool (`recent_activity`) in any mode, even
`tutor`.

---

## Commands

```bash
atlas                    # chat
atlas tutor              # any mode: coach tutor review debug plan
atlas "explain pointers" # one-shot
atlas today              # activity + append snapshot
atlas scan               # snapshot only
atlas notes              # how much do I remember
atlas search RAM         # search the vault
atlas sleep              # consolidate -> _digest.md
atlas eval               # retrieval score (no model needed)
atlas check              # doctor
```

Inside the chat: `/modes`, `/mode tutor`, `/today`, `/notes`, `/stats`, `/quit`.

---

## Choosing a model for your hardware

| Hardware | Fits comfortably | Model | Speed |
|---|---|---|---|
| M1, 8 GB unified | ~5 GB | `qwen2.5:3b` | 20–30 tok/s |
| RTX 2060, 6 GB VRAM | ~5.5 GB | `qwen2.5:7b` Q4 | 25–40 tok/s |
| RTX 2060, CPU offload | ~9 GB | `qwen2.5:14b` Q4 | 5–8 tok/s |

The 2060 is not a big card. A 7B at Q4 is the sweet spot; a 14B will run but
feel like dial-up. Do not chase size — a model that answers in 2 seconds you
actually use beats a better one you avoid.

---

## The "always on, cheap model" question

Running a cheap model continuously is tempting and usually a mistake. Details
in **[COSTS.md](COSTS.md)**: event-driven beats always-on, and one memory
store with two models beats two brains.

---

## Privacy

Everything is local by default. If you point `ATLAS_BASE_URL` at a cloud
provider, then whatever is in the prompt — including retrieved notes — goes
to that provider. Read the notes you've saved before you do that.
