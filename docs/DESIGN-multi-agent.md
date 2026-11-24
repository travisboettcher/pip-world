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

### Modules' working data (addendum, before release 3)
A module's definition (its code, manifest, version and status, its trial, its layout if it builds a place) is the world's. Its working
data is someone's: a manifest's `scope` says whose.
- **`agent`** (the default for rules and things): each agent has its own. The working data (`state`, `offers`, `facts`, `lines`,
  `due`, `cursor`, `show`, `budget`, `voices`, `heard`, `asks`, `happen`, `standing`, `requests`, `whereabouts`, `notes`) lives in
  that agent's file (`module_runtime`, keyed by the module's name so a new version keeps it, as the store is), and so does its store
  (`agent_module_store`). Crafting's projects, gathering's trips, reading's bookmarks, the garden's plots, trade's stall and tills,
  the happenings, raids and every status line are each agent's own. Such a module is stepped in each agent's step, as that agent; an
  agent with no data for it yet is new to it, and its `on_install` runs first. A thing (a creation's workings) is stepped only for the
  agent whose creation it is.
- **`world`** (parts and places always; rules that keep the world itself): one set of working data on the module's row and the world's
  store, stepped once in the world's step (as its first agent, until a proposal can say whom it is for). Pip's sky, Ashfall's village
  and Pip's neighbourhood are the world's, and so are the rules the world's builder writes.

The State routes this itself (`module`, `modules`, `update_module`, `store`, `merge_store`): every caller already passes the State of
the agent it acts for, so what it reads and writes is that agent's. An install from before gives the world's first agent the working
data and store its agent-scoped modules had; later agents start fresh.

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
   doesn't yet meet Wren on purpose. *Built (0.55.0):* world.json may list `agents` (each an `agent` entry with a `key`, and optionally
   a `home` of its own, shaped as places.json's `home`, and a `persona` file in the pack); `agent` stays the one-agent shorthand. The
   engine (`loop.build`) runs those AGENTS names (default all), each with its own file (the first agent's is DB_PATH, the others'
   `agents/<key>.db` beside it), the world's shared, its own budget (`DAILY_TOKEN_BUDGET_<KEY>`), and its own home to start in; only the
   first has the deployment's persona file and reaches the owner. Whatever names "the agent" names the one acting:
   `world_pack.acting(agent, state)` sets it for an agent's loop, ticks, steps and reflection (a context variable, so each asyncio task
   has its own), `world_pack.active().agent`, `places.home()` and the narrator's State follow it, and the world's own steps act as its
   first agent. The app takes `?agent=<key>` on every endpoint (404 for one the world hasn't), lists them at `/agents`, and the plain
   page has a picker. Ashfall names Ivo, a scavenger who lives in a lock-up off the ruins and trades at the village gate. *Decided while
   building:* Ivo doesn't run yet (Ashfall's deployment sets `AGENTS=wren`). Modules are the world's and so is their working data (a
   module's state, store, standing, published facts, offers), so a second agent would see Wren's crafting projects, her gathering trip
   and her stall as his own, and could finish them: that would spoil the experiment. Release 3 gives modules' working data an owner
   first, then Ivo starts.
3. **Meeting**: modules' working data by agent (each agent's projects, trips, stall and status lines its own; what is the world's, such
   as villagers brought or places laid out, stays shared), then presence, `say` between agents, letters and parcels between them,
   modules' `agents` read and `to`. Ivo starts. *Built so far (0.56.0):* modules' working data has an owner, as the addendum
   above says: `scope` in a manifest (`agent` by default, `world` for parts, places, Pip's sky and neighbourhood, Ashfall's village and
   the builder's rules), `module_runtime` and `agent_module_store` in each agent's file, the State routing every read and write, a step
   per scope (`modules.ours`), an agent new to a module installed from now, things stepped only for their maker, and an install from
   before giving its first agent what its modules had. Then the meeting (0.57.0, `others.py`): the World registers itself, so code acting for one
   agent can find the others. Agents at the same place see each other in their perception ("Ivo is here (a scavenger, digging)"), and
   the first time they meet: both remember it (`met:<key>`) and log a `met` event. `say(to=<agent>)` is heard only in person: it
   arrives in their inbox as speech (`source: agent`, shown as "said, here with you", answered with `say(to=...)`) and wakes them.
   `write_letter` to an agent one has met goes by the world's post (`agent_post`, a world table): two to six hours, then their inbox
   (`source: letter`), with one thing tucked inside moving between belongings (a creation stays with its maker: it lives in its maker's
   file); the day's letters count either kind. Modules may read `agents` (each one's key, name, where, activity, asleep; no one's
   mind). *Decided while building:* a world module's proposals still act on its first agent: `to` waits until a world module needs it,
   as none of the shipped ones does.
