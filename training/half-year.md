# Half a year with Atlas

26 weeks. Six phases. Each week has one focus, a few prompts worth answering,
and a memory target. Miss a week — don't restart, just continue where the
memory actually is.

Use it with:

```bash
atlas tutor      # learning something
atlas            # coach: the daily 3 lines
atlas review     # Sunday evidence
atlas plan       # when the week has no shape
```

---

## Phase 1 · Weeks 1–4 — Who I am

**Focus:** identity, constraints, direction. The facts that don't change much
but everything else depends on.

| Week | Focus | Ask yourself | Memory target |
|---|---|---|---|
| 1 | Baseline | Who am I right now: age, course, city, hardware, schedule? | 15 notes |
| 2 | Constraints | What actually limits me: money, time, energy, health, obligations? | 25 |
| 3 | Direction | Why CS? What do I want in 3 years? What would make me quit? | 35 |
| 4 | Avoidance | What do I keep postponing, and what do I tell myself about it? | 45 |

Prompts that produce good notes:

- "My typical weekday, hour by hour, honestly."
- "The three things I consistently fail to do."
- "What I say I want vs. what my calendar and commits say I want."
- "What kind of help actually helps me, and what annoys me."

**Checkpoint:** `atlas eval` should pass the first 10 questions. If not, the
notes are too vague — rewrite them as single facts.

---

## Phase 2 · Weeks 5–8 — How I learn

**Focus:** the learning profile. This is what makes tutor mode useful instead
of generic.

| Week | Focus | Ask yourself | Memory target |
|---|---|---|---|
| 5 | Study method | When did I last understand something deeply, and what did I do? | 55 |
| 6 | Failure log | Every bug/assignment I got wrong: what was the misunderstanding? | 65 |
| 7 | Pace | How long do I actually sustain focus? What breaks it? | 75 |
| 8 | Explanation style | Do I need analogies, code, diagrams, or first principles? | 85 |

Prompts:

- "Explain today's topic to me like I'm 12, then like I'm a compiler."
- "Quiz me on this week's material. One question at a time."
- "What did I get wrong in this assignment, and what belief caused it?"

**Checkpoint:** tutor mode should stop explaining basics you already have.
If it still does, your notes say "beginner" and never got updated — fix that.

---

## Phase 3 · Weeks 9–13 — What I build

**Focus:** projects, decisions, and the gap between plan and commit.

| Week | Focus | Ask yourself | Memory target |
|---|---|---|---|
| 9 | Current project | Scope, stack, why, what "done" means | 95 |
| 10 | Decisions | Every non-obvious choice + the alternative I rejected | 105 |
| 11 | Time audit | Where the hours actually went vs. where I said they went | 115 |
| 12 | Abandonment | What did I drop, and was that correct? | 125 |
| 13 | Retro | What would I do differently on the same project? | 135 |

Prompts:

- "Here are my commits this week. What does the evidence say I worked on?"
- "I chose X over Y. Was that defensible given what I knew?"
- "What's the smallest version of this project that would still teach me?"

**Checkpoint:** `atlas review` should produce observations you didn't already
know. If it only repeats your commits, ask sharper questions.

---

## Phase 4 · Weeks 14–18 — How I live

**Focus:** the operating system around the studying: sleep, energy, money,
people. Keep it factual, not therapeutic.

| Week | Focus | Ask yourself | Memory target |
|---|---|---|---|
| 14 | Energy | When am I sharp? When am I useless? What predicts each? | 145 |
| 15 | Sleep | Actual bedtime distribution, not the ideal one | 155 |
| 16 | Money | Fixed costs, income, what I'm saving for | 165 |
| 17 | People | Who I learn from, who drains me, who I owe | 175 |
| 18 | Defaults | What I do when I have no plan (the honest answer) | 185 |

Prompts:

- "Plan my day assuming I have 2 usable hours, not 6."
- "I slept 5 hours. What should I not attempt today?"
- "What did I spend on this month, and was it worth it?"

**Checkpoint:** plans start working. If Atlas still schedules 6 hours of deep
work, it doesn't believe your constraints — re-save them as facts.

---

## Phase 5 · Weeks 19–22 — Prediction and correction

**Focus:** the real training signal. Ask Atlas to predict you, then score it.

Every Sunday:

1. Ask: *"Based on my notes and this week's activity, predict: what I'll work
   on, what I'll avoid, and what will slip."*
2. Save the prediction in `weekly-review.md`.
3. Next Sunday: mark each one right/wrong and write one line of why.

| Week | Prediction focus | Target accuracy |
|---|---|---|
| 19 | What I'll actually work on | 40% |
| 20 | What I'll avoid | 50% |
| 21 | What slips and why | 55% |
| 22 | All three together | 60% |

This is where a memory becomes a model of you. Being wrong is the useful part:
a wrong prediction points at a note that is stale or missing.

---

## Phase 6 · Weeks 23–26 — Consolidate

**Focus:** pruning. A brain is defined by what it refuses to remember.

| Week | Job |
|---|---|
| 23 | Read every note. Delete anything not true, not yours, or not useful. |
| 24 | Merge duplicates. `atlas sleep`, then read `_digest.md` critically. |
| 25 | Grow the eval to 20 questions. Any failure = a memory bug, fix the note. |
| 26 | Stranger test: fresh chat, no history, 20 questions, score it. |

**Final deliverable:** run

```bash
cat notes/*.md > ~/Desktop/about-me.md
```

That file is the proof. If a stranger (or a new model) can read it and
understand you, the six months worked.

---

## If you fall off

The failure mode isn't missing days — it's restarting from scratch because you
feel behind. Instead:

```bash
atlas review --hours 168   # what did the last week actually look like?
atlas plan                 # one item for today, not a redemption arc
```

Memory is cumulative. A gap is data too: *"I stopped for 11 days after week 6;
what was happening?"* is one of the most useful notes you will ever save.
