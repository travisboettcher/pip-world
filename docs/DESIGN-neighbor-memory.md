# Design: a neighbor who remembers what she's said (less repetition)

Status (2026-10-31): parts 1 and 2 built and tested (fake backend); part 3 (self-check) not built. The same memory
now also covers residents (DESIGN-invented-places.md). Follows
DESIGN-neighbor.md; replaces the ROADMAP backlog idea of a verbatim-repeat check. Where the build had to decide
something the design left open, see "As built" at the end.

## Why
Briar's letters and visits keep bringing back the same details as if new. The clearest case is "the blue door is the
one that rattles": it was in her first letter, then two more letters, then spoken aloud during the 2026-10-31 visit
("Send word by the blue door, Pip, the one that rattles"). The groyne path came up in both visits. The owner likes the
storytelling and a recurring motif; the problem is that she *re-introduces* things, which reads as forgetful.

The cause is mostly what she's fed, not how she writes:
- `neighbors.correspondence()` puts her last letters into every letter and every spoken line **word for word**
  (`gm.neighbor_letter`, `gm.speak_in_person`). Models copy vivid phrasing they can see; the blue door is the most vivid
  thing she has said about herself, and it's in her context every time.
- She has almost nothing new to talk about. `life` holds the last `LIFE_KEPT` (3) one-line updates, and today it holds
  two restatements of the same news (the shingle bank past the third groyne). Each letter adds one sentence at most,
  and nothing stops it repeating the last one.

Not used, and why:
- **Sampling penalties** (frequency/presence/repetition): the Anthropic Messages API has none, and Haiku 5.5 rejects
  non-default `temperature`/`top_p`/`top_k`. They would also act on tokens, not ideas.
- **Matching and rejecting** (shared words, sentence similarity): a lightly reworded repeat passes, and rejecting a
  whole letter is heavier than the problem. The owner asked for a lighter touch.

