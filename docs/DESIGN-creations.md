# Design: projects, living creations, and companions

Status (2026-10-29): phases 1-3 implemented and tested (unit tests, plus each GM prompt run once against
Haiku 5.5); not yet deployed. Phase 4 (neighbor letters) is designed only, see the bottom.

## Problem
Pip's projects exist only in its head. `set_activity` stores a label, `use_item` on a tool changes nothing, and
nothing in the world ever reports a result. Observed in the first ~60 ticks:
- the same activity restated every minute ("filing pallets" x6, "cutting escape wheel" x7)
- near-duplicate todos that never close (#19/#34/#38/#43/#50 are all "cut the escape wheel and run the train")
- Pip only finishes things by deciding "close enough"; diary #26: "the loop is in my notes, not in the gears"

Goal: work has results the world decides, and finished things are **alive and useful** (a clock keeps time, a
mechanical bird sings and talks) **without hand-scripting every possible creation**.

## Core principle: the engine owns the rules, an LLM writes the content
Three parties:
- **Pip** (the agent) chooses what to do. It can't declare outcomes.
- **The engine** (plain Python) owns numbers and state: progress, materials, energy, dice, timers, what a
  capability does each minute. Deterministic given its RNG, testable, cheap (no LLM in the monitor loop).
- **The game master (GM)**: a separate LLM prompt (same backend and budget as Pip) that turns engine facts into
  flavor and turns free-form ideas into *data from a fixed vocabulary*. It never decides an outcome the engine
  already decided, and everything it returns is validated and clamped. Every GM call has a non-LLM fallback, so a
  GM failure (bad JSON, budget hit, API error) degrades flavor, never correctness.

GM calls use tool calling with a single `report` tool for structured output (works on every backend); a JSON blob
in plain text is accepted as a fallback.

## Phase 1: projects with world-decided progress

### Tools
- `start_project(name, goal)`: the GM **plans** it: 2-5 named stages, each with work minutes and materials, a
  difficulty (1-5), a craft (skill name, e.g. `clockmaking`), and helpful tools. The engine clamps: 15-240 min per
  stage, total material units <= 8, at most 3 active projects. Materials may include things Pip doesn't own yet:
  that's what creates real wants (wishlist, visitor gifts, later foraging).
- `work_on(project, minutes)`: one work session, 15-120 min, on the current stage. Materials for a stage are
  consumed when its first session starts; if they're missing the call is refused with exactly what's needed.
  The session runs in real time (`WORK_SPEED` scales it like `GROW_SPEED`); Pip's activity becomes
  `working` with the stage as description. Pip doesn't need to wake until it ends.
- `abandon_project(project, reason)`.

`rest` mid-session ends the session early: elapsed minutes are credited at half rate (as "slow", no dice, no
narration), so stopping early never beats finishing. `set_activity` during a session only updates the description
and mood (in the first live run Pip paired `work_on` with `set_activity` in one turn and cancelled its own work at
0 minutes). Eating and gardening don't interrupt.

### Resolution (engine)
When a session ends, the monitor resolves it:

```
score  = 0.05 * skill_level + 0.05 * helpful_tools_owned (max 3) - 0.05 * (difficulty - 1) - (0.15 if energy < 0.3)
r      = rng.random() + score
result = setback (r < 0.15) | slow (< 0.40) | good (< 0.90) | breakthrough
credit = minutes * {setback: 0, slow: 0.5, good: 1, breakthrough: 1.5}, capped at the stage's remaining minutes
```

- `skill_level = floor(sqrt(craft_xp_minutes / 60))`, max 5. Every session adds its minutes as xp, whatever the
  result. Practice makes Pip better (and makes the gifted needle file matter).
- A **setback** leaves a mark: the GM's narration is stored as a `scar` on the project, and scars become the
  finished creation's quirks. Personality comes from history, not randomness at the end.
- Working drains extra energy (`WORK_ENERGY_PER_HOUR`).

Then the GM **narrates** the result in 1-2 sentences, told the outcome, the stage, and the materials and tools Pip
actually has (without them it invented knives and wood), and is not allowed to change the outcome. Fallback: a template ("Progress on the escape wheel was slow."). A `work` event is logged and Pip is woken.
Breakthroughs, setbacks, finished stages and finished projects are diary "moments".

### Pacing
While a session is running, timer (heartbeat) wakes are pushed back to the session's end. Visitors and alerts
still wake Pip. This removes the "restate my activity every minute" ticks, which were most of the spend.

### Quality
On completion: `quality_points = breakthroughs - setbacks + skill_level / 2` maps to `rough` (< 0), `sound`
(< 1.5), `fine` (< 3), or `masterwork`. Quality sets the numbers in phase 2 (a rough clock drifts more).

## Phase 2: living creations

### Open-ended by default
Pip can make anything: objects, pictures, music, writing, clothes, machines, plants. Nothing in the prompts names
example projects, materials, crafts, sounds or names; the GM's planner and designer are told to follow Pip's idea
and fit the kind of work it is (a poem's stages and setbacks aren't a carving's). The only fixed parts are the few
*behaviours* the engine can run, and those are generic primitives whose specifics the GM writes.

### Not everything does something
Most creations - art, writing, music, keepsakes, gifts, clothes - have **no capabilities**: they are simply
themselves. The GM is told that zero capabilities is the right answer for such things, not to invent behaviour, and
to describe the thing itself rather than what it can or can't do. They show up with their description and quirks but
no running/stopped state, the engine never touches them, and `use_item` still works on them (reading a poem can lift
Pip's mood).

### Capabilities (generic primitives)
A creation is a stored **spec**: 0-3 capabilities plus 1-3 quirks. Each capability is a small engine handler that
knows *how to run* a kind of behaviour; everything specific about it is GM-written data. New primitive = one handler,
and every future creation can use it.

| Capability | Params (GM writes, engine clamps) | Engine behaviour |
|---|---|---|
| `timekeeper` | none (drift comes from quality) | Perception shows the time it shows and how far off it is. Drift accumulates per day; `use_item` can set it right |
| `upkeep` | `verb` (how it's tended, any word), `hours` 4-72 (x quality factor) | When the time runs out it **stops** (every other capability pauses) and Pip is woken. `tend` restarts it |
| `periodic` | `lines` (1-3 short sentences in the thing's own manner), `every_minutes` 20-720 | Logs one of the lines as a `creation` event now and then. Doesn't wake Pip |
| `sensor` | `condition` in `crop_ripe, visitor, dawn, dusk, hungry, tired`, `alert` (a line) | Edge-triggered: logs the alert and wakes Pip |
| `helper` | `effect` in `hurry_crops, find, comfort`, `line`, `every_minutes` (>= 60/360/240), `finds` (2-4 kinds of thing, `find` only) | `hurry_crops`: growing crops lose 10% of remaining time. `find`: 1 of its `finds` becomes a material. `comfort`: +0.05 energy. The `line` is logged each time |
| `companion` | `persona` (2-3 sentences), `chatter_minutes` 60-720 | Becomes a character that talks (phase 3); it names itself |

Capabilities compose: `timekeeper + periodic + upkeep` is a cuckoo clock that must be wound, or an hourglass that
must be turned, depending on what the GM wrote. A creation without `upkeep` keeps going forever.

Checked against the live model (Haiku 5.5) on a mixed set: a poem, a lullaby and a quilt got no capabilities; a
scarecrow got `hurry_crops` ("keeping sparrows away"); a jar lantern got `sensor: dusk` + `upkeep: trim`; a moss
terrarium got `upkeep: misting`; a clay pigeon became a companion that named itself; a wind-up mole got `find` with
its own list (buttons, bent keys, sea glass). An earlier run showed the GM squeezing the scarecrow into
`sensor: visitor` when the condition meanings weren't spelled out, so each enum value is described in the prompt.

### Design call (GM, once per project)
Input: name, goal, narrations, scars, quality. Output: final name, a short description, capabilities with params,
quirks. The engine drops unknown capabilities and unusable params (a `find` helper with nothing to find, a `sensor`
without an alert), clamps numbers, caps at 3 capabilities, allows `companion` only for difficulty >= 3, and falls
back to scars as quirks. Fallback for a failed call: the thing simply exists, with no capabilities.

The spec is **persisted**, so a creation behaves the same forever instead of being re-imagined on every mention.

### Interaction
- `tend(creation)`: restarts an `upkeep` creation (and one that was stopped by a mishap). A timekeeper that stood
  still restarts from the time it stopped, so it's now behind until Pip sets it.
- `use_item(item, purpose)`: if the name matches a creation instead of an item, the GM resolves the use (using,
  looking at, playing, reading, whatever fits): it gets the spec, state and Pip's purpose and returns a short
  narration plus effects from a capped list: `mood` (text), `energy` (-0.1..+0.1, at most once per creation per
  6 h), `set_clock` (timekeeper only), `stop` (only for `upkeep` creations, since tending is the only way to restart
  one). This is the open-ended path: Pip can do anything with a creation in words, but the world only changes
  through effects the engine knows.

### Visibility
- Perception gets "Your projects" (stage, progress %, materials needed, current session) and "Your creations"
  (going / stopped and what it needs, time shown, quirks; nothing but description and quirks for art). Recent events include creation chatter.
- API: `GET /projects`, `GET /creations`; `pipchat projects|creations`; UI panels.

## Phase 3: companions (characters)
A `companion` creation gets a row in `characters` (persona, chatter interval, last spoke). Characters are **not**
full agents: one small GM-style call per line, no tools beyond a `speak` report, tiny context (persona, what Pip
is doing, the last few lines exchanged). That keeps a chatty companion cheap.

- **Chatter**: while its creation is running, a companion says something every `chatter_minutes` (+-30%
  jitter). Logged as a `companion` event; doesn't wake Pip.
- **Conversation**: `say(text, to=<name>)` addresses a companion. It answers on the next monitor pass and that
  answer wakes Pip. Cap: `COMPANION_REPLIES_PER_HOUR` (default 4) per character, so Pip and a companion can't
  ping-pong the budget away.
- A stopped creation's companion is silent (tending it is how Pip keeps a friend going).
- Companion lines are untrusted model text in Pip's prompt, framed the same way as visitor text.

## Phase 4 (designed, not built): a neighbor
Same `characters` table with `kind = neighbor`, no creation behind it. `write_letter(to, text)` queues a letter
delivered after `LETTER_DELAY_MINUTES`; the neighbor's reply is generated on delivery and arrives after another
delay, then wakes Pip like a visitor. Occasionally the neighbor writes first, or sends a small parcel (seeds), capped
at one per day. Gives Pip a relationship that isn't Morgan, and slow mail is cheap.

## Explicitly out of scope here
Day/night and sleep, places and foraging trips, economy, HA weather, postcards to Morgan: see ROADMAP "Ideas".
The `helper: find` capability is the only foraging until places exist.

## Cost estimate
GM calls are ~1-2k tokens each: one plan per project, one narration per session (sessions are 15-120 min, so a
few per hour at most), one design per finished project, one per creative `use`, one per companion line. Less than
the per-minute restating ticks they replace.
