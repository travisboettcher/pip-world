# Design: world packs (a world-neutral engine)

Status (2026-11-11): designed; **phase 1 built (0.31.0, 0.32.0)**: the pack loader, `WORLD_PACK`, Pip's world's persona, narrator, bible
and guide in `worlds/pip/`; the agent's name and pronoun through every engine prompt; the `agent` read; and the test that keeps the
engine from naming its world; **phase 2 built (0.33.0)**: the world's content is data in its pack; **phase 3 built (0.34.0)**: the agent's stats and the world's tone
are its pack's (`stats.json`, `tone.json`), over the engine's floor; **phase 4 built (0.35.0)**: the hooks a feature needs to be a
module (tools, storage, belongings, status, logged moments, requests, sessions), proved by moving the garden into a shipped module;
**phase 5a built (0.36.0)**: gathering is a shipped module on the engine's place data; **5b built (0.37.0)**: the neighbourhood module
invents the neighbour and asks them to write first; **5c built (0.38.0)**: trade (booths, prices, tills, the agent's stall and its
customers, accounts, the neighbours' wares and market days) is the shipped `trade` module; **5d built (0.39.0)**: reading is the
shipped `reading` module, on the engine's first source (`books`); **5e built (0.40.0)**: the shipped `sky` module publishes the world's
weather and season, from the `weather` source; **5f's hooks built (0.41.0)**: the `narrator` source, sources asked three deep, list and
map tool arguments, public events, `creation`, and a module's work session. Next: 5f, crafting moved onto them. Follows the modules work (DESIGN-modules.md, 0.17.0 to 0.28.0). The owner asked
(2026-11-11) for an audit: could the engine just as easily run a post-apocalyptic wasteland with monsters, radiation sickness and a
village of survivors, and what would leak over? The answer was no; this is how to get to yes. The owner's direction: **features are
modules, added to a world, not switches turned off in the engine**; and a world needs a bootstrapping guide
([GUIDE-world-pack.md](GUIDE-world-pack.md)) that says what a basic pack needs.

## Why
The module system made the engine extensible: a world can now grow rules, places, scenes, things to talk to and happenings without a
release. But the core still assumes one world: a gentle maker called Pip in a workshop with a garden, in a coastal countryside, beside
the owner's real weather and ebooks. Run a wasteland on it today and the survivor wakes in a "workshop" with tomato seeds, the narrator
introduces "a curious creature… with a home, a little garden", a monster attack is refused by the text checks ("die", "blood" and
"disaster" are banned words), and it is sunny because it is sunny outside the owner's house.

A world-neutral engine is the next step of the same idea. The engine is the **referee and the mind**; everything that makes a world
*this* world (who lives in it, what they need, what they do all day, what can go wrong, how it looks and sounds) comes from a **world
pack**: data and modules the engine loads.

## The audit (2026-11-11)
What would carry over to a wasteland unchanged:
- **The module system**: sandbox, referee, approval and trials, budgets, the builder; `voices`/`ask`/`speak` (monsters and survivors
  to talk to), `happen` (raids, storms), new places from the builder.
- **Scenes**: geometry, parts, layouts, the one renderer, anchors and live elements; the map generator (terrain noise).
- **The mind**: memory, journal, reflection, the night pass, emotions, expectations, wishes, sleep and the circadian day, self-portrait.
- **Plumbing**: channels (Matrix, web visitors), outreach, the dashboard and public view, pacing, the event log, the `pipchat` CLI.

What is content baked into the engine (already registries or lists; moving them is a data job):
- Places: `HOME = "workshop"`; a fixed woods (sticks, bark, berries) and junkyard (`gathering.WOODS`, `JUNKYARD`); place kinds and the
  words that recognise them ("marsh", "heath", "dune"); the forage and scavenge help text.
- Starting state and effects: tomato and carrot seeds (`world.STARTER_ITEMS`); world effects "a garden plot" and "a workbench"; the
  news ability's words ("radio", "aerial"); crafting abilities (precision, patience, ingenuity…).
- Scene vocabulary: props (lighthouse, beehives, loom, bunting), settings (shore, marsh, heath), looks (shawl, apron), textures (thatch,
  slate, plaster), and the shipped layouts and parts (cottages, market stalls, the library).
- Happenings content: categories (garden, pantry, kindness…), fallback texts, season weights, the find tables.
- Prose: the builder's bible ("nothing loud, cruel or dramatic; magic"), 33 guide pages that tell Pip about its workshop and
  neighbours, the narrator's system prompt and every task prompt in `gm.py`.

What is a mechanic hard-wired to this world (needs engine work):
1. **The body is hunger and energy**: two columns on the agent, with their own decay, warnings and tools (`eat`, `rest`, `sleep`).
   Radiation sickness has nowhere to live.
2. **Nothing can really hurt**: no health, injury, danger or failure; effects are mild by design (energy never below 0.1, coin losses
   a share of the purse, never the last food).
3. **The tone limits are code**: the happening checks' banned words (`DENY`, `BIG_WORDS`), the narrator's "small world… nothing more
   powerful than it is", the caps on every effect.
4. **Features are the core loop**: the garden (table, plots, `plant`/`harvest`, crop sensors), crafting (projects, stages, the dice,
   creations and their capabilities, skills), letters (neighbours who write and visit), the library (the owner's Calibre books),
   the market (booths, prices, the stall), gathering. Each is engine code with its own tables, tools, prompts and dashboard tab.
5. **The world is tied to the real one**: weather from Home Assistant, seasons from the real calendar, real books, web search,
   postcards to real friends.
6. **"Pip" is everywhere**: about 120 times in the narrator's prompts, in tool descriptions, the guide, the module API (author
   `"pip"`, the `pip` read), `PIP_READS`, and the CLI. The agent's name isn't a setting.

## Principles
- **This is a standing rule, not just a plan.** Until every phase lands, new work follows it already: no new world-specific engine code,
  tables, tools or prompt wording; features go into modules, content into data, and the engine gains only generic hooks and checks
  (CLAUDE.md, "Keep the engine generic").
- **The engine has no world in it.** Engine code and engine prompts never name a place, an item, a creature, a feature or the agent.
  A CI check enforces it (a list of forbidden words grepped in `app/` outside `worlds/`), the way `hllc check` guards the homelab.
- **A world is a pack.** Everything world-specific is data or modules in one directory, versioned with the world, chosen by the owner
  (`WORLD_PACK=worlds/pip`).
- **Features are modules.** A garden, crafting, letters, a library, a market, the weather: each is a module (or a few) a pack includes.
  A world without a garden simply doesn't include one; nothing is switched off.
- **The engine keeps the generic checks.** As with `happen`: modules propose, the engine sets the limits and amounts that keep a world
  coherent and safe, from limits the pack declares within a floor the engine never lowers.
- **The mind is the engine's.** Memory, emotions, sleep, reflection, wishes, conversation: these are what make the agent an agent in any
  world, so they stay core, worded neutrally and named by the pack.
- **Pip's world is the first pack.** The current world moves into `worlds/pip/` with no change in behaviour, and every phase below keeps
  it running the same.

## The pack
A directory with a manifest, prose, data, and modules:

```
worlds/<world>/
  world.json        name, agent (name, pronoun, kind), engine api version, the modules it includes, defaults for settings
  persona.md        who the agent is (today's PERSONA_PATH)
  narrator.md       the narrator's voice and the world in a paragraph (replaces gm.SYSTEM's world sentence)
  bible.md          the builder's world bible (today's app/builder/bible.md)
  guide/*.md        what the agent is told about how its world works (the pack's own; features bring theirs)
  stats.json        the agent's needs and conditions (below)
  items.json        item kinds, starting belongings, what can be found where
  places.json       the home and the places the world starts with, and the place kinds it can grow
  scene.json        scene vocabulary: props, settings, looks, textures, palettes
  tone.json         what words and sizes the world allows (below)
  modules/          the pack's own modules (rules, things, parts, places, features), like app/module_library/ today
```

`world.json` lists what it includes: `"modules": ["std:garden", "std:market", "std:letters", "pip:workshop-layout", ...]`. `std:` is the
engine's **standard library**: feature modules written once and shareable between worlds (a garden is a garden), configured with
`params` (what grows, how fast). A pack's own modules live in `modules/`. Both are shipped modules (author `library`): live on a clean
trial, upgraded when the pack changes them, run without the runner.

### Stats: what the agent needs
`stats.json` declares the agent's stats instead of the engine hard-coding hunger and energy (built, 0.34.0; `worlds/pip/stats.json` has
Pip's two with every field):

```json
{"energy":    {"start": 0.9, "per_hour": -0.05, "asleep_per_hour": 0.25, "resting_per_hour": 0.30, "working_per_hour": -0.05,
               "alert": {"below": 0.2}, "low_at": 0.25, "good": "high", "restored_by": ["rest", "sleep"], "floor": 0.1, "tires": true,
               "tired_below": 0.3, "scale": "0=exhausted"},
 "hunger":    {"start": 0.2, "per_hour": 0.08, "asleep_factor": 0.5, "alert": {"above": 0.8}, "low_at": 0.8, "good": "low",
               "restored_by": ["eat"], "plain_meal": 0.4, "ceiling": 0.95, "alert_feelings": {"anger": 6, "sadness": 2}, "scale": "1=starving"},
 "radiation": {"label": "rads", "start": 0.0, "per_hour": 0.0, "alert": {"above": 0.6}, "low_at": 0.6, "good": "low"}}
```

The engine keeps a `stats` table (an install from before 0.34.0 carries its hunger and energy over), changes each stat at its rate for
what the agent is doing (asleep, resting, at work), raises an alert once when it crosses its `alert` (with its `alert_feelings`), shows
the stats in the agent's prompt (`label` and `scale`), on `/status` and the dashboard, and lets modules move any of them through `affect`
(`{"radiation": -0.1}`, at most 0.1 either way). `good` says which way is better; `low_at` is how far to the bad side counts as low, and
the world spares a low agent its bad turns; `floor` and `ceiling` bound what the world (a happening) may push it to. `eat`, `rest` and
`sleep` restore what names them in `restored_by`: food by its `restores` (`{"hunger": 0.4}`) or `food_value`, a plain meal by
`plain_meal`, a rest at `resting_per_hour`. The stat marked `tires` is the one work wears down and the work dice read (`tired_below`).
Sleep stays core (the circadian day is the mind's), but what it restores is the pack's. Settings no longer carry the rates
(`SLEEP_RECOVER_PER_HOUR` is gone); `Settings.stats` overrides a stat's numbers in tests.

### Stakes: what can go wrong
A world that can hurt needs a stat that can run out and an answer to what happens then. `at_zero` names an outcome the engine knows:
`knocked_out` (the agent loses some time and wakes at home, with a happening explaining it), `weak` (only rest and eat until it
recovers), and nothing permanent: no permadeath, no lost memory. The `happen` intents gain `harm` (`{"kind": "harm", "stat": "health"}`,
sized by severity) and become pack-extensible: an intent is a stat move, an item move, a coin move, a crop move, a creation stopping, as
today, all sized by the pack's tables.

### Tone: what the world allows
`tone.json` holds what was code (built, 0.34.0; `app/tone.py`): `deny`, the words a happening may not use; `big_words`, the words too
big for a minor or neutral turn; `text`, a happening's length (`min`, `max`, `title_max`); and `sizes`, every effect's size by severity
(`stat`, `lens`, `crop_shift`, `crop_yield_good`/`_bad`, `price_units`, `coin_caps`, `found_coins`, `found_items`, `food_loss`,
`mending_qty`). Words are regular expressions matched as whole words. Pip's pack carries the old values exactly; a pack without the file
gets the engine's sizes and no words of its own. A happening's `stat` effect moves any declared stat (`{"kind": "radiation"}` or
`{"kind": "stat", "stat": "radiation"}`), its way set by the tone and the stat's `good`.

The engine keeps a **floor** a pack cannot lower: no sexual content, nothing that encourages self-harm, nothing about real people,
real-world news never presented as the world's. It is in three places no pack touches: the narrator's fixed instructions
(`world_pack.FLOOR_RULES`, after every pack's own), the words every happening is checked against (`tone.FLOOR_WORDS`, added to any pack's
`deny`), and the name check that turns down any name the world didn't offer. A wasteland can say "blood" and lose a fight; it still
can't be cruel for its own sake. How often bad things come stays with the happenings module's params.

### Places, items and scenes
- `places.json`: the home (its key and label: `"shelter"`, `"workshop"`), the places a world starts with, and the place kinds it can grow
  (today's `PlaceKind` registry, with its words, verbs and loot), plus walking distances. The map and walking stay core.
- `items.json`: item kinds (`tool`, `material`, `food`, `seed` today; `ammo`, `medicine`, `scrap` elsewhere), starting belongings, and the
  find tables (today's `WOODS`, `JUNKYARD`).
- `scene.json`: props, settings, looks, textures and palettes the GM may pick from and the renderer draws. Textures are generated in the
  browser today (`art.js`); a pack adds its own as parameterised generators or small images.

### Real-world links are sources
Weather from Home Assistant, the owner's books, web search and postcards to friends need I/O, which modules never have. They become
**sources**: small engine adapters the owner configures (they are trusted code, like the channels), each exposing read-only data to
modules (`weather`, `books`) or one narrow action (`search`, `postcard`). A pack's modules decide whether and how the world uses them:
Pip's world reads the real weather; a wasteland's weather module invents dust storms and acid rain and publishes them as the world's
weather; its library module (a ruined archive) might read the owner's books, or a list it ships.

## Features as modules
What each feature needs that modules can't do yet is the real work. The pattern so far (workings, customers, happenings) holds: find the
generic hook, move the feature onto it, keep the engine's version as the fallback until the module is live everywhere, then remove it.

**Hooks still missing** (generic; none names a feature):
1. **Tools**: a module offers the agent tools, not just offers on a thing: `{"tools": [{"name": "plant", "help": "...", "params":
   {JSON schema}, "where": "home"}]}`, answered by `on_action`. The engine lists them with its own tools, checks the arguments against the
   schema, and shows them only where they apply. (Today a module can only add `use_item` actions to a creation.)
2. **Sessions**: a tool may start something that takes real time (work, reading, gathering, walking a patrol): `{"session": {"minutes":
   45, "kind": "work", "label": "..."}}`; the agent is busy until it ends, a session ending calls `on_time`, resting or sleeping
   interrupts it. Today's work, read, gather and walk sessions are this, special-cased.
3. **Storage**: a module's state is one JSON object of 16 KB. A garden, a project list, letters and bookmarks need more: per-module
   **collections** (`{"store": {"plots": {"3": {...}}}}`, read back as `ctx["store"]`), capped in size, listed on the module's page.
4. **Belongings**: `give`/`take` items and coins with caps in the manifest (generalising `find`, `consume` and `sell`), so a garden can
   take a seed and give a harvest, and a market can trade.
5. **Status**: lines the agent sees every time while they hold ("Your garden: plot 2, peas, ripe tomorrow"), not just once
   (`perceive`): `{"status": ["..."]}`, replaced on each call, shown in a section of the prompt named by the module.
6. **Structured asks**: `ask` with a JSON schema for the answer (a project's stages, a letter's reply and what it mentions), checked by
   the engine before `on_answer`, as `gm.ask` does for the engine today.
7. **Characters**: modules can create people (a name, a look, a home place, a persona kept by the engine, not shown to other modules),
   not just voices; letters and visits are then a module talking as them.
8. **Views**: a module can add a panel to the dashboard (a table or a list from its store and status), so the Work tab, the market and
   the garden don't need engine pages.

**The features, in the order they could move** (each one proves some of the hooks above):
| Feature | Today | Needs | Notes |
|---|---|---|---|
| Market (booths, buying, selling, prices) | `market.py`, `buy`/`sell`/`pay`/`browse`, prices and tills | tools, belongings, storage, status | Stall customers already moved (0.26.0) |
| Garden | `garden` table, `plant`/`harvest`, plots, crop sensors | tools, storage, belongings, status | Small; a good first proof of tools |
| Gathering | `gather`, `place_finds`, loot tables | tools, sessions, belongings | Find tables move to `items.json` |
| Letters and neighbours | `neighbors.py`, `write_letter`, visits, residents | characters, tools, structured asks | Visits in person build on voices (0.27.0) |
| Library | `read`, `settle`, bookmarks, Calibre | the `books` source, sessions, storage | The source stays engine code |
| Weather and calendar | `weather.py` (Home Assistant), `season_of` | the `weather` source, a published world weather and season | The scene and happenings read the published values |
| Crafting | projects, stages, the dice, experiments, creations, skills, abilities | all of the above | The biggest; creations' workings already moved (0.25.0, 0.27.0) |
| Drawing and writing | `draw`, `look`, `write_piece`, works | tools, storage | Close to core (the mind's expression); may stay |
| Web search, postcards | tools and outreach | the `search` and `postcard` sources | A pack chooses whether its agent has them |

What stays core: the loop, the mind (memory, journal, reflection, night pass, emotions, expectations, wishes, notes, `feel`, `settle`,
`recall`), sleep and the day, stats and stakes, belongings and the purse, places, walking and the map, characters and conversation, the
module system, happenings' checks, the world view's renderer, channels and visitors, the dashboard.

## Phase 4 in detail
The garden is the proof: nothing in the engine may know what a plot, a seed or a harvest is once it moves. What it needs, and the generic
hook that gives it:

| The garden needs | The hook (4a) |
|---|---|
| `plant` and `harvest`, at home | **tools**: the manifest's `tools` (`[{name, help, params, where}]`, `params` a small JSON schema, `where` one of `anywhere`, `home` or a place key). The engine offers them with its own tools where they apply, checks the arguments against the schema, logs each use as a `tool` event like its own, and runs the module's `on_action` with `{"tool": name, "args": {...}}`; the call's `reply` is the tool's result. A name may not shadow an engine tool or another live module's. |
| its plots, kept between calls | **storage**: `store` (`{"plots": {"2": {...}, "3": null}}`): per-module collections of JSON values by key, merged on each call (`null` deletes), read back as `ctx["store"]`. Kept by the module's name, so a new version keeps them; 64 KB a module, 200 keys a collection. |
| a seed taken, a harvest given | **belongings**: `take` (`[{item, qty}]`, only what the agent has) and `give` (`[{item, qty, kind, description?, attrs?}]`), each capped by the manifest's `belongings` (`{"takes": [kinds], "gives": [kinds], "most": n}`). The `items` read carries each item's `attrs`, so a module can read a seed's crop and growing time. A given item's `attrs` are plain values; `restores` may only name the world's stats. |
| "Your garden: plot 2, peas, ripe in an hour" every time | **status**: `status` (`{title, lines, ready?, next_at?}`), replaced on each call and shown in its own section of the prompt every tick, on `/status`, and on the dashboard. `ready` says something waits for the agent now; `next_at` when something next will; the free-time line ("nothing needs you for about...") reads them, not the garden. |
| to wake the agent and be remembered when a crop ripens | `schedule` and `wake`, as today, and **kinds for `log`**: `log` may be `{text, kind, feel?}`. The event is `module` with the module's name and the kind; a pack's `content.json` `module_firsts` (`{"garden:ripe": "had a crop ripen"}`) makes the first one a first, and `feel` moves the agent's emotions a little (at most 5 each). |
| happenings that hurry, slow, shrink or ruin a crop; a helper that hurries them; a world effect that clears a plot | **requests**: one module asks another to change itself. A module lists what it `answers` (`{"hurry": "help growing crops along"}`) and gets `on_request` (`{"what", "args", "from", "tone"?, "severity"?, "apply"}`); its `reply` says what changed. Another module proposes `request` (`{module, what, args}`); a happening's effect may be `{"kind": "request", "module", "what", "args"}` (asked once to describe, `apply: false`, before the words are written, then once to apply); a world effect's `does` may be `request:<module>:<what>`. The engine checks the request is to a live module that answers it; the module answering is the authority on its own state, sized by the severity it is given. |
| the scene's plots and the dashboard's garden | **published facts**, as today, and status: the world view carries the live modules' `facts` (`facts.garden.plots`), which the renderer's plots read; the dashboard shows each module's status. |
| sessions | Not the garden's, but in the list: **sessions**. `on_action` may start one (`{"session": {"minutes", "label", "working"?}}`): the agent is busy with `label` until it ends, then the module's `on_time` runs with `{"session": {"label", "interrupted"}}`; resting or sleeping ends it early. Gathering is its first user (phase 5). |

**4b, the move.** A shipped `garden` module: plots in its store (`GARDEN_PLOTS`, `GARDEN_PLOTS_MAX` and `GROW_SPEED` become its params,
as `HAPPENINGS_*` did), `plant`/`harvest` as its tools, the weather's effect on growing as its own table, its status lines, and `answers`
for `hurry`, `crop` (a happening's `time`, `yield`, `ruin`, sized by severity) and `add_plot`. The happenings module asks it for crop
turns; a creation's `hurry_crops` helper asks it to hurry; the sensor `crop_ripe` reads its facts. On first install the engine moves an
existing garden table into its store (a one-time migration, the only place the old table is named) and drops the table. Then `plant`,
`harvest`, `state.garden()`, the `garden` read and proposal, the garden prompt lines, `/garden` and the dashboard's own garden panel are
gone; `TOOLS` naming `plant` or `harvest` is fine (a tool name the engine doesn't have is skipped, with a warning).

**As built (0.35.0), and what the move added.** All of the above, plus what the garden turned out to need, each generic:
- a status line may say `{in:<time>}`, which the engine words as "45 min" or "3 hours" whenever it is shown, so "ready in about..." is
  never stale between the module's calls;
- `on_request` may `refuse` with a reason ("that crop is as good as ripe"), which is what the asker, a happening or a world effect hears;
- a tool may have a `first` ("planted something"): its first use is a first, each use that changes something is a diary moment, and a
  use that changes nothing (a harvest with nothing ripe) is a no-op, like the engine's own;
- a module tool's use is a public event with its result (the engine's own world actions are);
- a happening may mention any name a live module publishes in its facts' `names` (the garden's crops);
- the world view carries every live module's facts (`facts.garden.plots`, which the scene's plots read) and `/standing` serves the status
  sections (the dashboard's "Going on" card replaces its garden card);
- the weather's effect on growing is the module's own table; `weather.py` only words the conditions;
- the crop sizes left `tone.json` for the garden module; the happenings module asks it (`request` to `crop`), a creation's `hurry_crops`
  helper asks it (`hurry`), the sensor `crop_ripe` reads its facts, and Pip's world's `garden_plot` effect is `request:garden:add_plot`;
- the pack names the garden's first ripening (`module_firsts`: `garden:ripe`, the same first as before, so it isn't new again).

Still the engine's, for phase 5: seeds as an item kind (their `crop`, growing time and yield attributes, and scooping seeds out of food
with `use_item`), and the creation capabilities that name the garden (crafting moves last).

## Phase 5 in detail
**5a, gathering.** What a place holds stays the engine's, as place data any feature may use: its find table (the pack's `items.json`
`finds`, or an invented place's own), how picked over it is (a stock that use draws down and time refills, at the rates of the place's
kind), and a glimpse of it. The market's shelves and gathering draw on the same stock, which is why it is the place's. Gathering itself
moves into a shipped `gathering` module: the `gather` tool, the session, the haul, practice, and the words. What it needs, each generic:
- **the `here` read**: the place the agent is at (none while walking): its key, label, kind, whether it is open, its find table, its
  verbs, its stock and the kind's numbers (session lengths, capacity, refill, whether it keeps shop hours and trades);
- **the `abilities` read** (levels) and **`practice`** (`{ability: minutes}`, abilities the world knows, at most 240 a call);
- **`deplete`** (`{amount, place?}`): draw down a place's stock;
- **`doing`** (`{activity, description}`): what the agent is doing, as the engine's own tools set it;
- **`give` at a place** (`"at": key`): what was found where, so `where_to` remembers it;
- **a tool offered where a place lists it** (`"where": "offered"`): wherever a place's verbs include the tool's name, worded the place's
  own way (the woods' "Forage in the woods for 15-60 minutes...");
- **a moment's `items` and `tool`** in `log`: what came of it (a first for each thing found; the agent's sense of what its tools are
  good for reads it), and a moment is shown among recent events and can be recalled;
- **`owe`** (`{place, items}`), until the market moved (5c): what was taken at a shop went on account there. Since 0.38.0 gathering
  asks `trade` to put it on account (a `request` for `owe`, only when the `answers` read says trade is live to answer it).
A session's label now reads as what the agent is doing ("you're out foraging at the woods (about 20 min left)").

**5b, neighbours.** Characters and conversation stay the engine's, and so do letters: a letter is conversation at a distance, and a
character answers one with the same machinery as in person (their persona, kept private; what they've told the agent; their plans;
what's been said), as a wasteland's radio would. What moves is the neighbour feature: inventing someone who lives nearby, and when they
write first. Into a shipped `neighborhood` module, on two generic hooks:
- **structured asks**: `ask` may carry a `schema` (`{properties, required}`: strings, numbers, whole numbers, true/false, and objects of
  strings); the answer comes back checked, as `ctx["answer"]["data"]` (none if the model's answer didn't fit). With `mentions: true` the
  engine adds how a character may tell the agent about a place, and passes back `mentions_place`;
- **characters**: `character` (`{name, kind: "neighbor", persona, about, letter?, mentions_place?}`) brings someone into the world (never
  a name already in it, or the agent's); their first letter is on its way. `letter` (`{from}`) asks a neighbour to write to the agent
  (the engine writes it, as it answers letters, when none of theirs is already on the way).
The engine no longer invents a neighbour or keeps their writing schedule; `NEIGHBOR` and `NEIGHBOR_WRITES_EVERY_HOURS` become the
module's params. A neighbour's wares waited for the market (5c).

**5c, trade.** What stays the engine's: the purse (coins), belongings, the agent's creations and works (who owns them), places and what
they hold (`finds.goods`: a place's find table, or a trading place's own stock), characters and where they live. Everything that is
trade moves into a shipped `trade` module (`module_library/trade.py`, `trade.json`): `browse`, `buy`, `sell` and `pay` at shops,
markets and neighbours' homes; prices (a base from the thing, a local factor that moves 4% a unit traded and drifts back 10% a day, a
daily mood); a booth's daily till and stock; the agent's stall and its customers (the old `stall-customers` rule is folded in); what's
on account; a neighbour's wares (asked for once, as a structured ask) and their market day, when they keep a stall at the market
instead of being at home; and a happening's turn in a price. Its store keeps `prices`, `tills`, `stall`, `accounts` and `wares`, each
keyed by a short hash of the names (`slot`). The generic hooks it proved:
- **`coins`** (a signed whole number, at most 500 a call, never more than the agent has), with the manifest's `belongings.coins`;
- **`part_with`** (`{creation, to}`): one of the agent's creations is someone else's now (sold to a keeper, or off the stall);
- **`whereabouts`** (`{name: {at, doing?}}`): where a character is just now, if not at home (`places.place_of` reads it, so the agent
  meets a neighbour at their stall); **`notes`** (`{name: line}`): what the module says about a character, read where the engine
  describes them (the neighbours' list, their letters, the look of their home);
- **tools that share an engine tool's name**: where the module's tool applies, it is the one the agent sees and uses (`browse` at a
  shop is trade's; at the library it is still the engine's); `where` may be a list, and `kinds` limits a tool to kinds of place;
- **reads**: `answers` (what each live module answers), `made` (the agent's works), a person's `about` and a neighbour's `home`, an
  item's `description`, a creation's `quality` and `description`, a place's `trades`, `stalls`, `hours` and `goods`, `here`'s `stalls`
  and its `weights` (what the world's finds weigh), and `time`'s `utc_offset` (the sandbox can't read the local clock);
- **structured asks** may want a list of objects (`{type: array, items: {type: object, properties}}`);
- **two published conventions** the engine reads: `scene` (`{place: {booths, stall, lives_here}}`, merged into a place's scene) and
  `for_sale` (`[[place, item, price, whose]]`: where a wished-for thing can be had, and what a neighbour's letter may offer);
- a given thing the world knows by its name and kind gets the world's attributes (carrot seeds bought from a neighbour plant like the
  ones Pip could find); a tool's reply may run to 1,500 characters; a module's source to 40,000; what it publishes to 8,000 bytes.
The engine's `market.py`, the `buy`, `sell` and `pay` tools, the `stalls` read and the `sell` and `owe` proposals, the happenings' `price`
intent and the tone's `price_units` are gone. `CHARACTER_BOOTHS` is the module's `wares` param. An older install's prices, tills, stall,
accounts and wares move into trade's store once, and the old tables go.

**5d, the library.** The owner's books stay engine code: the providers (`library.py`, Calibre or a folder), the format readers, and the
narrator's condensing, so raw text never reaches a module or the prompt. They become the first **source** (`sources.py`): trusted
adapters a module may ask but never reach. A module names its `sources`, a hook proposes `{"source": {name, op, args}}`, and the engine
runs it and calls the module's `on_source` at once with the answer, within the same call, so a tool's reply can come from it (`on_source`
has the rights of the hook that asked). `books` does `search`, `wander`, `find` and `read` (the next stretch from a bookmark, condensed).
Reading moves into a shipped `reading` module (the name `library` is the library's layout): `browse` and `read` at the library, a reading
session of real time, bookmarks in its store (an older install's move there once), the books partway through as a status at the
library, the bookmarks published for the dashboard, and what was read told as a moment (finishing a book is the same first as before:
`module_firsts` may name the old one). A module whose sources aren't here offers no tools (no books, no reading). The engine's `read`
tool, its reading session and bookmarks table are gone; its `browse` only looks over the junkyard. `settle`, listed with the library in
the table above, is the mind's and stays core.

**5e, weather and calendar.** The provider stays engine code (`weather.py`, Home Assistant; the reading kept and fetched at most every ten
minutes) as the second source, `weather` (op `now`: `{reading}`, none without a fresh one). A shipped `sky` module asks it every ten
minutes and publishes the world's `weather` (`{condition, temp, unit, daylight, next_rising, next_setting}`) and `season` (from the
date, the right way round for its `hemisphere` param, `HEMISPHERE`), and shows the agent an "Outside" status. The engine reads what is
published (`modules.published`, `modules.world_season`): the scene's moment, the `weather` and `time` reads, happenings and layouts.
Without a module publishing a season, the engine still reckons one from the date (until phase 7); without one publishing the weather,
there is none. The engine's weather line, its wording of conditions and its refresh in the loop are gone. A wasteland's own sky module
invents ash days and publishes them the same way, asking no source.

**5f, crafting (planned 2026-11-13).** The biggest feature: projects (plans, stages, the dice, the narrator's judgement, materials,
expectations), experiments, plan revision, craft skills, and making a creation at the end. It moves over four releases, each a working
world, because so much reads what it logs: memory (recall, importance, day stats), firsts, emotions, the turning-point detector,
capabilities, the night pass (pausing and resuming projects), reminders, the dashboard's Work tab and feed, the scene (the work pose).
What stays core: the creations table and everything about a creation once made (running, tending, `use_item`, programs, workings,
giving it away); the agent's abilities and `practice`; sessions; belongings.
The owner chose (2026-11-13) to ship the hooks first, as their own release (0.41.0), then move crafting in a second.
Projects, experiments, plan revisions and the finished creation all work on the same project records, so once those records move into
a module's store, all of crafting has to move in one release: it can't be split by tool. What it needs, each generic:
- **the `narrator` source** (built): op `ask` (`{prompt, schema}`) has the narrator answer within the call, as data checked against the
  schema, so a tool's reply can rest on the narrator's judgement (`start_project`'s plan review); and a source asked again from
  `on_source`, a few deep (a session's end is judged, then narrated, then, at a project's end, the thing designed).
- **tool arguments that are lists and maps**: `start_project`'s `steps` (a list of `{name, minutes, materials}`, `materials` a map of
  name to count), as the engine's tool takes them today.
- **public events**: a shipped module logs an event of a public kind its manifest names (`logs: ["work", "experiment",
  "plan_revised"]`), with that kind's fields, and the expectations it settles; so memory, firsts, emotions, the turning-point detector,
  day stats, capabilities and the feed read it as they read the engine's own. (Phase 7 makes those readers the pack's.)
- **`creation`**: a module makes one of the agent's creations (`{name, description, quality, capabilities, quirks}`); the engine
  checks it as `sanitize_spec` does, applies world effects, logs `creation_made`, and offers its workings.
- **requests from the engine**: the night pass asks a module (`pause`, `resume`) instead of writing a table (with the move: the
  mechanism, `ask_module`, is already there).
- a module session that is work shows as work (the scene's pose, reminders' cue, the memory's context): a session may say what it is
  `about` (a project's name), and a working one poses as work.
Then the `crafting` module: the six tools, the dice and the narrator's rulings, materials, craft skills (its store) and ability practice,
expectations, the projects published for the dashboard and shown as status; the engine's projects.py, its tools, its narrator prompts for
crafting, the project and skill tables and the `work`/`experiment` session kinds removed; an older install's projects and skills moved
into the module's store once. About 3,000 lines of tests read or drive crafting directly and move with it.

## Phases
1. **The pack, with Pip's world in it.** *1a (0.31.0)*: `app/world_pack.py` loads `world.json` (name; the agent's name, pronoun one of
   it/she/he/they, and kind; `api` 1), and the pack's `persona.md` (the default when `PERSONA_PATH` has no file; with none, "You are
   <name>."), `narrator.md` (the narrator's system prompt is the pack's paragraph, then the engine's `NARRATOR_RULES`; for Pip's world it is
   the old prompt word for word), `bible.md` (unless `WORLD_BIBLE_PATH`) and `guide/<topic>.md` (a page the pack lacks is left out). The
   image ships `worlds/`. *1b and 1c (0.32.0)*: every engine string that named Pip now names the pack's agent (`world_pack.Agent`:
   `name`, `possessive`, and the pronoun's `they`, `them`, `their`, `themself`). Sentences whose subject is the agent use its name, so
   verbs agree in any world; a pronoun's subject form appears only before a verb that agrees with all of them (a past tense, "could").
   Code with no settings at hand asks `world_pack.active()` (one engine runs one world; the agent sets it at start). The shipped
   modules' descriptions moved into their own manifests (`reason`), as world content. The module API's `pip` read is now `agent` and
   `speak`'s `to_pip` is `to_agent`; the old names still work for modules already live. `tests/test_engine_neutral.py` scans every
   string literal in the engine (not comments or docstrings) and the builder's API page, and fails on "Pip"; it also runs the
   narrator, the help text, the builder's page and a refusal for another world's agent. Still named for Pip: identifiers (the author
   `"pip"`, Pip's programs, `pipchat`), anchor tags (`pip`, `pip-stall`), and world content such as "workshop" and "garden", which
   phase 2 moves out. *Then:* `worlds/pip/` holds the persona, narrator, bible and guide; `WORLD_PACK` selects it; the agent's
   name and pronoun come from `world.json` and every engine prompt is written around them; the `pip` read becomes `agent` (the old name
   kept as an alias for live modules). No change in behaviour; the CI check starts with the prompts.
2. **Data out of code.** *Built (0.33.0)*: `scene.json` (looks and their hints, props, scene details, settings and the words for them,
   coastal words), `items.json` (item kinds, seed and food defaults, starting belongings, find tables and what gathering there is
   called), `places.json` (the home: key, description, offers, aliases, what it's called; the library; the starting places with their
   kind and tag; the place-kind registry; the words for trades, reserved names and what a place may be), `content.json` (world effects,
   abilities, crafting's abilities, the happening firsts), and `world.json`'s `agent.lives`. Engine code reads them through functions
   (`world.kinds()`, `place_kinds.registry()`, `places.home_key()`, `looks.vocab()`...); the old constant names still answer, from the
   active world. `WILD_PLACES` now defaults to all of a pack's starting places. A world effect names what it does from a small engine
   list (`add_plot`, `add_project_slot`) until the garden and crafting are modules. Still in the engine: feature code and its words (the
   garden's tools, crafting), and the renderer's own vocabulary (textures, sprites). *Originally:* Place kinds, item kinds and tables, starting belongings, scene vocabulary, happenings' categories and tables,
   world effects and abilities move to the pack's JSON. Behaviour unchanged.
3. **Stats and tone.** *Built (0.34.0).* Hunger and energy are pack-declared stats in a `stats` table; `affect` and a happening's `stat`
   effect take any stat; `tone.json` replaces the hard-coded checks and sizes (with the engine's floor); `eat`/`rest`/`sleep` follow
   `restored_by`.
4. **Tools, sessions, storage, belongings, status.** The hooks that let a feature be a module, proved on the **garden**. In two steps
   (see "Phase 4 in detail" below): *4a* the hooks, each tested with a small module; *4b* the garden moves into a shipped `garden`
   module and the engine's garden (its table, tools, prompt lines, the `garden` read and proposal) is removed. *Built together (0.35.0).* The market, which the
   first plan also named here, moves with the other features in phase 5: it needs `characters` for its stallholders too.
5. **Features move.** One feature a release, each proving the hooks it needs (see "Phase 5 in detail"): *5a* gathering, *5b* neighbours
   (characters, structured asks), *5c* the market (it needs the neighbours' stalls), *5d* the library (sources), *5e* weather and
   calendar (sources), *5f* crafting. Each removes the engine's version when its module is live, as the garden did.
6. **Stakes and a second world.** Health and `at_zero`, `harm`; then a small **wasteland pack** as the test: a shelter, scavenging,
   radiation, a village of survivors as voices, raids as happenings, no garden. Its CI run (a day of simulated ticks with a fake model)
   proves the engine has no Pip in it.
7. **Remove the fallbacks.** The engine's built-in workings, companions, customers, happenings' dice and each moved feature.

Every phase is a release with tests, mutation testing and Pip's world running unchanged on it.

## Risks and open questions
- **Size.** Crafting, letters and the market are most of the engine's code and most of what makes Pip's days. Moving them is the bulk of
  the work; doing it as modules means the hooks must be good enough for real features, not just small rules. That is the point, and the
  risk: if a feature can't be expressed, the hook is wrong, and finding out is the work.
- **Prompt quality.** The engine's prompts are tuned to Pip's world. Written around a name and the pack's narrator, they must stay as good;
  compare transcripts of the same day before and after phase 1.
- **Modules' cost.** Features as modules run in the sandbox: a subprocess per hook call today. A tick that runs every feature may need a
  warm runner (a pool of interpreters) rather than a process per call.
- **Shared standard library.** `std:` modules are engine-shipped code that packs configure; a pack may also fork one into its own
  `modules/`. Which features are generic enough for `std:` (a garden, a market) and which are a world's own (Pip's crafting) is decided
  feature by feature.
- **Migration of a live world.** Pip's world has months of data in engine tables (garden, projects, letters). Moving a feature to a
  module needs a one-time migration into the module's store, kept reversible.
- **Who writes a pack.** A person, with the guide; later the builder could draft one from a description, with the owner approving.