## The idea
Stop showing her her own sentences; show her what Pip already knows. She can still refer back ("the blue door's still
rattling, you'll remember"), which is the motif done well. She just can't copy what she can't see.

## 1. What she sees (no extra calls)
The calls she already makes return two small optional fields, so the record is always current and costs a few output
tokens:

- `gist`: one sentence, third person, of what this letter or line said ("Told Pip the tide tables for the week and
  asked how the walker's stride went"). Stored on the letter (new column `letters.gist`) or on the `companion` event.
- `told`: 0-3 short phrases for things about herself or her world she told Pip **for the first time** ("her blue door
  rattles in the wind", "the path past the third groyne is buried in shingle"). Appended to a new
  `characters.told` list (JSON, like `life`), capped at `TOLD_KEPT` (30) and oldest dropped.

Prompts then change like this, in both `neighbor_letter` and `speak_in_person`:
- **Pip's words stay verbatim** (she is answering them).
- **Her own earlier letters and lines from earlier visits** are shown as their gists, oldest first.
- **Within the current visit**, her lines stay verbatim so the conversation flows (the visit is marked by the
  `arrived_at` meta that already scopes the greeting). The previous visit is shown as gists.
- A new block: *Things Pip already knows about you (refer back to them if it's natural, but don't introduce them
  again as news):* followed by `told`.

The model judges what counts as "new" in its own words, so a reworded repeat is still something Pip already knows. No
string matching anywhere.

A letter with no `gist` (all letters written before this ships, or a GM reply that left it out) falls back to its first
sentence, clipped; letters age out of the window (`CORRESPONDENCE_SHOWN`, 6) anyway. On first start after the change, a
neighbor with an empty `told` list gets one GM call over the correspondence so far to fill it (`gm.recall_told`), so
the blue door is in the list from day one. One call per neighbor, once.

## 2. Something new to say
- **A life that moves.** The letter prompt shows `life` as "already happening" and asks for a `life_update` only if
  something has *changed* since then. The engine keeps an update only if it isn't a restatement, and that check is the
  model's too: the same call returns `life_update_new: true/false`. Cheap, and no matching. `LIFE_KEPT` goes from 3 to
  5 so there's more to draw on.
- **Things coming up.** `life_update` may carry `upcoming`: `{what, in_days}` (1-14), e.g. "the spring tide on
  Thursday", "a bird count with the warden". Stored on the character (`characters.upcoming`, at most 3). When one comes
  due, her next letter or visit is told "today/this week: <what>", so it happens instead of being forgotten, and it
  moves to `life` afterwards. This is the "small evolving agenda" from the roadmap, without the engine deciding plot.

## 3. A gentle self-check (only if 1 and 2 aren't enough)
After a letter or line is written, one more cheap call reads the draft next to `told` and rewrites only the sentences
that re-introduce something as news, as callbacks or something new, leaving the rest untouched. It never refuses; if it
fails, the original stands. About $0.0003 per letter on Haiku 5.5. Not built in the first pass: we watch a few days of
letters and visits first (see Measuring).

## Guards
- `gist` clipped to 200 chars, each `told` phrase to 80, at most 3 per call; empty or missing fields are fine.
- `told` is shown in full (it's short); if it ever passes `TOLD_KEPT` the oldest drop, which is also how very old
  details become fair game to mention again.
- `upcoming.in_days` clamped to 1-14; at most 3 pending; one that's 3+ days overdue without being mentioned is moved to
  `life` quietly.
- Nothing here changes Pip's prompts. Pip still sees her letters and lines verbatim.

## Measuring
Before and after, over the last N letters and spoken lines: how often a phrase from `told` is presented as news. That
judgment is a model call too, run by hand (`scripts/`), not in the engine. Plus the owner's read of the letters.
Decide on step 3 after a few days.

## Testing (TDD, fake backend)
- Her prompt shows Pip's letters verbatim and her own as gists; the current visit's lines verbatim, earlier ones as
  gists; a letter without a gist falls back to its first sentence.
- `told` grows from the call's field, is capped, and appears in both prompts under the "already knows" heading.
- `life_update` with `life_update_new: false` isn't stored; `LIFE_KEPT` is 5.
- `upcoming` is clamped and capped, surfaces in the prompt when due, moves to `life` after.
- The one-time `recall_told` runs once per neighbor with an empty list and not again (and not when the GM fails
  twice in a row: retried at the next start).
- Mutation gate on `neighbors.py` and the touched parts of `gm.py` (prompt-text mutants in `gm` may be equivalent;
  note them).

## Build order
1. `gist` + `told` + the prompt changes + the one-time backfill (this is the fix).
2. `life_update_new`, `LIFE_KEPT` 5, `upcoming`.
3. Watch for a few days; step 3 only if needed.

## Not now
The same treatment for companion creations (`companions.py` also replays its own lines verbatim; worth doing once this
proves out). Letters that react to Pip's world facts (roadmap idea). Places she mentions becoming real: see
DESIGN-invented-places.md.

## As built (decisions the design left open)
- Her own letters and earlier-visit lines appear as `<name> (in brief): <gist>`; the headings say "Pip's in full,
  yours in brief". A visit line's `gist` is stored on its `companion` event only when the model gave one.
- "The current visit" is every `companion` event at or after the `arrived_at` timestamp (`companions.conversation`
  takes `verbatim_since`); old events with no gist fall back to their first sentence, like letters.
- `told` comes from both calls (letters and in-person lines), clipped to 80 chars, the first 3 non-empty per call.
- The backfill (`neighbors.recall_told` / `gm.recall_told`) runs from the agent loop's world step, not only at
  start-up: any neighbor with an empty `told` and no `told_recalled:<id>` meta gets one call over everything said
  so far, word for word (delivered letters, Pip's letters, visit lines). Success sets the meta, even if the list
  comes back empty, so it never runs again. Failures are counted in memory: after two it waits for the next start.
  It waits while nothing has been said yet, so a newly invented neighbor's first letter is recalled once it arrives.
- `life_update` is kept only when `life_update_new` is explicitly `true` (missing counts as not new).
- `upcoming` is its own optional field of the letter call (`{what, in_days}`), not nested inside `life_update`.
  It's stored as `{what, due_at}`. Pending plans are shown too ("Coming up for <name>: in 3 days: the spring
  tide"), so she can look forward to them and doesn't announce them twice. Due ones read "today or this week:
  <what>". After the next letter or in-person line it becomes `Recently: <what>.` in `life`. Only letters propose
  plans; a visit can bring a due one up. A new plan when 3 are already pending is dropped, and so is an `in_days`
  that isn't a number.
- **Residents** (people met at an invented place, DESIGN-invented-places.md) share the in-person half: their earlier
  lines in brief, this visit's verbatim, `told` from each line. With no letters, they report `life_update` /
  `life_update_new` on their in-person lines instead (same rule: kept only when explicitly new); they have no
  `upcoming` and no `recall_told` backfill. Every letter and in-person call also carries the "Places in Pip's world"
  line and the optional `mentions_place` (DESIGN-invented-places.md, "As built").
