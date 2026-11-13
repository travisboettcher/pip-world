# Design: expectations and surprise

Note (2026-11-13): since 0.42.0 the expectations a work session or an experiment settles are logged by the shipped `crafting`
module (an `event`'s `expect`); the comparison, calibration and surprise are the engine's (DESIGN-world-packs.md, "5f built").

Status: **built** (all four phases, 2026-10-30). Decisions: three-word vocabulary kept (a 1-5 scale can come later); calibration
block after 5 predictions; surprises only create a diary prompt through the first-of-each-kind firsts. Step-duration
comparisons are recorded whether or not they are surprising (only surprising ones are flagged). Sources: [RESEARCH-self.md](RESEARCH-self.md), mechanism 4 (Metacognitive Loop
note-assess-guide; AIMA belief states; Schmidhuber / Oudeyer learning progress; Ricoeur's concordance vs discordance).
Same rule as the rest of the self work: the engine records **facts** (what Pip expected, what happened, how far apart) and
creates the **occasion**; Pip decides what it means. No evaluative words, no scripted reaction.

## Why
Surprise is a mismatch between what Pip expected and what happened. It is the raw fact behind curiosity ("I keep being
wrong about brass"), turning points, and claims like "I read my own work too kindly". Today Pip never states an
expectation, so nothing can be violated. Everything below is deterministic: no extra LLM calls.

## What Pip can expect (three sources, all checkable by the engine)

| Source | How the expectation is made | What it is compared with | Error |
|---|---|---|---|
| **Work session** | optional `expect` on `work_on`: `well` / `slowly` / `badly` (omit = no prediction) | the session's verdict (blowup, setback, slow, good, breakthrough) | ordinal distance on 0-4: well=3, slowly=2, badly=1; signed (+ better than expected, - worse) |
| **Experiment** | optional `expect` on `experiment`: `works` / `partly` / `fails` | the outcome (insight/surprise = works, clue = partly, nothing = fails; an irrelevant hypothesis = fails) | signed distance on 0-2 |
| **Step duration** | implicit: Pip's own minutes guess when it wrote the step (kept as `guess`) | minutes of work actually spent on that step when it finishes | ratio actual / guess |

Interrupted sessions resolve no expectation. The GM is **not** told what Pip expected (it must not pander); it judges
the approach exactly as before.

## Surprise
A comparison is *surprising* when it is far from the expectation: session |error| >= 2, experiment |error| = 2, step
ratio >= 1.8 or <= 0.5. Direction is recorded as `better` / `worse` / `longer` / `shorter` than expected (no mood words).

## Storage
```
expectations(id, ts, kind,            -- 'session' | 'experiment' | 'step'
             project_id, subject,     -- the step or hypothesis
             expected TEXT, actual TEXT, error REAL, surprising INT, event_id INT)
work_session + expect TEXT            -- carried from the tool call to the resolution
stages[].guess                        -- Pip's original minutes, never overwritten by the GM's correction
```
The `work` / `experiment` events gain `expected`, `error` and `surprise` fields, so feeds and the reflection can cite
the event id.

## Surfacing (facts only)
- **The result line** Pip sees after a session/experiment adds the comparison: "(you expected it to go well; it went
  badly)". Nothing is added when there was no prediction.
- **Firsts:** new facets `surprise:better`, `surprise:worse` (major) feed "New for you" and the diary moments.
- **Reflection:** the night's surprises are listed with their event ids, so insights and `changed` claims can cite
  them. Day counts gain `predictions` and `surprises`.
- **Calibration block** (after >= 5 predictions; small, fixed size): "Your predictions lately: 6 of 9 close; in 4 of
  your last 5 clockmaking predictions it went worse than you expected." Counts per craft only, with at least 3 data
  points.
- **Learning progress (phase 2):** per craft, mean absolute error over the last 5 predictions vs the 5 before, shown as
  numbers ("your misses on clockmaking: 1.6 before, 0.8 now"), and exposed in `GET /memory`. This is the
  Schmidhuber/Oudeyer idea: what is getting clearer, what stays stuck, and a measurable form of "I'm curious about X".

## Persona
One short sentence: you can say what you expect (`expect`) before working or experimenting; it helps you see how well
you read your own work. Not required, not scored as good or bad.

## Build order
1. `expect` on `work_on` / `experiment`, storage, comparison, result line, event fields, tests.
2. Step duration (`guess`) and its comparison; migration keeps `guess = minutes` for existing stages.
3. Firsts facets, reflection list, day counts, calibration block.
4. Learning progress and API.

## Risks
- Pip may always predict "well". That is itself data (the calibration block shows it), and it is Pip's to notice.
- Over-weighting surprise: only surprises beyond the thresholds are flagged, and nothing nudges Pip to act on them.
- Prediction as ritual: it is optional and unrewarded, so the log shows what Pip chose to predict.

## Decisions made
1. Is a 3-word vocabulary right (`well`/`slowly`/`badly`; `works`/`partly`/`fails`), or do you prefer a 1-5 scale?
2. Show the calibration block only after 5 predictions (proposed), or sooner?
3. Should a surprise ever create a diary moment on its own (beyond the first of each kind)? Proposed: no, the
   nightly reflection covers them.
