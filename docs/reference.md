# agent_world

Autonomous AI agent ("Pip") that wakes on its own, looks at its state, and acts via tools.
M1 is headless: a Python/FastAPI brain with an HTTP API. `agent_world.hll` is the source of
truth; `docker-compose.yml` is generated (`hllc build agent_world/agent_world.hll`).

## Run
```sh
cp .env.tpl .env   # add ANTHROPIC_API_KEY (and TAVILY_API_KEY for web_search)
docker compose up -d --build
```
Internal only: `https://agent-world.internal.example.io` (`/state`, `/events`, `POST /inbox`, `POST /tick`).

## Swapping parts (env + restart, no rebuild)
- `LLM_BACKEND`: `anthropic` (default) | `openai_compat` (set `LLM_BASE_URL`, e.g. `http://ollama:11434/v1`) | `fake`
- `PACING`: `heartbeat_events` (default) | `fixed_tick` | `manual` (only `POST /tick`)
- `MAX_CALLS_PER_TICK` (default 3): extra LLM calls in one wake happen only when a tool result needs a response (currently `web_search` and tool errors). `1` restores one-call-per-tick.
- `TOOLS`: comma list of registered tools. `DAILY_TOKEN_BUDGET` (default 5M, ~$0.70/day on Haiku 5.5) caps spend; ticks pause when hit.

Add a backend in `brain/app/llm/` and register it in `llm/__init__.py`; add a pacing policy in `pacing.py`.
`brain/persona.md` is re-read every tick.

## Tests
`cd brain && pip install -r requirements-dev.txt && pytest`

## Talking to Pip: `pipchat`
Stdlib-only CLI (`./pipchat`, or symlink it onto your PATH). Defaults to the Traefik URL; override with `PIP_URL` or `--url`.
```sh
./pipchat                       # interactive chat; /status /usage /notes /log /watch /tick work inside it
./pipchat "hello Pip"           # say one thing, print the reply
./pipchat status | usage | health
./pipchat notes [diary|todo|wishlist|ambitions|learned] [--status open|done]
./pipchat log 30 --kind tool --kind say
./pipchat watch --kind tick     # live stream
./pipchat --json notes          # JSON for scripting (watch emits JSON lines)
```

## Pip's journal
`note_to_self` writes to one of five sections (`diary`, `todo`, `wishlist`, `ambitions`, `learned`); `resolve_note`
crosses off a todo/wishlist/ambition item. Open items and the latest diary entries are shown to Pip every tick, and the
persona (`brain/persona.md`, re-read live) encourages it to keep them. HTTP: `GET /notes`.

## Belongings and garden
Pip owns items (kind `tool`: kept, `material`: used up by `use_item`, `food`: eaten, `seed`: planted) and has a small
garden (`GARDEN_PLOTS`, default 3). It starts with tomato and carrot seeds (given once). Crops grow in real time
(`GROW_SPEED` speeds that up), a ripe crop wakes Pip, and harvested produce is food that fills more than a plain meal.
```sh
./pipchat give "tiny needle file" --message "for the clock!"          # tool (kept)
./pipchat give "spare brass" --kind material -q 5                     # used up as Pip works
./pipchat give "basil seeds" --kind seed --grow-minutes 30            # Pip can plant it
./pipchat items | garden
```
HTTP: `GET /items`, `POST /items` (gift; wakes Pip), `GET /garden`.

