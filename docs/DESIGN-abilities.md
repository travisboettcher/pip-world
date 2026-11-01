# Design: objects that grant abilities

Status (2026-11-01): designed, not built. Roadmap: "Objects that grant abilities" (owner idea, 2026-10-31).

## Goal
A thing Pip made can give Pip something it cannot otherwise do, and only while the thing works. A clock lets Pip know the exact time; a radio
brings news. A stopped clock gives no time, and an unwound radio no news. Prefer general mechanisms (see `CLAUDE.md`): no new tool is added;
abilities are used through what Pip already does (looking at its surroundings, `use_item`).

## Model: an ability registry plus a `provides` capability
Like `world_effects.py`, a small registry in `app/abilities.py` names each ability; the GM may propose it for a creation, the engine checks
and owns the limits.

```
Ability(name, help, words, per_day)
  time  - the exact time of day            (a clock; implied by the existing `timekeeper` capability, no GM proposal needed)
  news  - a short bulletin from the world  (a radio, a wireless, a receiving set; per_day = 3)
```
- New capability `provides: {"ability": <name>}` in `creations.CAPABILITIES`. `sanitize_spec` keeps it only if the ability exists and the
  project's own words suggest it (same word check as `world_effects.allowed`), and at most one ability per creation.
- A creation is a **provider** of an ability while it is `running` (existing: stopped by mishap or by upkeep running out, so a radio with
  `upkeep` goes quiet until it is tended). `abilities.providers(state, name, now)` and `abilities.has(state, name, now)` are the only checks.
- Adding an ability later is one registry entry plus the place its result shows up.

## What Pip sees
- **time**: while a running provider exists, the time line in perception gains the exact time and how the clock runs ("By your Gear Clock it is
  2:14 PM, about 2 minutes fast."), instead of only the period of day. Without one, Pip still gets the period ("It is afternoon").
  The creation line keeps its own reading as today.
- **news**: nothing in perception. `use_item` on a running provider with a purpose that fits (listen, tune in, turn it on, whatever) asks the GM
  for a `bulletin`: two or three sentences about Pip's world only (the weather summary, the neighbors' recent news, the season, an invented
  harmless item), never real-world events. The engine limits it: `per_day` per creation, counted in the creation's runtime
  (`news_log`: timestamps). Over the limit, the result is plain narration: "only static" (no bulletin). Bulletins are logged as a `creation`
  event of kind `news` so reflection and recall can see them.

## Engine changes
1. `abilities.py` registry; `providers`, `has`, `allowed(ability, project)`, `gm_lines()`.
2. `creations.py`: `provides` in `CAPABILITIES`, sanitize, `describe` ("it brings you news" for a running one), `use` passes `news_allowed` to the GM and
   records the bulletin.
3. `gm.py`: design prompt lists the abilities via `abilities.gm_lines()`; `use` gains an optional `bulletin` ask when allowed.
4. `sleep.perception` (or the perception assembler) adds the exact time when `abilities.has(state, "time", now)`.

## Not now
Weather at the radio beyond a one-line summary being passed as flavour; real headlines (owner chose the invented, in-world source);
abilities that need a new tool.

## Tests
Registry checks and word gating; sanitize drops unknown or unsuited abilities; providers stop when the creation stops or its upkeep runs out;
the exact time appears only with a running provider; bulletin limit per day and per creation; the GM prompt carries the registry; `use` with no
GM reply degrades to plain narration.
