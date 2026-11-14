# Engine audit: what still assumes Pip's world (2026-11-14)

Status: **audit, decisions taken (2026-11-14), nothing built yet.** Written after the world-packs plan finished (DESIGN-world-packs.md, phases 1-7, 0.31.0 to 0.46.0).
The owner asked whether one more pass was needed: over the module architecture (the hooks it offers) and over engine code that still
expects a workflow specific to Pip. This is that pass: what was checked, what was found, the owner's decisions, and the order of releases.

## Decisions (the owner, 2026-11-14)
- **The engine is not to be made anemic.** What many worlds would share and is hard to get right stays the engine's, built to be
  extended by modules. Neighbour visits and talk scenes are the example: they don't move into a module as they are; the machinery (a
  character present, a scene of talk, what is remembered of it, letters there and back) stays the engine's and works for any character a
  module brings, so a world can simulate a whole village of people talking through the same scenes. Modules decide who exists and what
  they do (C1).
- **The dashboard is Pip's world's for now.** The engine may later offer an abstract dashboard and components that worlds reuse or plug
  their own panels into, likely on a framework; that is a bigger refactor, not part of this plan. Until then the dashboard page moves into
  Pip's pack, and the engine serves the active pack's page (B5).
- **`pip` is renamed completely.** No aliases remain in the engine: the `pip` read, the `"pip"` author, the scene's `pip` key and anchor,
  and the engine's own docstrings and comments, with a migration for what is stored (A4).

## Verdict
Nothing the engine *says* is Pip's any more: no string literal in `app/` outside the shipped modules names Pip, and `tests/test_ashfall.py`
fails if anything of Pip's world reaches the model or the chat in a simulated wasteland day. What remains is in how the engine is *built*:
a handful of features are still engine code a world can't change or leave out (neighbours and letters, the creation capabilities, the
happenings' effect vocabulary), several pieces of plumbing know one feature by name (the night pass, the guide, the dashboard, a few
places), and the module API grew one proposal at a time and now has overlaps. None of it blocks Ashfall; all of it would block a third
world that wants something different in those places. Worth doing, in small releases, with the API consolidation last.

## How this was checked
- Every string literal in `app/` (docstrings and comments excluded), scanned for the words of Pip's world: Pip, workshop, garden, crop,
  neighbour, letter, postcard, library, clock, hunger, energy, project.
- The Ashfall day (`tests/test_ashfall.py`, three fixed dates; 30 more by hand), which records every word sent to the agent's model and
  the narrator and every chat command's answer.
- An inventory of what the shipped modules (`app/module_library/`) and Ashfall's own (`worlds/ashfall/modules/`) actually use: hooks,
  reads, proposals and manifest keys.
- The engine's tools and their scopes (`tools.REGISTRY`, `tools.SCOPES`), the endpoints in `app/main.py`, the dashboard's calls
  (`web/app.js`), and the special cases in places, the night pass, the guide and memory.

## What is already the world's
The agent (name, pronoun, kind, persona), the narrator's voice and bible, stats and stakes, tone and its sizes, items and find tables,
places and their kinds, scenes, the guide's text, the world's modules (`world.json`), the season and weather (the sky module), and every
moved feature: gathering, the garden, trade, reading, crafting, the neighbourhood's invention, happenings' dice. A module's events say how
the engine reads them (0.46.0). The engine keeps, by design: the loop, memory, emotions, sleep, sessions, belongings and coins, people's
identity, places and walking, the map, creations as things, the module runtime and sandbox, sources and channels, the narrator, the floor.

## Findings

### A. Small leaks (one release)
- **A1. Stats named in tools.** `eat` ("lowers hunger") and `rest` ("recover energy") describe themselves in Pip's stats; the note checks
  refuse "hunger/energy numbers" with a regex of those two words (`tools.py`, `STAT_NUMBERS`). *Fix:* word both from the declared stats
  (`restored_by`, labels); build the regex from the world's stat labels.