4. **The experiment**: watch Ashfall for a week; fix what it shows; then the owner decides about Pip's world. *Found so far:* the
   builder saw only the first agent (0.57.4: it sees every agent); each agent kept its own look of a shared place, so the layouts were
   rebuilt every beat (0.58.0: a place's look is the world's; DESIGN-dashboard.md, "Found while building"). *More agents* (owner,
   2026-11-18, to make meetings likelier and see how the engine takes different dispositions): three villagers who live inside the
   walls and spend their days at the village (Hester the cooper, grumpy; Tobin the water-runner, sunny; Sela the herbalist, anxious),
   each with a `temperament` (where its feelings rest) and knowing each other from the start (`knows`); Wren and Ivo meet them, and
   each other, by chance (0.59.0). *Found next* (owner, 2026-11-18): the talk worked (Wren met Sela and asked her to
   look at her vent) but cost a day's budget by morning: every line one agent said to another woke the listener for a whole world
   turn (about 11,500 tokens), a line every fifteen seconds. 0.60.0 runs it as a scene (below); and an agent's closing words beside a
   `say` are no longer logged as a second line, setting off somewhere cuts a gathering short, and the diary is written at home.

## Talk between agents (0.60.0)
When an agent's turn finds words from another agent who is here (its inbox, `source: agent`), the turn
runs the talk as one scene (`Agent._talk_with`, then `Agent._hold_talk`, a task of its own in `World.talks`): the two speak in turn,
the listener first, each from the talk scene's small prompt, its own (its persona, what it thinks of the other, its to-dos about them,
the talk so far as it heard it). A line is logged as the speaker's `say` and arrives in the listener's log at once (`inbox`, consumed),
waking no one. A talk takes time (0.65.0): each line as long as it takes to say and a pause (`talk.line_seconds`), both agents free
between lines (a visitor or a letter gets a world turn; what one says to the other meanwhile is part of the talk, waking no one), and
no heartbeat while it goes on. It ends on a goodbye, a silence, either running out of budget, one leaving or falling asleep
(`talk.cut_short`), or after `STRETCH_MINUTES` of talk; both log `talk` and have a world turn. For
`AGENT_QUIET_MINUTES` after (`talked:<key>`), words between them are heard but don't wake the listener, so a world turn doesn't start
the ping-pong again; when the listener's turn comes, they pick the talk up again as a scene. Each agent holds a lock (`talking`) for its turns, and a scene holds the other's; if the other is mid-turn for
`LOCK_WAIT` seconds, the words are answered the old way. Minds stay private: each line comes from its speaker's own State.