## Projects and creations
Design and rationale: [DESIGN-creations.md](DESIGN-creations.md). Pip chooses what to make; the engine decides how it
goes; a "game master" LLM call (same backend and budget) only writes flavor and picks from a fixed vocabulary.
- `start_project(name, goal, steps)`: **Pip writes the plan**; the GM reviews it (tags abilities, sets craft and
  difficulty, holds the truth about what Pip can't know yet) and never rewrites it. `work_on(project, minutes, approach)` runs a
  real-time session (`WORK_SPEED` speeds it up), and Pip isn't woken by the heartbeat until it ends. Then a dice roll
  (skill, owned helpful tools, difficulty, fatigue) sets the odds; if Pip described an approach the GM judges it and
  may move the result one step either way (up to a blowup that costs progress, energy and a material); otherwise the
  GM only narrates. Resting cuts a session short at half credit; `set_activity` only re-describes it. `abandon_project` gives up.
- **Discovery** ([DESIGN-discovery.md](DESIGN-discovery.md)): plans are partial. The GM lists what Pip doesn't know yet
  (and writes hidden facts it never sees); `experiment(project, hypothesis)` is a timed session whose outcome the engine
  rolls and the GM narrates, revealing facts and answering questions. `revise_plan(project, steps, drop, because)`
  lets Pip edit its own plan freely, and bring in what it learned from searches, books or visitors (the GM judges that). Abilities (precision, patience, ingenuity, knowledge,
  handiness) transfer between crafts; Pip sees them as words, `pipchat projects` shows the numbers.
- A finished project becomes a creation. Most (art, writing, keepsakes) have no behaviour and simply exist. Ones that
  genuinely work get up to 3 generic capabilities (`timekeeper`, `upkeep`, `periodic`, `sensor`, `helper`,
  `companion`), with the specifics (what it does, how it's tended, what it finds) written by the GM, plus quirks
  (setbacks leave marks). The engine runs them every monitor pass without the LLM: timekeepers drift, things that
  need upkeep stop until Pip `tend`s them, sensors wake Pip, helpers speed the garden, find things or comfort Pip.
  `use_item` on a creation asks the GM what happens, with only small capped effects.
- A `companion` creation talks: it chatters now and then and answers `say(text, to=<name>)`, capped at
  `COMPANION_REPLIES_PER_HOUR`.
```sh
./pipchat projects [-v] [--status active|done|abandoned]   # stages, progress, skills; -v shows each session
./pipchat creations                                         # what Pip has made and what it's doing
```
HTTP: `GET /projects`, `GET /creations`. New tools must be listed in `TOOLS` in `.env` (see `.env.tpl`).

## Long-term memory
Design: [DESIGN-memory.md](DESIGN-memory.md).
- **Sleep**: once a day after `REFLECT_HOUR` (local, default 3; the first one runs right away) Pip reflects in its
  own voice on everything since the last time: a day summary, up to 5 insights with importance, notes on the people
  involved, and a fresh self-portrait. These sit at the top of every prompt at a fixed size (~500-900 tokens).
- **`recall(query)`**: Pip searches its journal, visitor messages, gifts, work, reflections and people notes
  (SQLite FTS5).
- **Who's talking**: visitor messages carry a sender (`pipchat --from`, default `$PIP_NAME` or Morgan; the web UI
  uses the name from the gift form), so Pip can remember people.
```sh
./pipchat memory                      # self-portrait, people, beliefs, recent days
./pipchat reflect                     # reflect now instead of at night
./pipchat recall "first gift"         # search Pip's memory like its recall tool does
```
HTTP: `GET /memory`, `GET /recall?q=`, `POST /reflect`; `POST /inbox` takes `sender`.

## The neighbor
Design: [DESIGN-neighbor.md](DESIGN-neighbor.md). On first start (`NEIGHBOR=1`, the default) the GM invents a
neighbor - name, private persona, a public one-liner - whose first letter arrives soon after. Pip writes back with
`write_letter(to, text, enclose?)` (up to `LETTERS_PER_DAY`; `enclose` gives away one item or creation). Letters take
`LETTER_DELAY_MINUTES` each way; the neighbor answers on delivery, writes first every `NEIGHBOR_WRITES_EVERY_HOURS`,
may send a small parcel (`PARCELS_PER_DAY`), and has a life that moves on between letters. Letters arrive in Pip's
inbox with the neighbor as sender, so memory, recall and the nightly reflection pick them up. Pip can also
`go_to` the neighbor's home: they greet it and talk in person (`say` with `to`).
```sh
./pipchat letters      # the neighbor, what's new with them, and every letter (in transit too)
```
HTTP: `GET /letters`.

## Places and the library
Design: [DESIGN-library.md](DESIGN-library.md). Pip lives in its `workshop` (projects and garden happen there) and
can `go_to` the **library**: the homelab's Calibre library (`../calibre/library`, the folder calibre-web serves),
mounted **read-only** at `/library`. A walk takes `WALK_MINUTES`. At the library Pip can `browse_library` (search or
wander the shelves) and `read(book, minutes)`: when the session ends, the next stretch of the book (EPUB or PDF
text, from Pip's bookmark) is condensed by the GM into what Pip read, which feeds memory, recall and reflection.
No library mounted = no library place and no library tools.
```sh
./pipchat library                 # what Pip is reading, and how far in
./pipchat library numenera        # search the catalogue
```
HTTP: `GET /library/search?q=`, `GET /library/bookmarks`.

## Day, night and sleep
See [DESIGN-sleep.md](DESIGN-sleep.md). Pip perceives the period of day and which day of its life it is. At night (`BEDTIME_HOUR`-`WAKE_HOUR`)
it can `sleep` until morning: no ticks, faster recovery, slower hunger; the nightly reflection runs as it falls asleep.
Only a visitor (or `pipchat tick`) wakes it early. `SLEEP=0` turns the rhythm off.

## Firsts
See [DESIGN-self.md](DESIGN-self.md) and [RESEARCH-self.md](RESEARCH-self.md). Every logged event yields facets; the first time one is seen
it is recorded (`facets` table), marked on the event, shown to Pip as plain fact under "New for you", and listed for the
nightly reflection. Major firsts (first sleep, first visitor, first setback...) can also prompt a diary moment. The engine
never says what a first means. Existing history was backfilled silently on first start.

## Cited reflections
The nightly reflection tags every event line with its id and lists Pip's earlier beliefs as `i<number>`. Each new insight
lists the ids it rests on (`because`); unknown ids are dropped and an insight with nothing cited is a *hunch*, shown to Pip
apart from its beliefs. A small GM call (`VERIFY_INSIGHTS`) checks that the cited lines support each claim and demotes
unsupported ones to hunches. `recall` shows the moments behind a belief. Events carry a deterministic importance that
decides what survives the reflection's character budget. Nothing is rewritten: a revised belief is a new insight that
cites the old one.

## Portrait versions and change
Every nightly self-portrait is kept (`GET /memory` -> `portraits`); the reflection sees the last three, dated, plus the last
days in plain counts (`day_stats`). If Pip sees itself differently it can record a cited `changed` claim; supported ones
show up in its prompt as "How you've changed".

## Expectations and surprise
See [DESIGN-expectations.md](DESIGN-expectations.md). `work_on` and `experiment` take an optional `expect`
(`well`/`slowly`/`badly`, `works`/`partly`/`fails`); the engine compares it with the outcome and Pip sees the plain comparison.
Step durations are compared with Pip's own minutes guess. Big misses are flagged as surprises (better/worse/longer/shorter), feed
the first-surprise facts, the nightly reflection and a small calibration block; `GET /memory` lists the records.

## Turning points
At each reflection the engine looks for signals that the day changed more than usual (major firsts, surprises, counts far
from Pip's own usual, goal changes, a new main conversation partner, returns after a long gap). Three or more make a
candidate that the reflection is asked about as facts; Pip may mark at most one day as mattering, with cited evidence.

## Capabilities
Each night the engine counts how Pip's tools, crafts and abilities have actually gone (worked / didn't, went well / badly), keeps a
dated snapshot, and shows the counts (with the change since last time) to the reflection so the self-portrait is grounded in what
Pip really did. `GET /memory` exposes the latest snapshot.

## The night pass
See [DESIGN-nightpass.md](DESIGN-nightpass.md). After a nightly reflection that found something to go over, Pip's sleeping self gets a
second call (once per sleep, at least 6 h apart). Using only cited evidence it may archive or merge old notes, mark one done, put a
project on hold or take it off, add one goal, and choose up to three things to focus on tomorrow. Nothing is deleted; Pip is told what
was decided and why and can `undo_decision`. Yesterday's focus is reviewed against the log (kept / carried / dropped) and counted.
`NIGHT_PASS=off|log|apply` (default apply); `GET /memory` lists decisions and focus.

## Tools belong to places
Each tool is scoped (`anywhere`, `home`, or a place): the model is offered only the tools that work where Pip is, and the registry refuses
a tool used from the wrong place ("you're at the library; go_to home first"). Home: `work_on`, `experiment`, `plant`, `harvest`, `tend`,
`sleep`. Library: `browse` (was `browse_library`; the old name still works), `read`. Everything else works anywhere. Away from home Pip is told what the place offers. See
[DESIGN-places.md](DESIGN-places.md).
Places are records (`places.py`: home, the library, each neighbor's home); the prompt lists where Pip can go, how long it takes, whether it is
closed, and what each place is for.

## Gathering
The woods (8 min away) and the junkyard (15 min) are open in daylight. `gather` is a timed session (15-60 min) that rolls a haul from the
place's loot table (sticks, bark, berries, seeds; scrap brass, wire, gears, the odd tool); the place's stock runs down and refills with
time, so camping there yields less. The GM only narrates what the engine found. Finds are remembered per place; `where_to` answers
"where could I get brass?" from the directory and what Pip has found, and a project step missing a material says where it was found.
`WILD_PLACES` chooses which places exist. See [DESIGN-places.md](DESIGN-places.md).

## The web UI
`/ui/` has five tabs (Now, Journal, World, Work, Mind), a chat bubble (bottom-right; unread badge; remembers whether it was open) and a header
with Pip's activity, hunger/energy meters and a token-usage pill (hover or tap for the breakdown and cost). The Mind tab shows the
self-portrait, beliefs and hunches, how Pip has changed, days that mattered, people, what its sleeping self decided, and what it can do.
The files are bind-mounted: edit `brain/web/` and refresh, no rebuild.