- **A2. Old columns.** The `agent` table still has `hunger` and `energy` columns from before stats were the world's (`state.py`, schema and
  the first insert). *Fix:* drop them (SQLite's `DROP COLUMN`), as 0.45.0 dropped the old feature tables.
- **A3. Leftovers of crafting.** `undo_decision` says "a paused project"; reflection's material still words a `start_project` tool call
  (`memory.py`, `material`), now duplicating crafting's `project_started` event; the `/projects` chat command and the `projects` entry in
  `/help` are crafting's (`commands.py`). *Fix:* word `undo_decision` from what the night pass did; drop the tool branch; see B5 for commands.
- **A4. Pip in names.** The module author `"pip"` (the agent's own programs), `PIP_READS`, the `pip` read (kept as the old name of `agent`;
  no shipped module uses it), the scene JSON's `pip` key (`world_view.py`, `world/map.js`), the layouts' `pip` anchor (the shipped
  layouts, Ashfall's `shelter`, `world/layout.js`), and "Pip" in about 350 of the engine's docstrings, comments and identifiers. *Fix
  (decided):* rename to `agent` everywhere in the engine, with no alias: a migration rewrites stored rows (a module's `author`, the
  `"id": "pip"` anchor in a world-made layout's source, which is then rebuilt); a manifest that reads `pip` is refused. Pip's live world
  has no programs of the agent's own, and its 7 live layouts with that anchor are shipped ones that change with the release. The
  dashboard's "Pip"s are Pip's world's once the page is its pack's (B5).
- **A5. Legacy fields.** `public_view.py` keeps fields for `garden` events from before 0.35.0. *Fix:* drop (installs older than 0.44 are
  refused anyway).

### B. Plumbing that knows one feature by name
- **B1. The night pass is crafting's.** Its facts list crafting's published projects (`nightpass.py`, `_projects`, `_limit`), its ops
  include `pause_project` and `resume_project`, citations use `p<id>`, and a focus can refer to a project. A world whose plans are
  something else (repairs, expeditions) can't have them tidied overnight. *Fix:* a module publishes the things the pass may look after
  (`plans`: `{id, label, status, last_touched}`) and answers what may be done to them (`pause`, `resume`); the pass's ops become
  "ask module M to do X to its item I", cited as `m:<module>:<id>`, and undone by asking the opposite.
- **B2. The guide's pages are registered in the engine.** `app/guide/__init__.py` lists every page by name and gates each on engine tool
  names (`projects` on `start_project`, `market` on `buy`/`sell`/`pay`, `library` on `browse`/`read`). A pack page the list doesn't name
  is never shown: Ashfall's `stakes` page needed an engine change. *Fix:* each page says when it applies (a front-matter line: the tools,
  settings or stats it needs, and its place in the order), and the engine keeps only the gate predicates.
- **B3. Special places.** `home`, `library` and neighbours' homes are special-cased: the map's kind (`worldmap.py`), the layouts' kinds
  (`layouts.KINDS` includes `library`, `neighbor`, `shop`, `market`), the library place from `places.json` plus `LIBRARY_PATH`
  (`places.py`), and a neighbour's home as a name ending in "'s home" (`HOME_SUFFIX`). *Fix:* every place kind comes from the pack; the
  library is a place of a kind whose availability the `books` source says; a character's home is a place the character record points to,
  not a suffix.
- **B4. Tool scopes by place key.** `browse` is scoped to `junkyard` (0.44.1 added the place-kind verbs as a way round). *Fix:* engine
  tools scope by role (`home`, `anywhere`, `offered`: where a place's kind lists the verb), never by a place's key.
- **B5. The dashboard and feature endpoints.** `/projects` (crafting), `/letters` (neighbours) and `/library/bookmarks` (reading) are
  endpoints of one feature each; the dashboard's Work tab renders projects and the World tab letters; `/projects` is a chat command. The
  generic mechanism exists: `/standing` shows every module's status. *Fix (decided):* the dashboard page (`web/index.html`, `app.js`,
  `style.css`) moves into Pip's pack (`worlds/pip/web/`), and the engine serves the active pack's `web/` at `/ui` (a pack without one gets
  a plain page of the agent's state and its modules' standing). The scene and map renderer (`web/world/`, three.js, the fonts) draws the
  engine's layout contract, so it stays the engine's and any pack's page may load it. A generic read of what live modules publish
  (`/published`) replaces the three feature endpoints, so a pack's page reads its modules' data without routes of their own; the chat
  command for a module's standing is `/<module>`. The abstract dashboard with reusable components is a later piece of work.

### C. Features still built into the engine
- **C1. Neighbours and letters.** `neighbors.py` (about 350 lines), `write_letter`, the `letters` table, the narrator's
  `neighbor_letter` and `speak_in_person`, in-person talk scenes, residents of invented places, and the `neighbor` character kind. 5b moved
  only the neighbour's invention into a module and kept letters as "conversation at a distance". Ashfall's village of survivors had to be
  voices on a radio. *Fix (decided: the machinery stays the engine's, for any character):* the engine keeps people as a service that
  any module's characters use: characters of any role a module names (not just `neighbor` and `resident`), each with a home place it
  owns or whereabouts a module says, in-person talk scenes with whoever is present (turns, what the agent remembers of the talk, the
  narrator voicing the character), and correspondence (letters there and back over hours, parcels within limits) for any character the
  world lets the agent write to. Modules decide who exists and what they do: inventing them, their lives and schedules, when they visit
  or write first, what they bring. What moves out of the engine is the neighbour's own rules in `neighbors.py` (when it writes first,
  its parcels, its trade note, its visits), into the neighbourhood module. Ashfall's village becomes a dozen villagers at the village,
  each someone to talk to through the same scenes. Two or three releases.
- **C2. What made things can do.** The capability catalogue is fixed in `creations.py`: `CAPABILITIES`, `SENSOR_CONDITIONS` (`crop_ripe`,
  `visitor`, `dawn`, `dusk`, `hungry`, `tired`), `HELPER_EFFECTS` (`hurry_crops`, `find`, `comfort`). Two parts are already the pack's
  (`world` effects and `provides` abilities, in `content.json`); the rest assume Pip's stats and a garden (0.44.0 hides the crop ones where
  nothing publishes `plots`). A wasteland can't make a water filter or a Geiger counter that works. *Fix:* the catalogue becomes the pack's
  (`content.json` `capabilities`: each with the narrator's help line, its params schema, and the request that carries it out), sensors
  watch published facts and stats by name, and helpers ask a module (`request`) as `hurry_crops` already asks the garden.
- **C3. The happenings' effect vocabulary.** `INTENTS` is fixed (`happenings.py`): coins, item, food_loss, stat, harm, stop, news, memory,
  request. `news` is about neighbours, `item` draws from the find tables by place kind, `stop` halts a creation. `request` is already the
  open door (a module applies its own effect, sized by severity). *Fix:* keep the primitives that are the engine's (stat, harm, coins,
  item, losing some of an item kind, memory) and route the rest through `request`, so news about a neighbour is the neighbourhood
  module's, and a creation stopping is the workings' own.
- **C4. Real-world links as tools.** `send_postcard` and `web_search` are engine tools; the design (DESIGN-world-packs.md, "Real-world links
  are sources") wants them to be sources that a world's modules choose to offer. Low priority: both are owner settings already.
- **Fine as they are:** drawing and writing (`draw`, `write_piece`, `look`, the gallery), programs (`program`), invented places,
  wishes, recall, the night pass's note ops, reflection, emotions.

### D. The module API
Nine hooks, nineteen reads and thirty-four proposals, added one feature at a time. What the shipped modules and Ashfall use:
- **Used by one module:** the proposals `perceive`, `offer`, `consume`, `runtime` and `find` (`workings`, the creations' runtime), `deplete`
  (`gathering`), `event` and `creation` (`crafting`); `character` and `letter` (`neighborhood`), `coins`, `part_with`, `whereabouts` and
  `notes` (`trade`) are each one feature's. The reads `weather` (garden), `made` (trade), `answers` (gathering), `making` and `found`
  (crafting); `pip` is used by none.
- **Overlaps:** `log` (`{text, kind, feel, items, tool}`) is an `event` with a `read` in all but name; `take`, `consume` and `part_with` all
  move things out of belongings, and `give`, `coins` and `find` move things in; `perceive`, `status` and `speak` all put words in front of
  the agent; `doing` and a `session`'s label both say what the agent is doing.
- **Proposed shape (sketch):** belongings in and out as `take` and `give` (items and coins; `part_with` is a `take` the agent agreed to;
  `consume` is a `take` of materials; `find` is a `give` with a reason); `event` with `read` replaces `log`; words to the agent as `status`
  (standing), `perceive` (once) and `speak` (as a voice); the agent as `affect` (stats, mood), `practice` and `doing`; the world as
  `publish`, `store`, `happen`, `request`, `source`, `schedule`, `wake`; people as `voices` and `character`. About twenty proposals.
  The `here`, `places` and `people` reads stay; the one-feature reads either become published facts (`weather` is the sky's already)
  or stay as the engine's own data (`made`, `found`).
- **How:** a manifest `api: 2`, with `api: 1` manifests accepted and translated for a few releases (the shipped modules move in the same
  release); the sandbox runner and the builder's API page (`app/builder/api.md`) change with it.

## Releases
Each a release with tests, mutation testing on what changed, Pip's world running unchanged, and the Ashfall day extended to cover it.
1. **The small leaks and the rename** (A1-A5): no `pip` left in the engine, the old columns and legacy fields gone.
2. **The dashboard into Pip's pack** (B5): the engine serves the pack's page and the shared renderer, `/published` replaces the feature
   endpoints, `/<module>` the feature commands; Ashfall gets the plain page.
3. **The night pass and the guide** (B1, B2): plans any module offers, tidied overnight; guide pages that say when they apply.
4. **People, part one** (B3, B4, C1): place kinds and scopes from the pack; characters of any role with a home place they own; talk
   scenes with whoever is present; Ashfall's villagers to talk to at the village.
5. **People, part two** (C1): correspondence for any character; the neighbourhood module drives the neighbour's letters, parcels and
   visits; `neighbors.py` keeps only the machinery.
6. **What things can do, and what happens** (C2, C3): capabilities from the pack, happenings' other effects through `request`; Ashfall
   gains a water filter that works.
7. **The API consolidated** (D, `api: 2`), last, once the releases above have shown which proposals are really needed.

Later, not in this plan: the engine's abstract dashboard, with components worlds reuse and panels they plug in.
