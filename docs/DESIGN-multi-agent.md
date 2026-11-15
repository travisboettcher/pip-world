# Design: more than one agent in a world (2026-11-15)

The owner asked for it (ROADMAP, "Multiple agents in one world"): two or more agents living in the same world, each with a mind of its
own, meeting in person and writing to each other through the machinery the characters already use. It is built and tried on Ashfall
first (Wren and a second survivor), as an experimental build; Pip's world moves only when the owner says so.

## What one agent means today
- **Storage.** One SQLite file. Of its ~40 tables almost all are the agent's own mind and life: `agent` (one row, `CHECK (id = 1)`),
  `stats`, `emotions`, `emotion_log`, `memories`, `recall_index`, `memory_context`, `reflections`, `reflection_cites`, `focus`,
  `night_decisions`, `expectations`, `turning_points`, `facets`, `abilities`, `capability_snapshots`, `day_stats`, `items`, `creations`,
  `works`, `work_session` (one row), `inbox`, `letters`, `people` (who it knows), `outreach`, `usage`, `happenings`, `happening_rolls`.
  The world's are few: `places`, `map_places`, `place_finds`, `modules`, `module_store`, `module_calls`, `characters`, `purses` (already
  keyed by party), and parts of `meta` and `events`.
- **The loop.** `loop.Agent` is both the agent and the world: `run()` ticks the agent, and its monitor runs the world's steps
  (`resolve_world`: modules, layouts, happenings, characters' letters and visits, sessions ending, stakes, the night's reflection, the
  builder). `world_pack.active()` and the pack's single `agent` (name, pronoun, kind, home) are read everywhere.
- **Modules.** The `agent` read, and `take`, `give`, `affect`, `perceive`, `wake`, `session`, `doing` and `practice`, all mean the one
  agent. Hooks a tool or a voice set off (`on_action`, `on_message`) are already an agent's; the world's own (`on_tick`, `on_time`,
  `on_event`) are not anyone's.
- **People.** Characters are voiced by the narrator. Talk scenes, letters and parcels are the engine's (C1), between the agent and a
  character.

## The shape
### Storage: the world's database and one per agent
Each agent keeps its own file (`/data/agents/<key>.db`) with the same tables as today, and the world keeps `world.db` with the world's
tables. An agent's connection opens its own file and `ATTACH`es the world's. SQLite looks an unqualified table name up in `main` first,
then the attached databases, so a world table that exists only in `world.db` is found without changing the SQL that names it: almost
every query stays as it is. There are no triggers or foreign keys to cross files. Writes to the world go through one lock per world
(WAL mode), not per agent. `events` splits by who it is about: the agent's own in its file, the world's (module live, layout built,
a character arriving) in the world's; the dashboard's feed reads both.

The alternative, an `agent_id` column on some thirty tables and in every query, touches far more code and fails silently when a query
forgets the filter. One file per agent also makes an agent easy to back up, copy into another world, or retire.

Migration: an existing single-file install becomes `world.db` plus `agents/<its agent>.db` once, by moving the world's tables. A world
with one agent behaves exactly as before; that is the first release, and the only one Pip's world needs until it gets a second agent.

### Process: one engine, the world's steps once, a loop per agent
`loop.Agent` splits in two. A `World` owns the pack, the narrator, the runner, the library, modules, layouts, characters, the builder,
the map and the clock, and runs the world's steps once a monitor beat. Each `Agent` owns its State (its file with the world attached),
its persona, pacing, tools, memory, sleep, reflection and night pass, its own happenings and stakes, and its token budget. One process
runs the World and every Agent as asyncio tasks, as it runs the one agent now.

