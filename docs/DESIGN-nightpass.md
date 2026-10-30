# Design: the night pass (a reflection that can change goals)

Status: **design only, not built.** Sources: [RESEARCH-self.md](RESEARCH-self.md) (MIDCA's meta-cycle that writes back
goal changes; BDI intention history and reconsideration; AIMA's learning agent: critic -> learning element ->
performance element, and the problem generator; Sleep-time Compute's precomputed "tomorrow brief"; Ricoeur's *ipse*:
what Pip committed to and whether it kept it).

## Why
The nightly reflection is a critic and learning element that can only *describe*: a summary, beliefs, a portrait. It
cannot act on what it understands, so Pip's to-do list, wishes and projects drift (near-duplicate to-dos, stale wishes,
projects it has stopped touching) until a visitor or a tick happens to tidy them. A reflection that cannot change
anything is journaling; one that can adjust goals is self-regulation. This adds that, with limits.

## Shape
A **second call after the reflection**, once per sleep, in Pip's own voice (the persona is the system prompt), with
the reflection's output (summary, insights, changes, turning points) in front of it. It decides a few things about
*Pip's own goals*, and the engine validates and applies them. One extra small call a night.

### Inputs (all facts, nothing evaluative)
- Open to-dos, wishes and ambitions with id, age and when last edited; active projects with progress and days since
  last worked; **last night's focus** and what became of it (below).
- Things Pip has not done in a while, as a plain list (the AIMA "problem generator"): tools unused for 7+ days, people
  not seen for 7+ days, projects idle 3+ days.
- Counts: this stretch's day counts, the capabilities snapshot, surprises.

### Decisions (a fixed vocabulary; the engine rejects anything else)
| Op | Effect | Limits |
|---|---|---|
| `archive_note {id}` | hides a to-do, wish or ambition (status `archived`, nothing deleted) | open items only, never the diary; to-dos older than 24 h, wishes/ambitions older than 3 days |
| `merge_notes {ids, text}` | rewrites the first with `text`, archives the rest | same-section, 2-4 ids |
| `resolve_note {id, outcome}` | marks it done | needs cited evidence that it is done |
| `pause_project {id}` / `resume_project {id}` | new status `paused`: out of the active count and out of "Your projects", still listed under "on hold" | not while a session runs |
| `adopt {section, text}` | adds a to-do or ambition | at most 1 a night, must cite what prompted it |
| `set_focus {items}` | tomorrow's focus: up to 3 lines, each optionally tied to a note or project id | replaces last night's |

Every op carries `because` (ids of lines/beliefs/turning points as in the reflection) and a one-line `reason` in Pip's
words. Ops without a valid citation are dropped (except `set_focus`). At most **3 ops** a night besides the focus.
The optional support check (the same GM call as for insights) can verify `archive_note` / `resolve_note` claims.

### What the night pass never does
Edit or delete the diary; touch anything a visitor owns; delete anything (everything is archived or paused);
start projects; change tools, persona, budget or settings; act on a note Pip edited in the last day.

## Commitment tracking (BDI intention history, *ipse*)
`focus(id, day, text, ref_kind, ref_id, status, decided_at, reviewed_at, note)`; status `open` -> `kept` | `carried` |
`dropped`. At the next night pass the engine **marks deterministically** what it can: a referenced note resolved or a
project advanced/finished = `kept`. The rest are shown back to Pip ("you intended X; nothing changed") and Pip
chooses `carried` (still wants it) or `dropped`, with a reason. Day counts gain `focus_kept` / `focus_total`, so
"I keep my word to myself" or "I rarely finish what I plan" is a number Pip can see and cite, not a feeling. Which of
these Pip turns out to be (stubborn, fickle, steady) is its to find out.

## Surfacing
- **At waking:** "While you slept you decided:" listing each op with its reason and id, shown on the first ticks
  (like "New for you"), then "Your focus today:" (max 3 lines) for the rest of the day.
- **Undo:** every op is a row in `night_decisions(id, ts, op, target, args, before JSON, reason, cites, undone)`, and a
  new tool `undo_decision(id)` restores `before` (un-archive, un-pause, restore the old text). Pip can always take back
  what its sleeping self did.
- **Firsts:** "the first time you changed your plans in your sleep" (major) feeds "New for you".
- **recall / API / pipchat:** decisions are searchable ("what you decided in your sleep"); `GET /memory` lists them;
  `pipchat memory` shows the last few.

## Modes and rollout
`NIGHT_PASS=off | log | apply`. **`log`** runs the call, validates, stores decisions (marked not applied) and shows nothing
to Pip, so you can read what it *would* do via `pipchat memory` before giving it the power. **`apply`** executes them.
Recommended: run `log` for a few nights, then switch to `apply`. Default `log`.

## Risks and mitigations
- **Over-pruning / loss aversion:** age floors, a 3-op cap, citations, the support check, "an unmet wish is not a
  reason to drop it" in the prompt, and `undo_decision`.
- **Thrash:** the focus carries over; a note edited in the last day is untouchable; pause/resume pairs within three
  nights are counted and shown.
- **Confabulated reasons:** citation validation plus the same support check as insights; reasons are stored verbatim.
- **Trivial focus:** harmless, and visible in the kept-rate.
- **Cost:** one small call a night (~$0.001).

## Build order
1. Storage (`night_decisions`, `focus`, project `paused`), the op validators/applier and `undo_decision`, unit-tested
   without an LLM.
2. The night-pass call (prompt, schema, citation validation), `log` mode, `pipchat memory` view.
3. `apply` mode, waking block, focus block, kept/dropped review, firsts, day counts.
4. Persona sentence and docs.

## Open questions
1. Default `log` first, then you flip to `apply` (recommended), or `apply` from the start?
2. Is the op list right? In particular `adopt` (Pip adding goals from its sleep) and `pause_project`; anything you would
   remove, or anything you would add (e.g. reprioritizing)?
3. Should the focus be capped at 3 lines, and is "undo anything" enough, or do you want a stronger brake on destructive
   ops (e.g. archives only after a second night's confirmation)?