Meeting someone, an agent learns where they live (0.60.0; found when Sela promised to look at Wren's vent and had no way to get there):
another agent's home is a place it can go once they have met (`places.agents_homes`), found by its key or by its owner's name
("Wren's"), a home in kind. Arriving while they're in, the two see each other, and a word starts a talk.

Handing things over (0.61.0; found when Ivo and Hester agreed a price for his wire in a talk and had no way to keep the deal): `give`
hands someone here something the agent carries, and/or coins (`others.hand`); both remember it (`gave`, `gift`), and it is offered in
a talk scene too, where it shows in the talk as it happened ("Ivo: (hands you 11 x copper wire)"). A creation stays with its maker.
Each agent has a purse of its own (the world's first agent's is `agent`, as before; another's `agent:<key>`): until 0.61.0 every
agent's coins were one purse. After a talk, each world turn is shown it (the talk with whoever is here), as after a talk with a
character; without that, Ivo asked Hester his question again the moment it ended. And a scene shows the other agents who are there.

Talks run longer, and go on as talks (0.64.0; found on Ashfall, 2026-11-20): at 8 lines every talk between agents was cut off
mid-task (none ended on a goodbye), and the two went on a line per world turn, about 15,000 tokens a line where a scene's line is
about 2,000 (140 such lines that day). The owner: let the conversation continue instead. `AGENT_LINES` is 20, and words left
after a talk resume it as a scene, however lately they talked. A talk lifts feelings (`emotions.TALKED`) the first time each day with
each other agent (`company:<key>`), not every talk: with a talk every half hour, grumpy Hester's joy and trust had settled at twice
her temperament. The same day, the villagers: a character is the world's, so what it has heard (`companions.hear`) records which
agent said it, and only that agent's beat answers or drops it (every other agent's beat had wiped Tobin's questions to Jun, far from
the gate, as if he had left); a talk scene with characters is with the one the agent spoke to last this visit, else the first who
spoke (it had always been the first one there, Marta). And another agent's home is laid out by its owner only (`layouts._targets`):
seen from next door it reads differently ("home" to one, "the stillroom" to the other), so each home was rebuilt every beat, about
20,000 times a day.

A talk takes time, not lines (0.65.0; found on Ashfall, 2026-11-21): with 0.64.0's brake gone, Wren and Sela, checking her vent
together, said a line a second (about seventy 20-line talks back to back, 07:00 to 08:34) and both spent their day's tokens. The owner:
make the dialogue take time rather than limit it, so how long they stay together is the limit. A line now takes its speaking time
(2.5 words a second) and a 20-second pause; there is no limit on lines; every 20 minutes of talk each has a world turn, and words
left pick the talk up again. A line costs about 2,300 tokens and a world turn about 15,000, so an hour together costs each about
150-200k: a whole day at the same place stays inside a 3M budget.

## A character becomes an agent (0.66.0)
The owner (2026-11-22): Oriel, Pip's neighbour, should become an agent of her own; tried first on Ashfall, with Marta at the gate.
A world.json agent may name the character it was (`was`). The first time it starts (`becoming.step`, at the world's start, after the
agents know each other), if the world has that character, the agent takes over what they carried: their `life` and what they `told`
(as things it has `learned`), and every exchange the other agents had with them, told from its own side at the time it happened
(`State.remember`: in the log and the recall index, nothing appraised): the character's letters are its `letter_sent`, letters to
them its `inbox` (`source: letter`), their words in person its `say`, words to them its `inbox` (`source: agent`). Letters still in
the post become the world's agent post, due when they were. Each agent who dealt with the character has met the agent, both ways; the
character is removed, and the agent logs `became`. Once only (`became` in its file). A world that never had the character starts the
agent as written. A module that brings people must not bring an agent back as a character (Ashfall's village reads `agents`).

## Pip's neighbours (0.67.0)
The owner (2026-11-22, -23): Pip's world gets neighbours who are agents. Oriel Vantosh, the tide-reader Pip has written to and visited
since its first week, becomes one (`was`); with her, Abel Marrow at the scrapyard (who knew her husband), Tansy Hale the beekeeper and
painter by the wood (one who draws, so the draw tool is used), and Lio Fenn, who carries goods and letters from the harbour. Pip is still
the first agent and the only one who reaches the owner. What it took, all generic:
- an agent may start with belongings of its own (`items`, shaped as items.json's `start`), not the world's (Oriel's tin of brass and
  wire, not Pip's seed packets; Ashfall's villagers had acted like scavengers on Wren's kit);
- the modules' `agents` read gives each agent's `role`, and the neighbourhood invents a neighbour only when the agent has none,
  character or agent (it would otherwise have replaced Oriel the moment she stepped aside);
- Pip's own home layout claims its place (`workshop`), and the neighbour-cottage layout lays out other homes; the builder's list of
  anchors now names a place with a layout of its own, as well as each kind's;
- guide pages by role: Pip is the `maker`, the others `neighbor` (their own home page and a page on their own lives).
Tried on a copy of Pip's data: Oriel takes over 34 letters she wrote, 198 lines and letters from Pip and 135 of her own words.

The map's land is the world's (0.63.1; found when one agent's map had mountains and another's none): drawn from the world's seed
(kept by its first agent, like the places' looks) and every place's spot, the same for all; each agent's map still frames what it
knows and paints only where it has walked.

## Decisions (the owner, 2026-11-15)
- **One process**, supervisor and actors in shape (above); separate processes maybe later.
- **Minds are private.** An agent's diary, notes, emotions, reflections and memories are its own: no other agent and no module reads
  them. Agents know each other by what they see, hear, and read in letters.
- **Meeting is left to chance.** Neither agent starts knowing of the other; they meet if their paths cross.
- **Ashfall's second agent is a scavenger trader**: lives in a shelter of their own, scavenges the east blocks and trades salvage, so
  their routes cross Wren's (the ruins, the village gate).
