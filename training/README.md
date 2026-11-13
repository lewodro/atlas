# The six-month program

Goal: by month six, a fresh conversation with Atlas can answer 20 questions
about you, correctly, without you repeating yourself.

This is **not** fine-tuning. No weights change. "Training" here means building
a memory that is accurate, retrievable, and honest — which is the only kind
that survives a model swap.

- Start here: [`first-week.md`](first-week.md) — day by day
- The plan: [`half-year.md`](half-year.md)
- The scoreboard: [`questions.json`](questions.json) (used by `atlas eval`)
- The weekly ritual: [`weekly-review.md`](weekly-review.md)

---

## The daily loop (5 minutes)

```bash
atlas plan            # 3 items for today, from real constraints
# ...live your day...
atlas                 # 3 lines: what happened, what surprised you, what's next
atlas sleep           # once a week is enough
```

Three lines is the whole habit. If you write more, you'll stop by week two.

---

## The weekly loop (20 minutes, Sunday)

```bash
atlas review          # reads your commits + files, not your intentions
atlas sleep           # compress notes -> _digest.md
atlas eval            # score: how well does it still know you?
```

Then open `weekly-review.md`, answer the five questions, and record the
prediction score.

---

## What "knows me best" is measured by

| Metric | How | Target by week 26 |
|---|---|---|
| Recall | `atlas eval` pass rate | 90%+ |
| Density | facts per note | 1 fact, no essays |
| Freshness | notes confirmed in last 90 days | 80%+ |
| Prediction | weekly predictions that came true | 60%+ |
| Stranger test | new chat answers 20/20 | pass |

The stranger test is the only one that matters. Everything else is a proxy.

---

## Rules that keep it from rotting

1. **One fact per note.** "I'm tired and my C assignment is due" is two notes
   and one of them is garbage.
2. **Never store a guess as a fact.** The librarian filters most of it; you
   are the second filter.
3. **Delete monthly.** A wrong note is worse than no note, because it is
   retrieved with confidence.
4. **No journaling your feelings into the vault.** Feelings belong in the chat;
   the vault holds what stays true.
5. **When it's wrong, fix the note — not the prompt.** Prompt patches hide
   bad memory; they don't fix it.
