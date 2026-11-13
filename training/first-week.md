# Week 1 — what you actually do, day by day

A concrete first week. Total: ~15 minutes a day, 25 on Sunday. Don't add more
— the habit is the point.

Run `atlas` from any terminal. Everything below lives in `~/devAI/atlas`.

---

## Monday — baseline (15 min)

```bash
atlas
```

Paste this, one line at a time — it's the foundation every later question
depends on:

> I'm 19, first-year CS. I'm learning Python and C. I have an 8 GB M1 MacBook
> and a Windows laptop with an RTX 2060. My projects live in ~/devAI. I study
> best in the morning. I prefer short, direct answers.

```
/quit
atlas
what do you know about me?
```

**Saved:** ~6 notes. **Success:** the second session answers without you
repeating yourself.

---

## Tuesday — constraints (10 min)

```bash
atlas plan
```

> Make me a study plan for tomorrow assuming I only have 2 usable hours, not 6.

Then answer honestly:

> What actually limits me right now: time, money, energy, or skill?

**Saved:** 2–3 constraint notes. These are what stop the model scheduling
fantasy weeks.

---

## Wednesday — learning (15 min)

```bash
atlas tutor
```

> I'm stuck on [topic from class today]. Check what I already know first,
> then teach me from there. Quiz me after.

Answer its questions out loud. When it explains something you already knew:

> I already know that. Remember it so you stop explaining it.

**Saved:** what you know and don't. **Success:** it stops re-teaching basics.

---

## Thursday — debug (15 min)

Open a real bug. Then:

```bash
atlas debug
```

> Here's the error: [paste]. Here's the smallest input that fails: [paste].
> What's your hypothesis, and how do I falsify it in under a minute?

Don't ask for the fix. Ask for the hypothesis.

**Saved:** the misunderstanding, not the bug. ("I thought `==` compared
values of arrays" is a better note than "fixed IndexError.")

---

## Friday — evidence (10 min)

```bash
atlas review
```

> How was my week? Use my commits and files, and separate what you observed
> from what you inferred.

Then, grudgingly:

> What did I avoid this week?

**Saved:** 2–3 observations. **Success:** at least one thing you didn't
already know about your own week.

---

## Saturday — build (0 min, on purpose)

No Atlas. Use the day to actually build something. This is the only day the
tool is closed — otherwise you're studying the tool instead of the subject.

---

## Sunday — review (25 min)

```bash
atlas review
atlas sleep      # compress notes -> _digest.md
atlas eval       # score: 5/5 now, more later
```

Copy the weekly template and fill it:

```bash
cp training/weekly-review.md notes/$(date +%Y-%m-%d)-review.md
```

Answer the five questions. Add next week's three items. Then one prediction:

> Predict what I'll work on, what I'll avoid, and what will slip next week.

Write the prediction down in the review file. Next Sunday you'll score it.

---

## What the week should leave behind

| | Target |
|---|---|
| Notes | ~15–20 |
| Turns logged | 30–50 |
| `atlas eval` | 5/5, with 15 pending questions visible |
| Wrong notes deleted | at least one (you'll find a bad one) |
| Habits formed | 1 |

---

## The failure modes (all normal)

| What happens | What to do |
|---|---|
| You miss Tuesday | Thursday still works. Memory is cumulative. |
| It saves something stupid | `rm notes/<file>` — simpler than fixing a prompt |
| You write long diary entries | Stop. One fact, one line. |
| You talk to it instead of studying | Close it. It's a mirror, not the work. |
| Week 2 feels repetitive | That's the point. Repetition is what makes it know you. |

---

## After week 1

Open [`half-year.md`](half-year.md) and start phase 1 properly. You already
did most of week 1 today.
