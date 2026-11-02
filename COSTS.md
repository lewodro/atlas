# Costs: the "always-on cheap model + Claude second brain" idea

You proposed running a low-cost model (DeepSeek) constantly as a harness, plus
a separate second brain in Claude. Half of that is a very good idea. The other
half will quietly cost you more and make you dumber. Here's the split.

---

## 1. "Constant" is doing the wrong work

An LLM does nothing while idle. A constant harness means one of two things:

**a) A daemon that polls.** Calls the model every N minutes to see if anything
happened. This burns money to generate the sentence "nothing to report."

**b) A daemon that waits.** Zero cost while idle, wakes on an event: a file
saved, a git commit, a message from you, a scheduled 3am job.

You want (b). Atlas is already event-driven: the model runs when you type,
when you commit-and-ask, and once at night. Idle cost is exactly zero.

### The arithmetic that decides everything

```
monthly cost ≈ (calls/day) × (tokens/call) × 30 × price/token
```

Illustrative, not current — check the provider's pricing page before trusting
any number:

| Setup | Calls/day | Tokens each | Monthly at ~$0.3/M in, $1/M out |
|---|---|---|---|
| Chat when you want it | 40 | 3k | **under $1** |
| Poll every 5 min, 8h/day | 96 | 3k | ~$3 |
| Poll every 60s, 24/7 | 1440 | 3k | ~$40 |
| "Ambient" agent w/ tools + retries | 1440 | 12k | **$150+** |

The jump from $1 to $40 is not intelligence. It's idleness being billed.

---

## 2. The two-brain trap

"One brain in Atlas, one brain in Claude" sounds like redundancy. In practice
it becomes **two half-memories that disagree**, and you stop trusting either.

This is the failure mode:

```
Atlas knows:  you're learning C, you own a 2060, you sleep at 2am
Claude knows:  you're learning Python, you want to build a startup
You:           "what should I study tonight?"
               -> two different answers, both confident, one wrong
```

Memory is the product. Models are interchangeable. So:

> **One memory store. Many readers. Never two stores.**

---

## 3. The architecture that actually works

```
                    ~/dev/atlas/notes/*.md   ← the single source of truth
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   local model           frontier model        Claude / ChatGPT
   (free, always)        (per-question)        (deep dives, uploads)
        │                     │                     │
   journaling,           hard debugging,       architecture reviews,
   summaries,            exam-level tutoring,  career thinking,
   daily review          anything you'd pay    anything long-form
                         attention to
```

Routing rule, in one line: **routine → local, thinking → frontier.**

Atlas implements this with two tiers:

```bash
# .env  (optional second tier)
ATLAS_FRONTIER_BASE_URL=https://api.deepseek.com/v1
ATLAS_FRONTIER_API_KEY=sk-...
ATLAS_FRONTIER_MODEL=deepseek-chat
```

Then inside the chat:

```
/frontier          toggle: this question uses the paid model
/mode tutor        ...and the tutor prompt
```

Everything else — memory writes, activity scans, consolidation — stays local
and free. You pay for exactly the turns where quality matters.

### Why DeepSeek for the cheap tier

It is cheap, fast, and good enough for summarising commits and asking you one
question about your day. But note the irony: **if the model is cloud, the
"constant" part is now a bill and a network dependency.** A local 3B model on
your Mac is genuinely $0 and works on a train. For the routine tier, local
wins on both counts.

Use the cloud tier for what it's actually better at: long context, hard
reasoning, code you'll ship.

### Where Claude fits

Claude is a *reader*, not a second brain. Concretely:

1. `atlas sleep` compresses your notes into `notes/_digest.md`.
2. `atlas export` (see below) dumps the vault to one Markdown file.
3. Upload that file to a Claude Project, or ask Claude about it directly.
4. Whatever you learn there, **write back into `notes/`** — by hand, or by
   asking Atlas to `remember`.

Claude gets a snapshot. Atlas keeps the source of truth. When they disagree,
`notes/` wins, because it's the only thing that survives every model change.

One-liner to add later:

```bash
# concatenate the vault for upload
cat notes/*.md | pbcopy
```

---

## 4. What "constant" should mean for you

| Want | Build | Cost |
|---|---|---|
| A mentor available instantly | Atlas open in a terminal tab | $0 |
| It notices what you did | `atlas today` when you sit down | $0 |
| It remembers you | `notes/` + nightly `atlas sleep` | $0 |
| A second opinion on hard problems | `/frontier` or Claude, deliberately | cents |
| It watches you all day | **don't** | money + anxiety |

If you ever do want a genuine daemon, make it *cheap and dumb*: a 15-minute
`launchd` job that runs `atlas scan` (git + file timestamps, no model) and
appends to `data/activity.jsonl`. Then the model reads that timeline only when
you ask. Observation is free; interpretation is billed.

---

## 5. The rule to remember

> Spend tokens on thinking, not on waiting. Keep one memory, and let models
> come and go.
