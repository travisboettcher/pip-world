# Design: firsts and cited reflections (the start of a sense of self)

Status: **design only, not built.** Sources and rationale: [RESEARCH-self.md](RESEARCH-self.md) (mechanisms 1 and 2).
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
  `New for you (last 6 h): - the first time you planted something (2 h ago) ...` Max 5 lines, newest first, majors before
  minors. A first drops out after the window; it is not repeated every tick.
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
