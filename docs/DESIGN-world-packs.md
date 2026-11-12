# Design: world packs (a world-neutral engine)

Status (2026-11-11): designed; **phase 1 built (0.31.0, 0.32.0)**: the pack loader, `WORLD_PACK`, Pip's world's persona, narrator, bible
and guide in `worlds/pip/`; the agent's name and pronoun through every engine prompt; the `agent` read; and the test that keeps the
engine from naming its world; **phase 2 built (0.33.0)**: the world's content is data in its pack. Next: phase 3 (stats and tone). Follows the modules work (DESIGN-modules.md, 0.17.0 to 0.28.0). The owner asked
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
`stats.json` declares the agent's stats instead of the engine hard-coding hunger and energy:

```json
{"energy":    {"start": 1.0, "decay_per_hour": 0.03, "low": 0.25, "restored_by": ["rest", "sleep"], "floor": 0.1},
 "hunger":    {"start": 0.0, "rise_per_hour": 0.04, "high": 0.8, "restored_by": ["eat"]},
 "radiation": {"start": 0.0, "rise_per_hour": 0, "high": 0.6, "shown": "radiation sickness", "restored_by": ["use:rad pills"]},
 "health":    {"start": 1.0, "low": 0.3, "at_zero": "knocked_out"}}
```

The engine keeps a stats table, applies decay, warns at thresholds (today's `apply_decay` alerts), shows them in the agent's prompt and on
the dashboard, and lets modules move them through a generalised `affect` (`{"stat": "radiation", "delta": 0.1}`) within per-stat caps.
`eat`, `rest` and `sleep` become what a stat's `restored_by` says: an item attribute (`food_value` becomes `restores: {hunger: 0.4}`),
a rest, sleep. Sleep stays core (the circadian day is the mind's), but what it restores is the pack's.

### Stakes: what can go wrong
A world that can hurt needs a stat that can run out and an answer to what happens then. `at_zero` names an outcome the engine knows:
`knocked_out` (the agent loses some time and wakes at home, with a happening explaining it), `weak` (only rest and eat until it
recovers), and nothing permanent: no permadeath, no lost memory. The `happen` intents gain `harm` (`{"kind": "harm", "stat": "health"}`,
sized by severity) and become pack-extensible: an intent is a stat move, an item move, a coin move, a crop move, a creation stopping, as
today, all sized by the pack's tables.

### Tone: what the world allows
`tone.json` holds what is code today: words the happening checks refuse, which sizes may use big words, the caps on each effect by
severity, how often bad things may come. Pip's pack carries today's values exactly. The engine keeps a **floor** a pack cannot lower:
no sexual content, nothing that encourages self-harm, nothing aimed at real people, real-world news never presented as the world's.
A wasteland can say "blood" and lose a fight; it still can't be cruel for its own sake (the narrator and the builder are told so in the
engine's fixed instructions, not the pack's).

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
3. **Stats and tone.** Hunger and energy become pack-declared stats; `affect` takes any stat; `tone.json` replaces the hard-coded checks
   (with the engine's floor); `eat`/`rest` follow `restored_by`.
4. **Tools, sessions, storage, belongings, status.** The hooks that let a feature be a module, proved on the **garden** (and the market).
5. **Features move.** Gathering, letters and neighbours (with characters), the library (with sources), weather and calendar, then
   crafting. Each keeps the engine's version as a fallback until it's live, then removes it.
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
