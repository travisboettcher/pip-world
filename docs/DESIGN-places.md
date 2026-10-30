# Design: more places, and tools that belong to places

Status: **step 1 (tool scoping) built 2026-10-30; the rest is designed, not built.** Decisions (owner: "go with your
recommendations"): shared verbs (`browse`, `gather`); woods + junkyard first, market and coins later; `places.json` waits for
the public-repo extraction; woods/junkyard daylight-only, library always open; every built-in place known from the start. Builds on [DESIGN-library.md](DESIGN-library.md) (places, `go_to`, the library) and
[DESIGN-neighbor.md](DESIGN-neighbor.md) (neighbors' homes).

## Why
- Pip has three kinds of place (home, the library, a neighbor's home) and nearly all of its materials still arrive as
  gifts. A wish for brass becomes a visitor's errand. More places give Pip somewhere to *go and get* things, and give
  the day shape (open hours, daylight).
- Today location is enforced by scattered checks inside tools (`away_from_home`, `not_at_library`), and every tool is
  offered on every call whatever Pip is doing or where. Adding a place means touching tools, perception and checks.
  Library tools are named for the library (`browse_library`), which won't generalize.

## Proposal: places supply the tools
Pip is offered, on each tick, the tools that make sense *where it is*: the **everywhere** tools plus the tools of the
**current place**. A place is a data record that says what you can do there; the verbs are shared.

### Options considered
| Option | For | Against |
|---|---|---|
| One generic `interact(thing, action)` | tiny tool list; trivially extensible | free-text actions lose typed schemas and the model's tool-calling strengths; every place needs prose to explain its verbs; harder to validate and test |
| A bespoke tool per place action (`browse_library`, `forage`, `scavenge`, `buy`...) | typed and clear | tool bloat; the library's naming doesn't generalize |
| **Scoped tools with a few shared verbs (recommended)** | typed schemas, small list per place, one place record to add a place | the offered tool list changes when Pip moves (fine: prompts change only on arrival) |

The recommended middle: **shared verbs whose meaning and description depend on the place**, so Pip's vocabulary stays
small and the description it sees tells it what the verb does *here*.

| Verb | Where | Meaning |
|---|---|---|
| `browse(query?)` | library, market, junkyard | look through what is on offer (replaces `browse_library`) |
| `read(book, minutes)` | library | unchanged |
| `gather(minutes)` | woods ("forage"), junkyard ("scavenge") | a timed session that finds things |
| `buy` / `sell` | market (with the economy) | trade for coins |
| `say(to=...)` | a neighbor's home | unchanged: talk in person |

`browse_library` stays accepted as an alias for a while (see Migration).

## A place is a record
```
Place: key, label, blurb (what the GM is told), walk_minutes, tools {verb: description-here},
       open_hours (None = always), requires (e.g. the Calibre mount), loot (for gather places)
```
Built-ins live in code; an optional bind-mounted `places.json` can add or override places (descriptions, hours, walk
times, loot tables) without code, which also helps the public-repo extraction. The file is validated like the GM's
output: unknown fields are ignored, quantities and probabilities are clamped.

### First batch
| Place | Walk | Hours | Tools | Gives |
|---|---|---|---|---|
| workshop (home) | - | always | work, garden, projects, sleep, creations | the garden and the making |
| library | 10 min | always | browse, read | knowledge (unchanged) |
| woods | 8 min | daylight only | gather ("forage") | sticks, bark, resin, feathers, wild berries and nuts (food), seeds now and then |
| junkyard | 15 min | daylight only | gather ("scavenge"), browse | scrap brass and wire, gears, odd parts, now and then a tool |
| neighbors' homes | as now | always | say (in person) | talk |

A second batch adds the **market** with coins (`buy`, `sell`, `browse`), i.e. the roadmap's economy. It is deliberately
separate: it changes what everything is worth.

## Tool scoping
Each tool is declared with where it can be used: `where="anywhere"` (default), `"home"`, or a set of place keys.

| Where | Tools |
|---|---|
| anywhere | `say`, `set_activity`, `eat`, `rest`, notes (`note_to_self`, `edit_note`, `resolve_note`), `recall`, `web_search`, `write_letter`, `go_to`, `start_project`, `revise_plan`, `abandon_project`, `resume_project`, `undo_decision`, `use_item` |
| home | `work_on`, `experiment`, `plant`, `harvest`, `tend`, `sleep` |
| library | `browse`, `read` |
| woods, junkyard | `gather`; junkyard also `browse` |

- The tool list sent to the model each call is filtered by the current location. The engine still **enforces** it when a
  tool is called (the model may use a stale idea of where it is): "you can't do that here; it's something you do at the
  library". The ad-hoc `away_from_home` / `not_at_library` checks go away.
- Place-specific descriptions come from the place record (`browse` at the market says what the market offers).
- Perception gets one line: "Here you can: browse (look through the shelves), read (...)", built from the same record,
  so Pip is told what is possible without a tool schema it must infer from.

## The directory: how Pip knows where to go
If tools belong to places, Pip must be able to tell *where* a thing can be done from anywhere, since the tool is not on
its list until it gets there. Three layers, cheapest first:

1. **Always in the prompt (compact):** the "Places you can go" line grows into a small directory, built from the same
   place records as the tools, so it can't drift from what is actually possible:
   ```
   Places (go_to): library, 10 min - browse and read books
                   woods, 8 min, daylight only (open now) - forage for wood, bark, resin, berries
                   junkyard, 15 min, daylight only (closed until morning) - scavenge scrap, gears, parts
                   Marigold's home, 12 min - talk with Marigold
   ```
   About 100 tokens, shown wherever Pip is (home or away), with "closed now" computed from the clock. Pip lives here, so it
   knows its neighbourhood and what each place is *for*; what it will actually *find* it learns by going.
2. **`where_to(what)` (anywhere):** "where could I get brass?" It searches the directory (blurbs, verbs) and **what Pip has
   already found where**, kept in a small table `place_finds(place, item, times, last_ts)` filled from `gathered` events and
   `browse` results. Answer, in facts: "the junkyard: scrap metal; you found brass wire there twice (last on Nov 2)". It is
   only what Pip knows; a place it hasn't tried says "you haven't looked there yet".
3. **Where it is needed:** a project step that lacks materials already says "missing 2 brass wire"; it gains
   "(you found brass wire at the junkyard)" when Pip has found it somewhere. The night pass's "things you haven't done in
   a while" can include "you haven't been to the woods in 6 days". Arriving at a place prints "Here you can: ..." (the
   place's verbs with their local descriptions).

Later extension (not in the first build): **discovery of places**: some places start unknown and are learned from a
neighbor's letter, a book or a visitor, appearing in the directory when learned. For the first batch every built-in
place is known from the start.

## `gather`: the shared engine
A real-time session like work and reading (`kind = gather`, 15-60 minutes, `WORK_SPEED` applies). When it ends:
1. The engine rolls a haul from the place's **loot table** (item, kind, weight, quantity range, optional rarity), shifted
   a little by luck and by Pip's skill (handiness / knowledge, fed from the abilities it already has). It never invents
   items; the table is the world.
2. **Depletion**: each place has a stock that sessions draw down and time refills (default +1 hour per hour, full at
   100), so camping at the junkyard returns less. "The easy pickings are gone" is a fact Pip can read from the result.
3. One short GM call narrates the haul in a couple of sentences, using only the items the engine gave it (same pattern
   as work).
4. Items go to inventory like gifts do; the event `gathered` feeds firsts (`gathered:brass scrap`), capabilities
   ("woods: 9 gathers, 8 found something"), recall and the nightly reflection.
Interrupting (resting, a visitor) ends early with a proportional, smaller haul.

## Hours, daylight, walking
- `open_hours` and daylight use the same local clock as sleep. A closed or dark place can still be walked to, but its
  tools are not offered and perception says so ("the junkyard is closed until morning"). Pip is nudged to sleep at night
  by the existing mechanisms; it is never forced.
- Walk time is per place (`walk_minutes`), the same session machinery as today.
- First arrival at each place: the GM writes the description once and it is kept (as now), seeded from the place's blurb.

## Interplay with what exists
- **Materials economy:** Pip can now meet its own wishes. The wish-reconciliation hints still apply; "gifts grant wishes
  within minutes" (roadmap) is partly solved because gathering takes real time and stock runs down.
- **Firsts / capabilities / night pass:** new facets (`place:woods`, `gathered:*`), capability counts per verb, and the
  night pass's "things you haven't done in a while" list can include places.
- **Neighbors:** unchanged; a neighbor's home is a place whose only extra tool is conversation.
- **Project and garden work** need Pip at home exactly as today, now by scoping instead of per-tool checks.

## Migration
- `browse_library` -> `browse` in `TOOLS`; the old name is accepted as an alias (with a log line) and in history:
  firsts and capabilities normalize tool names through one alias table so past counts and "first" dates carry over.
- The persona's library paragraph becomes a general "you can go to other places; what you can do depends on where you
  are".
- Existing events/logs are untouched.

## Build order
1. **(built)** Scoping: `where` on tools (`@tool(..., where="home"|"library"|...)`), enforcement in the registry wrapper so every
   caller gets the same answer, the offered list filtered by location each tick (`specs_for`), a "Here you can also" line away from
   home; `away_from_home` / `not_at_library` removed. One deliberate change: `tend` is now home-only. Aliases arrive with the
   `browse` rename in step 2.
2. Place records and registry (library and neighbors expressed as records); `browse` replaces `browse_library`; the directory
   line in the prompt and the arrival "Here you can" line.
3. `gather` engine (loot, depletion, narration, events), woods and junkyard, hours/daylight, `place_finds` and `where_to`,
   the "(you found X at ...)" hint on missing materials.
4. Optional `places.json`; docs; roadmap.
Later: market and coins; more places.

## Risks
- **Farming:** depletion, session length, daylight and walking time cap it; the loot table decides rarity, not the GM.
- **A stale tool list:** the model may call a tool offered on the previous tick; enforcement returns a helpful error.
- **Tool churn between ticks** changes the prompt prefix (matters only if prompt caching is used; not today).
- **Too many places** dilute the world: start with two.
- **Brass inflation:** make scrap brass common but small-quantity, and gears/tools rare.

## Open questions
1. Shared verbs (`browse`, `gather`) as recommended, or distinct names per place (`forage`, `scavenge`)?
2. Batch 1 = woods + junkyard, with the market and coins as a separate later batch?
3. Should `places.json` (user-editable places and loot) be part of the first build or wait for the public-repo extraction?
4. Daylight-only for woods and junkyard, and always open for the library?
5. Should every built-in place be known from the start (recommended for the first batch), with learning-about-places via
   letters and books as a later extension?