It is shaped as a supervisor and actors, kept in one process to start small (the owner's call): each Agent is an actor whose only way
in is its mailbox (the inbox: what it hears, letters, wakes) and whose own state no one else touches; the World is the supervisor that
starts the agents, restarts one whose task dies (after a backoff, logged) without stopping the world or the others, and owns everything
shared. Nothing reaches into another agent's State, so moving agents into processes of their own later changes the transport, not the
design.

### Who the agents are
`world.json` gains `agents`: a list of what `agent` is today (`name`, `pronoun`, `kind`, `lives`, `look`, plus `key`, `home` and
`persona`: a file in the pack). `agent` stays as the one-agent shorthand. The deployment chooses which run (`AGENTS=wren,tomas`, default
all), and each may have its own persona file and budget (`DAILY_TOKEN_BUDGET_<KEY>`), so one agent can't spend another's day.

### Meeting each other
Another agent is someone the agent knows, like a character, but with a mind of its own, so nothing is narrated for it:
- **In person.** Agents at the same place see each other (presence, as characters are seen). `say(to="Tomas")` puts the line in
  Tomas's inbox as speech heard in person and wakes him (as a visitor's message does); his answer comes back the same way. A
  conversation has turns and an end like a talk scene, with each side's words its own model's.
- **Letters.** `write_letter` to another agent who writes is delivered after the usual hours into that agent's inbox as a letter, not
  answered by the narrator. Parcels move items between their belongings, within the day's cap.
- **Characters** stay as they are, voiced by the narrator, met by any agent.
- Trade, gifts and shared projects come later, through modules.

### Modules
The `agent` read stays "the agent this call is for": the one whose tool or voice set the hook off. A world hook (`on_tick`, `on_time`,
`on_event`) is for no one in particular, so it reads `agents` (each agent's public facts: name, where, activity, asleep) and says whom a
proposal is for with `"to": <agent key>` on `take`, `give`, `affect`, `perceive`, `wake`, `session`, `doing` and `practice`. Without a `to`
it is the acting agent's, or refused on a world hook when there is more than one. This adds to api 2; nothing in it changes for one agent.
Shipped modules that assume one agent (gathering's trip, reading's bookmark, crafting's projects, the stall) keep their state by agent.

### The dashboard
The engine's plain page and Pip's page show one agent at a time, with a switcher when there are several; `/state`, `/events` and the
rest take `?agent=`. The scene draws every agent at its place. Public pages, if a world has them, show all.

## Releases (each tested, mutation-tested, deployed to the experimental stack only)
1. **The world's database and the agent's** (one agent, no visible change): storage split, migration, `World` and `Agent` apart. *Built (0.54.0):*
   the storage split. The world's tables (`state.WORLD_TABLES`: places, the map, modules and their store and calls, characters,
   purses) live in `WORLD_DB_PATH`, by default beside the agent's file (`agent.db`: `agent-world.db`), attached to each agent's
   connection as `world` (WAL); an install from before moves them out once, rows and ids and all. `events`, `meta` and `place_finds`
   stay the agent's for now. A module's dry run copies both files. A deployment's backups must now take both files. And `loop.World`
   (0.54.0): the pack, the narrator, the library and the module runner, the world's steps once a beat (the shipped modules offered,
   modules' calls, answers and happenings, the owner told, layouts, the map) and the builder's night; it supervises its agents, starting
   again one whose loop dies (said in that agent's log). `loop.Agent` keeps its own steps (decay and feelings, stakes, a walk or session
   ending, its happenings, wishes, letters, reflection); alone it makes a world of its own, and its `gm`, `runner` and `library` are its
   world's. Until release 3 the world acts through its first agent's State, and owner notices go through that agent's channel.
2. **Several agents**: `agents` in world.json, a loop and budget each, the dashboard's switcher, a second survivor in Ashfall who
   doesn't yet meet Wren on purpose.
3. **Meeting**: presence, `say` between agents, letters and parcels between them, modules' `agents` read and `to`.
4. **The experiment**: watch Ashfall for a week; fix what it shows; then the owner decides about Pip's world.

## Decisions (the owner, 2026-11-15)
- **One process**, supervisor and actors in shape (above); separate processes maybe later.
- **Minds are private.** An agent's diary, notes, emotions, reflections and memories are its own: no other agent and no module reads
  them. Agents know each other by what they see, hear, and read in letters.
- **Meeting is left to chance.** Neither agent starts knowing of the other; they meet if their paths cross.
- **Ashfall's second agent is a scavenger trader**: lives in a shelter of their own, scavenges the east blocks and trades salvage, so
  their routes cross Wren's (the ruins, the village gate).
