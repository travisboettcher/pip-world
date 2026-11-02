# Design: places that characters mention become real

Status (2026-10-31): **built**, residents and the neighbor-prompt wiring included. See "As built" at the end for where
the implementation differs from the text above. Builds on [DESIGN-places.md](DESIGN-places.md) (place records, the
directory, `gather`, `where_to`; its "later extension: discovery of places"), [DESIGN-neighbor.md](DESIGN-neighbor.md)
(letters and visits) and the referee pattern of [DESIGN-creations.md](DESIGN-creations.md): the engine decides what exists
and what it does, the GM only proposes from a fixed vocabulary and narrates. Related roadmap items: "Places, remaining:
`places.json` ... a place or two more" and "Small economy".

## Why
On 2026-10-30/31 Briar Fennick told Pip, in letter #5 and in both in-person visits (events 1254, 1306), to ask "the
ironmonger in Saltholm" for thin brass wire. Saltholm doesn't exist. Pip believed her, thanked her, and wrote to-dos it can
never finish (#117, #125 still open, #127; a fourth was refused as a duplicate). It never even tried `go_to Saltholm` (all
12 `go_to` calls in the log are to Briar's home, the woods or home): the directory didn't list it, so Pip filed it as
"later". Meanwhile the junkyard, which is real, has brass wire.

The owner likes Briar's storytelling and does not want it narrowed to the existing map. So the fix runs the other way:
**when a character points Pip at a place, the world grows to include it.** The characters already invent a world in
their words; this makes the engine keep up with them, within caps.

## The idea in one paragraph
A character's GM call may return, beside the letter or the spoken line, one optional `mentions_place`. The engine
checks it (the name really is in the words, it isn't a place already known, under the caps) and records a **heard-of**
place: a name, who said it, what they said is there, a walk time fixed by the engine. Pip's directory lists it under
"Places you've heard of", so `go_to Saltholm` just works. The place becomes **real lazily**, on Pip's first arrival: one
GM call proposes its kind, description and what can be found there, from a fixed registry of place kinds and the four
existing item kinds; the engine validates, clamps and keeps it. From then on it is a place like the junkyard.

## Detection: noticing a mentioned place
| Option | Cost | Reliability | Verdict |
|---|---|---|---|
| **Optional `mentions_place` field on the calls that write a character's words** (`gm.neighbor_letter`, `gm.speak_in_person`, `gm.invent_neighbor`) | a few dozen output tokens on calls already made | high: the writer knows what it meant; the engine checks it against the text | **primary** |
| A separate extraction pass over each letter/line | one extra GM call per letter and per spoken line | high | not needed; the field does the same job for free |
| Pip's failed `go_to` | free | **would have missed the motivating case**: Pip never tried | backstop only |
| A regex for capitalised names | free | noisy ("Dear Pip", "Thursday", "the Third Groyne") | no |

Recommended:
1. **The field.** `GameMaster.ask` already takes a properties dict; the three calls gain an optional
   `mentions_place: {place, there, distance}`:
   - `place`: the destination as said, the town, wood or shop Pip would walk to ("Saltholm");
   - `there`: what the character says is there or is for, under 120 chars ("an ironmonger with a drawer of odds and
     ends; thin brass wire, the fishing-hook gauge");
   - `distance`: `near | far | very far`, the character's sense of it (enum; the engine owns the minutes).
   The prompt adds one sentence: "Only if your words point Pip to a place it could go and that isn't one of these:
   <known and heard-of place names>, give `mentions_place`. Not your own home, not landscape you just pass through."
   Listing the known names makes the GM reuse them (which is half the dedupe) and costs ~30 tokens.
2. **The backstop.** A `go_to` that matches nothing (`places.find` returns None) searches the last ~20 `companion` events
   and delivered neighbor letters for the asked-for name (normalised, below). If a character said it, the place is
   recorded as heard-of (`there` = the sentence it came from) and the walk starts. **Pip alone can't make a place real**:
   a name only Pip has used still gets today's "you don't know a place called ..." answer.
3. **Backfill once.** Saltholm was said before this exists. On first start with the feature, a one-time migration runs the
   backstop's search for every proper name in Pip's open to-dos (#125 names Saltholm; Briar said it), so the motivating
   place is heard-of from day one. No GM call.

The engine checks every proposed mention (`invented_places.accept(state, speaker, text, raw)`):
- the place's core words (below) appear in the character's own `text`, as `world_effects.allowed` checks a project's own
  words; a field about a place the words never name is dropped;
- not Pip's home, a neighbor's name or home, or a reserved name (`home`, `workshop`, `library`, `woods`, `junkyard`, and
  `market`, kept for the coins market); 2-40 chars, at most 5 words;
- not already known: a match on an existing record's key or aliases adds the mention to that record instead (below);
- under the caps (Guards).

## Names: normalising and dedupe
A place has a `key` (its display name, "Saltholm") and `aliases`. Matching uses a **core**: lowercase, drop leading
articles and "'s", drop trade and feature words (`ironmonger, shop, store, market, stall, smithy, village, town, harbour,
quay, inn, mill, ...`, a short list in code), singularise with `state.name_key`.

| Said | Core | Result |
|---|---|---|
| "Saltholm" | `saltholm` | new heard-of place "Saltholm" |
| "the Saltholm ironmonger" | `saltholm` | same place; "ironmonger" goes into its `there` notes |
| "Saltholm's ironmonger" | `saltholm` | same |
| "the ironmonger in Saltholm" | `saltholm` | same (the GM is asked for the destination, so this usually arrives as `place: Saltholm` anyway) |
| "the old mill" | `old mill` (no proper noun: the trade word "mill" is kept when nothing else is left) | new place "the old mill" |

The key is the shortest proper-noun form seen; other forms become aliases. `places.find` already matches substrings both
ways ("saltholm ironmonger" contains "saltholm"), so it learns aliases by adding them to the candidates it searches.
Granularity: **the settlement is the place, a shop is what's there.** One village with an ironmonger is one place, not
two; that keeps the directory short and makes "the baker in Saltholm" a fact about Saltholm, not a new place.

## When it becomes real: heard-of first, real on arrival
Recommended: **lazy.** A mention costs nothing but a row; the GM call that designs the place runs only if Pip actually goes.
Most mentioned places will never be visited, and an unvisited place doesn't need loot tables.

| Stage | What exists | What Pip sees |
|---|---|---|
| heard-of | key, aliases, who said it, the `there` notes (up to 3 mentions, clipped), `walk_minutes` (engine-chosen now, so it's stable), first heard at | a second directory block, and `where_to` finds it |
| real | the full place record (below), the description | the normal directory line, "Here you can", verbs |
| removed | kept for history, never offered | nothing |

The directory (`places.directory`) gains:
```
Places you've heard of but not been to (go_to works):
- Saltholm, about 35 min, a long walk - Briar says: an ironmonger with a drawer of odds and ends (thin brass wire)
```
`where_to("brass wire")` matches heard-of `there` notes too: "Saltholm: Briar says the ironmonger there has thin brass
wire (you haven't been)", beside "the junkyard: you've found brass wire there twice". An open to-do naming a heard-of
place gets a note in the same spirit as the visit note in `loop.py` (the "[you've since visited ...]" annotation):
"[Saltholm: you've heard of it; go_to Saltholm to walk there]". That turns #125 into something Pip can do.

`go_to` a heard-of place: `walk_minutes` from the record, and the existing "closed when you get there" note works
before the design, because the kind's default hours are applied at heard-of time from `distance` and `there` words (a
shop word means shop hours). On arrival, `places.arrive` sees an undesigned place and calls `gm.design_place` instead of
`gm.describe_place` (one call does both). If the GM fails, Pip still arrives; the place has only its blurb and no verbs
("you find Saltholm, but can't get your bearings today"), and the design is retried on the next arrival.

## What a place record is made of, and who owns what
The existing `Place` dataclass (`places.py`) plus a source. Stored in a new table
`places (key, aliases, status, kind, blurb, walk_minutes, hours, daylight_only, verbs, loot, mentions, description,
created_at, real_at, source)`; `places.registry()` reads it after the built-ins.

| Field | Who | Rule |
|---|---|---|
| key, aliases | engine | from the mention, normalised |
| `walk_minutes` | **engine** | from `distance`: near 12-20, far 20-35, very far 35-50 (uniform, fixed once); hard cap 50 so a round trip plus a session fits in daylight |
| kind | GM proposes, engine checks | one of the kind registry below; checked by words, falls back to `sight` |
| hours / daylight | engine (from kind); GM may shift within the kind's bounds | shop: opens 7-10, closes 16-19, at least 6 h; wild and yard: daylight only; sight: daylight only |
| verbs | **engine** (from kind) | only existing shared verbs: `gather`, `browse`. No new tools, ever |
| verb wording | GM | the short help and the gerund ("rummaging in the ironmonger's drawer"), clipped |
| loot | GM proposes entries, engine builds the table | see below |
| description | GM, written once | must agree with the mentions it is given; clipped to 500 like today |
| mentions | engine | the characters' words, kept as evidence |

**The kind registry** (`place_kinds.py`), in the shape of `world_effects.EFFECTS`: each entry is a few lines with its
help text for the GM, its words, its verbs, its hours rule, its loot rules and its stock numbers. Adding a kind is one
entry; nothing else needs to know.

| Kind | Words (one must appear in the mentions) | Verbs | Loot rules | Stock (capacity / refill per hour) |
|---|---|---|---|---|
| `wild` (a wood, a shore, a marsh edge) | wood, shore, beach, flats, meadow, hill, marsh, ... | gather | material, food, seed; no tools | 120 / 15 (as the woods) |
| `yard` (a scrapyard, a quarry, a tip) | scrap, heap, quarry, tip, dump, yard, wreck | gather, browse | material, rare tool (at most one tool entry) | 120 / 15 |
| `shop` (an ironmonger, a chandler, a seed merchant) | shop, -monger, merchant, chandler, smith, sells, keeps, stall, store | browse, gather ("rummage") | material, tool, seed, food; at most two tool entries | 40 / 2 (restocks over a day) |
| `sight` (a lighthouse, a ruin, a viewpoint) | anything (the fallback) | none | none | - |

**Loot**: the GM proposes 4-10 entries `{name, kind, tier: common|uncommon|rare, description}`; the engine turns them into
a `gathering.LOOT`-shaped table: `kind` must be in `world.KINDS` and allowed by the place kind, weight and quantity range
come from tier and kind (common 15-30 / 1-3, uncommon 6-12 / 1-2, rare 2-5 / 1; tools are always rare, seeds get the
usual crop defaults the way neighbor parcels do), names are clipped and matched with `state.name_key` against items that
already exist (the junkyard's "brass wire", Pip's inventory) so the same thing stacks. The design prompt lists those
existing names and asks the GM to reuse one when the thing is the same. **Promise check**: every item named in the
`there` notes ("thin brass wire") must be in the table; if the GM left it out, the engine adds it as `uncommon`. What a
character promised is what Pip finds, sometimes.

`gathering.LOOT` and `VERB` become lookups (`loot_for(state, place)`, `verb_for(...)`) that fall back to the `places`
table; `stock`, `draw`, `resolve`, `place_finds` and the "(you found X at ...)" hint already work per place key.
Tool scoping needs one change: `gather` and `browse` are scoped `where=("woods", "junkyard")` / `("library",
"junkyard")` today, which can't name places that don't exist yet. They become scoped to **"wherever the place record lists
the verb"** (`tools.is_here` asks `name in place.verbs`), which the built-ins already satisfy. `out_of_place` and
`specs_for` keep their closed-place logic.

## Shops before there are coins
| Option | For | Against |
|---|---|---|
| Browse only | no inflation | the motivating case stays unsolved: Briar said Pip could get wire there |
| Free rummage (a shop that is just a `gather` place) | simple, reuses everything | a shop that gives things away is odd, and it's a second junkyard |
| Barter (leave an item, take an item) | in keeping with letters and parcels | needs item values, which is the economy itself |
| One welcome gift, then browse | cheap | a dead end after one visit |
| **Rummage on account (recommended)** | uses `gather` as-is; the shop's slow restock caps it; and it leaves exactly the record the economy will need | one small new list |

Recommended: at a shop, `browse` shows what is in stock today (`gathering.glimpse` over the table, only entries with stock),
and `gather`, described there as "ask to pick through the drawer", is a short session (15-30 min) whose haul comes from
the shop's table with the shop's small, slow stock. Each haul is written into an `on_account` list for that shop ("2
brass wire, on account with the Saltholm ironmonger"), shown in the result and in `browse` there. Nothing is owed yet:
the narration says the keeper lets Pip settle up later. When the market and coins arrive, the shop's loot table **is**
its stock list (prices from tier), `buy`/`sell` replace `gather` at shops, and the on-account list becomes a first,
small debt to settle: a want the economy inherits rather than a rule it has to undo. The keeper is narration only
for now (Not now: a keeper character).

## Guards
- **Caps** (settings, defaults): at most 2 new heard-of places a day (`INVENTED_PLACES_PER_DAY`), 12 invented places in
  all, heard-of and real together (`INVENTED_PLACES_MAX`); at most 1 design call a day (a second new place reached the
  same day arrives undesigned, exactly as on a GM failure, and is designed on the next arrival). A heard-of place that is never visited is forgotten after 30 days, freeing room. At the cap, mentions
  are not recorded, and the characters' prompts already list the places that exist, so they lean on them.
- **Characters and visitors create places**, and only with their own words (the text check). Pip's guesses and Pip's
  to-dos don't. (Owner decision 6: what a visitor says in chat counts.) The owner adds places directly (below).
- **Distance**: the engine owns walk minutes, capped at 50; `go_to` adds "it'll be dark before you could get back" when
  arrival plus the walk home passes nightfall (`sleepmod`), a warning, not a refusal, like today's "closed" note.
- **Sleep and daylight**: invented places only get daylight-only or bounded shop hours from their kind; none is open all
  night. `sleep` stays home-only. Nothing about sessions or pacing changes.
- **Inflation**: shops restock over a day, at most two tool entries, tools always rare; yields follow `gathering`'s
  depletion. The GM proposes names and tiers; the engine decides weights, quantities and counts.
- **Everything clipped and validated** like `neighbors.clean_parcel`; an unusable design is a bare place, never a crash.
- **Owner control and persistence**: the `places` table lives in the SQLite volume (so it is backed up with the volume). `GET /places`,
  `pipchat places` (heard-of and real, with who mentioned them), `pipchat places rm Saltholm` (status `removed`; if Pip is
  there it can still `go_to` away, and nothing is offered there), and `PATCH /places/<key>` for walk, hours, description and
  loot through the same validator. The roadmap's `places.json` becomes an **overlay** read at startup: entries override
  built-ins or table rows by key, `"removed": true` hides one, and `pipchat places export` writes the current table in that
  format, so editing the world by hand is: export, edit, mount.

## Keeping characters consistent afterwards
- `gm.neighbor_letter` and `gm.speak_in_person` get one compact line, built from the registry like the directory:
  "Places in Pip's world: the woods, the junkyard (scrap), the library; Saltholm, a long walk (you told Pip about its
  ironmonger; Pip has been and found brass wire there)". Up to 8 places, the ones this character mentioned first. Briar
  then speaks as someone who knows Saltholm, and the same list is what makes her reuse names instead of inventing a second
  village. It doesn't forbid new places; it only tells her what already exists.
- `gm.design_place` is given every recorded mention verbatim and told the description must agree with them ("Briar said
  the ironmonger keeps a drawer of odds and ends"). The promise check makes the loot agree too.
- A later mention of a real place (Briar names Saltholm's harbour) is added to its `mentions` as evidence and shown in the
  directory blurb, and may add to the place (owner decision 3).
- Recall and firsts need nothing new: arrivals log `arrived` (the `place:` first already exists in `firsts.py`), hauls log
  `gathered`, and the mention itself logs a `heard_of_place` event so recall can answer "who told me about Saltholm?".

## Testing (TDD, per agent_world/CLAUDE.md)
All with the `fake` backend (`FakeBackend.queue` a `report` tool call; `FakeBackend.calls` to assert what a prompt
contained), a fixed `random.Random`, and a temp `State`. Red first for each:
- `accept`: a field whose name isn't in the text is dropped; the four Saltholm spellings give one place with aliases;
  reserved names, neighbor names and Pip's home are refused; the third mention in a day and the 13th place are refused;
  `distance` maps into its band and the minutes don't change on later mentions.
- `neighbors._write` / `_visits`: a queued letter with `mentions_place` records a heard-of place; without the field,
  nothing; a GM failure still behaves as today.
- Backstop: `go_to Saltholm` with Briar's line in recent events starts a walk with the stored minutes; with the name only
  in Pip's own notes, it's still "you don't know a place".
- Directory, `where_to` and the to-do note show heard-of places; `specs_for` offers `gather` at a real shop and not at a
  sight or a heard-of place; a closed shop offers nothing.
- `arrive`: first arrival calls `design_place` once and stores a validated record (unknown kinds dropped, quantities
  from tiers, at most two tools, the promised "brass wire" present even when the GM left it out, existing names reused);
  GM failure leaves a bare place and a second arrival retries.
- `gathering.resolve` at an invented shop draws from its table, uses its capacity and refill, writes `on_account`.
- Owner paths: remove, patch (through the validator), `places.json` overlay precedence.
Then mutation testing on the touched modules **one at a time** (`invented_places`, `place_kinds`, `places`, `gathering`),
`nice -n 19 ... --max-children 4`, to the 95% gate.

## Build plan
1. **Heard-of places**: the `places` table, `invented_places.accept` with normalisation and caps, the `mentions_place`
   field on the three GM calls, the directory block, `go_to` to a heard-of place (walk only; arrival gets today's
   `describe_place`), `where_to`, the to-do note, the Saltholm backfill. Already fixes the dead-end to-dos.
2. **Real places**: `place_kinds.py`, `gm.design_place`, the loot builder and promise check, verb-based scoping for
   `gather`/`browse`, `gathering` lookups from the table, the darkness warning.
3. **Shops**: shop kind's hours and slow stock, `browse` stock view, rummage on account.
4. **Consistency and owner control**: the places line in neighbor prompts, `heard_of_place` events, `GET/PATCH /places`,
   `pipchat places`, the `places.json` overlay and export; README and ROADMAP updates.

## Not now
A map (walk times are from home only; "past Briar's, over the marsh" isn't modelled), a shopkeeper or villager as a
character (`characters` table, `say(to=...)`), places mentioned in books, by visitors in chat or by companion creations,
places growing new offers after they're real, coins and `buy`/`sell` (the economy, which this is shaped to hand over to),
places that change over time (a flooded path).

## Open questions for the owner
1. Lazy (real on first arrival, recommended) or real on first mention?
2. Rummage on account at shops until coins (recommended), or browse-only, or barter?
3. When a character mentions something new about a place that's already real (Saltholm's harbour), should the place gain
   it (one new loot entry or a verb, capped per place), or only record it as talk?
4. Caps: 2 heard-of a day and 12 invented places in all, with unvisited ones forgotten after 30 days. Right size?
5. Should a shopkeeper become a character Pip can talk to (more GM calls per visit), now or with the economy?
6. Should the owner's chat ("there's a market in the next valley") be able to create places too, or stay owner-only via
   `pipchat places add`?
7. `places.json` as an overlay now, or keep it with the public-repo extraction as DESIGN-places.md decided?

## Owner decisions (2026-10-31)
1. **Lazy**: heard-of on mention, real on first arrival.
2. **Rummage on account** at shops until coins.
3. **Places grow**: a later mention of something new at a real place (Saltholm's harbour) can add to it (a loot entry, a
   verb from the fixed set, or a line of description), capped per place.
4. **Light caps**, as proposed. Distance is a natural limit too: a place a character calls very far is heard-of but
   too far to walk to ("it's days away over the marsh"); it stays in what Pip knows without being reachable.
5. **Residents now**: a shopkeeper (or anyone who lives or works at a place) is a persistent character with their own
   history and memory, treated like a neighbor (the `characters` table; greeting once per visit, `say(to=...)`,
   capped replies; the gist/`told` memory of DESIGN-neighbor-memory.md). Unlike a neighbor they don't write letters.
6. **Chat can create places**: what a visitor says in chat counts as a mention, like a character's words.
7. `places.json`: later.
8. **Places needn't be useful**: some are just destinations (a lake with a nice view) with a description and no
   verbs. A kind for that is in the registry from the start.

## As built (2026-10-31)
Code: `brain/app/invented_places.py` (names, `accept`, `add_to`, the backstop, backfill, chat, design, loot, owner control,
the prompt seams), `place_kinds.py` (the kind registry), the `places` table in `state.py`, and small changes to `places.py`,
`gathering.py`, `tools.py`, `loop.py`, `gm.py` (`design_place`), `main.py`, `memory.py` and `pipchat`. Tests:
`tests/test_invented_places.py`, `tests/test_place_kinds.py`. Where it differs from the design above:

- **The characters' prompts**: `gm.neighbor_letter`, `gm.speak_in_person` (neighbors and residents) and
  `gm.invent_neighbor` take `mention` (the `invented_places.mention_instruction` sentence, listing every existing place
  name; when given, the report schema gains the optional `mentions_place`: `place`, `there`, `distance` enum
  `near|far|very far`, optional `items`, the things the character says can be had there); the letter and in-person
  calls also take `places`, that character's `places_line` ("Places in Pip's world: ...", their own mentions first, up
  to 8), shown after what Pip already knows about them. The GM methods only place the strings; `neighbors.py` builds
  them, and after every reply (a letter, a line in person, a new neighbor's first letter) passes the character's own
  words and the raw field to `invented_places.accept`. `neighbors.step` takes the library (the agent loop passes it) so
  the lists include it. `places.json` is not built (decision 7).
- **Residents (decision 5)**: `gm.design_place` may return one `resident` (`name`, `persona`, `about`; the prompt says a
  shop normally has its keeper, a wild place or a sight often nobody, and that someone the mentions name as being there
  is that person). `invented_places.settle` keeps them as a `characters` row of kind `resident` with the place's key in
  the new `place` column: name and persona required, clipped like a neighbor (40/800, `about` 160), never Pip or a name
  any character already has (case-insensitive); a `resident` event is logged. Only a successful design makes one, so a
  place gets at most one, at the moment it becomes real. Being met in person is generalised: `places.place_of(state,
  ch)` (a neighbor's home, a resident's place while it is real, else None) and `places.company_at`; `neighbors._visits`
  runs over everyone met in person, so a resident greets once per visit, answers `say(to=...)` under
  `COMPANION_REPLIES_PER_HOUR`, keeps `gist`/`told` exactly as a neighbor does, and their lines are `companion` events
  with `visit: true` (so memory, recall, people notes and firsts cover them unchanged). Differences from a neighbor: the
  in-person prompt says "who Pip meets at <place>" / "Pip is at <place>, with <name>" / "greet it" (no door) and
  "(oldest first; ...)" without "letters and"; it asks for an optional `life_update`/`life_update_new` (their life moves
  on in talk, since they never write; kept on the same rule as a letter's); no letters, no writing first, no plans
  (`upcoming`), no `recall_told` backfill (nothing to backfill). Pip learns the name only by being there: the
  perception says "<name> is here (<about>); talk with them in person using say with to: <name>." and nothing names them
  elsewhere. `say(to=...)` a resident from anywhere else, or while walking, gets "<name> can't hear you from here; go_to
  <place> to talk with them" (a neighbor's refusal mentions letters instead, which residents don't take); after the
  owner removes the place the resident stays in the table, never greets, and `say` gets just "can't hear you from
  here". `write_letter` to a resident is refused as for anyone who isn't a neighbor. `GET /places` lists each place's
  `residents` (name, about, life), removed places too, and `pipchat places` prints them. A resident's own place is in
  their "Places in Pip's world" line like any other (described from Pip's side: "Saltholm, a long walk (Pip has
  been)").
- **The table** has a few more columns than listed: `core` (the normalised name used for matching), `distance`,
  `on_account` (a map item -> qty), `grown` (growth used), `heard_at` (the last mention, for forgetting). `key` is
  case-insensitive. A place's key is fixed at its first mention (the proper-noun form of that name) and never renamed,
  because stock, finds and the kept description are keyed by it; later spellings become aliases.
- **Names**: the core keeps proper nouns minus trade words when the name has one; a capitalised plain adjective ("The Old
  Mill", "North") doesn't count as a proper noun, so "The Old Mill" and "the old mill" are one place. A name is refused if
  it is reserved (`home`, `house`, `workshop`, `library`, `wood(s)`, `junkyard`, `market`, `garden`), shares a word with
  Pip, any character's name, or the speaker's own name (so "A letter from Briar" never makes a place called Briar). A
  name the owner removed is never re-made.
- **Distance** (decision 4): near 12-20 min, far 20-35, very far = no walk at all (heard-of, too far to walk; `go_to` says
  so kindly, and the directory lists it in a third block). The 50-minute cap applies to the owner's `PATCH`, which can
  also make a very far place walkable or a walkable one very far.
- **Heard-of hours**: the kind is guessed from the name and `there` words at mention time (a shop word means shop
  hours, 9-17); the design may change it. A shut shop says when it opens ("it opens at 9:00"), in `go_to`, the
  perception and the refusal, instead of "it's dark".
- **The backstop** searches the last 20 things others said to Pip: `companion` events (companions, and neighbors in
  person), delivered letters and visitor chat (`inbox` events that are letters or not gifts), never Pip's own words or
  engine-written gift notes. The distance comes from cue words in the sentence ("days away" = very far, "just down the
  lane" = near, otherwise far). The backfill runs once (`meta invented_places_backfill`) when the agent starts, over the
  last 5000 events, and only counts a name a character wrote capitalised and mid-sentence (so "Ask" and "Thursday" in a
  to-do don't become places).
- **Chat (decision 6)**: the cheapest reliable detection is a few patterns on each visitor message as it arrives
  (`Agent.receive`), no GM call: a pointing phrase ("go to", "walk over to", "visit", "go and see"; "there's a ... in",
  "ask the ... in", "try the ... at"; "a lake/village/shop called") followed by a capitalised name or "the" plus up to two
  words and a landscape or settlement word ("the next valley", "the old mill"). Each hit goes through `accept` like a
  character's mention (caps, reserved names, neighbors). "I was in Berlin" or "a cat called Tom" record nothing; what the
  patterns miss, the backstop still catches because it searches chat too.
- **Design**: at most one successful design per rolling 24 h. The design call returns `kind`, `description`, `blurb`,
  `loot`, and for shops `opens`/`closes`, `gather_help`, `browse_help`, `gerund`. A design with no description is
  unusable (the place stays heard-of and bare, "you find Saltholm, but can't get your bearings today"). A place whose
  loot comes out empty gets no verbs.
- **Loot**: up to 10 GM entries, then the promised things. Promises are the `items` the characters named plus any
  existing item name that appears in a `there` note; a promise is kept by any entry whose name covers it ("brass wire"
  keeps "thin brass wire"), so no near-duplicates are added. Weights are drawn within the tier's range.
- **Scoping**: the built-ins keep their static scopes (`gather` at woods/junkyard, `browse` at library/junkyard, which
  existing tests pin); an invented place additionally offers whichever of `gather`/`browse` its record lists
  (`tools.listed_here`), and closed-place logic covers both. `browse` is still only enabled when the library is mounted
  (as before), so without one a shop offers `gather` alone.
- **Shops**: full yield at half the capacity (20 of 40), so a stocked shop isn't "picked over"; `browse` there shows up to
  4 things, fewer as stock runs down, "bare" at none, and the on-account list. The darkness warning in `go_to` is only
  for invented places (the built-ins are a short walk).
- **Growth (decision 3)**: up to 3 per place. A later mention of a real place naming something new (an `items` entry or a
  known item in its `there`) adds it as an uncommon find (a sight grows like a wild place and gains a gather verb); with
  nothing new to find, a new `there` becomes a line of description ("Morgan says: a harbour full of boats."). Mentions
  since the design also show in the directory blurb. A heard-of place only keeps the mention, and the design honours it.
- **Events**: `heard_of_place` is logged once, when the place is first recorded; it shows in recent events ("Briar told
  you about Saltholm: ...") and in recall.
- **Owner control**: `GET /places` (every row, all statuses, plus the built-in keys), `PATCH /places/<key>`
  (`walk_minutes`, `hours`, `description`, `loot`; anything else, or a bad value, is a 422), `DELETE /places/<key>`
  (status `removed`), `pipchat places` and `pipchat places rm NAME`. No `pipchat places add` or `export`.
