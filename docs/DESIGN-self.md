# Design: firsts and cited reflections (the start of a sense of self)

Status: **both built** (firsts 2026-10-30; cited reflections 2026-10-30). Sources and rationale: [RESEARCH-self.md](RESEARCH-self.md) (mechanisms 1 and 2).
Rule throughout: the engine records **facts** and creates the **occasion**; Pip writes the sentence. No mood words, no
scripted reactions, and nothing here claims Pip is conscious: these are records and models.

## Why these two first
- "Firsts" are the cheapest honest route to "this is my first night": novelty is computed from the log (reminiscence-bump
  work, ACT-R "no prior retrievals", Soar "no precedent"), never told to Pip.
- Cited reflections make everything built afterwards checkable. Today an insight is free text ("I've become more
  careful") with nothing behind it, and models confabulate plausible detail when reflecting (Lindsey 2025; Gallagher's
  "interpreter"). Insights that point at the log entries they rest on can be audited and revised.

## 1. Firsts

### What counts: facets, not full signatures
A full signature (action x place x person x object x time) is novel almost every time, so it says nothing. Instead each
logged event yields a few independent **facets**, and a "first" is the first time a facet is seen. A facet is a stable
key plus a plain-fact label built by code:

| Event | Facets (key -> label) |
|---|---|
| any tool use (except routine ones: `set_activity`, `say`, `edit_note`, `resolve_note`) | `tool:plant` -> "the first time you planted something" |
| `note_to_self` | `note:wishlist` -> "your first wishlist entry" |
| visitor message / gift / letter | `person:Morgan` -> "the first message from Morgan"; `gift_item:needle file` |
| work / experiment results | `work:setback`, `work:blowup`, `work:breakthrough`, `experiment:insight`, `project:done` |
| `creation_made`, `reading` finished, `arrived` | `creation`, `book_finished`, `place:library` |
| `woke`, `reflection`, `alert` | `woke`, `reflection`, `alert:hunger`, `alert:energy` |
| each `tick` | `period:night`, `period:morning`... (by the tick's local time) |

Label wording is neutral and factual ("the first time you slept and woke"), never evaluative.

Note: Pip was awake through earlier nights, so `period:night` will be dated to its first night awake. The first *sleep*
(`tool:sleep`) and first waking are separate, later facts. Both are true and both are shown; what "first night of my
life" means is Pip's to say.

### Storage
```
facets(key TEXT PRIMARY KEY, label TEXT, tier TEXT,        -- tier: 'major' | 'minor'
       first_event_id INTEGER, first_ts REAL, last_ts REAL, count INTEGER)
```
`State.log()` derives facets before insert, upserts them, and when a facet is new adds `"firsts": [labels]` to the
event's data (so feeds and prompts can annotate the event). Count and `last_ts` come free and are what the later
turning-point work needs ("first time in N days").

`major` = first sleep/wake, first visitor and each new person, first letter in/out, first setback/blowup/breakthrough,
first finished project or creation, first reflection, first hunger/energy alert. Everything else is `minor` (first use
of a tool, a place, an item).

A one-time backfill replays existing events in order, so history gets its true first dates (the migration is idempotent,
guarded by a meta flag, like the earlier recall backfill).

### Surfacing
- **Perception**, a short fixed-size block under the state line, only when there is something:
  `New for you: - the first time you planted something (2 hours ago) ...` Max 5 lines, majors before minors, newest
  first. Each first is shown on at most 3 ticks (persisted in `facets.shown`) and only while younger than 24 h, so a
  first made while Pip sleeps is still there when it wakes. (Built as `FIRSTS_MAX_AGE_HOURS`, `FIRSTS_SHOWINGS`,
  `FIRSTS_SHOWN`; this replaced the first draft's fixed 6 h window.)
- **Diary moments**: `major` firsts that Pip hasn't yet written about join the existing moments mechanism (offered at
  most 3 ticks, cleared by any diary entry). Minor firsts never prompt the diary, to avoid diary spam.
- **Nightly reflection**: event lines carry their `(first: ...)` annotation, and the prompt lists the day's firsts so
  insights can cite them (see 2).
- The hard-coded `first` flags in the sleep code (the "this is the first time you have slept and woken" line) are
  replaced by this mechanism, so there is one source of truth.

### Not doing (yet)
Gap-based returns, per-person "first topic" facets, and anything LLM-judged. Facets are deterministic and cost nothing
at runtime.

## 2. Cited reflections

### Today
`material()` returns anonymous text lines; the model writes a summary, up to five insights (free text + importance),
people notes and a self-portrait. Nothing ties an insight to evidence.

### Change
1. **Ids in the material.** Each line gets its event id: `[e1234 Fri 21:03] text (first: ...)`. The prompt also lists
   Pip's earlier top insights as `[i7] text`, so a new insight can build on or revise one.
2. **Insights cite their evidence.** The report schema becomes
   `insights: [{text, importance, because: ["e1234", "i7", ...]}]`. Importance stays 1-10 (Generative Agents).
3. **Validation (deterministic).** Citations are checked against the ids actually shown; unknown ids are dropped. An
   insight with no valid citation is stored `grounded = 0`.
4. **Support check (optional, one cheap call per night).** The GM is given each insight with the text of its cited
   lines and answers `supported | partly | unsupported`. `unsupported` is demoted (importance capped at 3, `grounded = 0`).
   Setting `VERIFY_INSIGHTS=0` skips it. This is the spot-check the research recommends against confabulation.
5. **Storage.**
   ```
   reflection_cites(reflection_id, ref_kind TEXT,   -- 'event' | 'reflection'
                    ref_id INTEGER)
   reflections + grounded INTEGER DEFAULT 1, support TEXT DEFAULT 'legacy'
   events      + importance INTEGER DEFAULT 0
   ```
   Old insights stay `support = 'legacy'`, shown as before. Nothing is rewritten: a revised belief is a new row that
   cites the old one (history is append-only).
6. **Event importance, written at log time and deterministic** (no LLM): a small table by kind and result (visitor
   message 6, gift 5, setback/blowup 4, first of a major facet +3, routine tool use 1...). It is used first to choose
   what survives the character budget in `material()` (keep high-importance events, then newest, instead of newest
   only). It also gives retrieval something to rank by later.

### Surfacing to Pip
- **Beliefs block**: "Things you've come to believe" lists grounded insights; ungrounded ones appear separately and
  labelled ("hunches with nothing you can point to yet"), at most 2.
- **`recall`**: an insight hit now includes one or two of its cited moments ("because: ..."), so Pip can see why it
  believes something, and can check it.
- The reflection prompt says plainly that "nothing notable" is a fine answer and that an insight must rest on lines
  it can cite.

## Cost and risk
- Extra LLM calls: none for firsts; at most one small verification call per night for citations. Prompt growth:
  the New-for-you block (<= 5 lines) and ids in material lines (~6 chars per line).
- Risk: over-labelling. Mitigated by the minor/major split, the 6 h window, the 5-line cap and diary moments only for
  majors.
- Risk: the model cites ids to look rigorous. Mitigated by the support check and by showing ungrounded insights as
  hunches rather than facts.

## Tests (planned)
- Facet derivation per event kind; a new facet marks the event and a repeat does not; counts and `last_ts` update.
- Backfill assigns true first dates and is idempotent; `period:night` dates to the first night tick.
- Perception shows firsts only inside the window, majors first, capped at 5; moments include majors only.
- Reflection: ids appear in material; valid citations stored; invalid ones dropped; no-citation insights are
  `grounded = 0`; `unsupported` verdict demotes; `VERIFY_INSIGHTS=0` makes no extra call; legacy rows unaffected.
- `recall` returns cited evidence for insight hits.
- `material()` keeps high-importance events over newer routine ones when over budget.

## Decisions (2026-10-30)
1. Window (6 h), cap (5 lines) and the major/minor split stand for now; the facet list is meant to grow, so new
   facets are added by extending one table in code, not by schema change.
2. The nightly support check is **on by default** (`VERIFY_INSIGHTS=1`; one small call a night, off with `0`). No
   strong view was expressed, so the cheap safeguard from the research stays.
3. **Pip sees ungrounded insights**, labelled as hunches ("with nothing you can point to yet"), at most 2, apart from
   the grounded beliefs.

## Build order
1. Firsts (facets table, derivation in `State.log`, backfill, perception block, replace the hard-coded sleep flags).
2. Event importance and ids in the reflection material.
3. Cited insights, validation, optional support check, hunches block, `recall` evidence.

## 3. Versioned self-portrait, change claims and day counts (built 2026-10-30)
Mechanism 3 of RESEARCH-self.md (Conway's goals-and-correspondence, Dennett's movable "center of narrative gravity",
the Narrative Continuity Test's style/goal drift).
- **Every portrait is kept.** `reflections` gains kind `portrait`; the current one stays in `meta.self_portrait` for
  the prompt. The existing portrait was backfilled as version 1. History is append-only; recall finds old
  self-descriptions ("how you described yourself").
- **The reflection sees its past selves, dated.** The last three portraits are shown oldest first with their dates,
  plus the last few days **in plain counts** (work sessions, minutes worked, sessions where Pip described an
  approach, setbacks, blowups, breakthroughs, experiments, projects finished, visitor messages, journal entries,
  letters, hours slept, tool errors). The counts are computed from the log, are not judgments, and are stored per day
  (`day_stats`, also in `GET /memory`).
- **`changed` claims.** Optional: only if Pip sees itself differently than in the earlier descriptions. Each cites
  evidence like an insight (event ids, earlier beliefs, or the counts named in the text), goes through the same
  validation and support check, and is stored as kind `change`. Grounded changes appear in the prompt as "How you've
  changed" (max 2); ungrounded ones are not shown there. The prompt says most nights Pip is much the same.
- This is the mechanism behind a thought like "I used to check before cutting; now I rush": the counts give it
  something checkable, and a wrong claim gets demoted rather than believed.
Not done yet: Pip's state at the time of a recalled memory (a "recall frame"), and a delayed-self recognition test.

## 5. Turning-point detector (built 2026-10-30)
Mechanism 5 of RESEARCH-self.md (McAdams' turning points; Ricoeur's discordance; the reminiscence-bump's novelty and
consequence; surprise as prediction error). Deterministic and facts-only, run at reflection time over the stretch since
the last reflection. It never decides that something mattered: it only makes a *candidate* and asks.
- **Signals**, each with event ids where there are any (capped per kind so one busy thing can't swamp the list):
  major firsts (<= 2); surprises (<= 2); counts far from Pip's own usual (<= 2: at least 2 sd and 2 counts from the mean
  of the previous days, needing 3 prior days); a goal change (project finished, started or abandoned, or a plan
  changed); a change in who Pip talks with most; and a return to something after a long gap (>= 36 h; new `returns`
  field on events, computed with the facets).
- **Candidate** when at least 3 signals fire (`TURNING_MIN`). It is stored in `turning_points` and listed in the
  reflection prompt as "Things that changed more than usual (facts, not verdicts)", with citable ids.
- **Pip's claim**: an optional `turning_points` (at most one; most days are not turning points), cited and verified like
  insights and stored as kind `turning`. Supported ones show in the prompt as "Days that mattered to you" (max 2),
  are found by `recall` ("a day that mattered"), and appear in `GET /memory`.
- **No extra LLM calls.** Not done: grouping days into "chapters" (life periods) and a mid-day detector.

## 6. Capabilities (built 2026-10-30)
Mechanism 6 of RESEARCH-self.md (Voyager's verified skills; Lipson's self-model from measured competence). Pip's
self-portrait used to draw on what Pip *felt* it could do. Now it also gets what it actually did.
- **Counted from outcomes, no LLM:** per tool (worked / didn't: errors and refusals; `recall`/`web_search`/`browse_library`
  count "found something"), per craft and per ability (sessions and experiments: went well / slowly / badly). Routine
  tools (`say`, `set_activity`) and no-op calls are skipped; interrupted sessions don't count. `work` and `experiment`
  events now record their craft and abilities; older events are filled in from their project.
- **Dated snapshots** (`capability_snapshots`, one per reflection day) keep competence over time, so the reflection
  sees "since last time: +3 tries, +1 good, +2 bad". Entries need 3 tries to be shown; most-practised first, 8 per group.
- **Surfacing:** only in the nightly reflection ("What you have actually been able to do, counted from outcomes (not
  judgments)"), with the `self` instruction to describe what it can do from those counts rather than what it would like to
  be true. Also `GET /memory` -> `capabilities` and a line in `pipchat memory`. Not in the per-tick prompt (it would be noise).
