# Guide: bootstrapping a world pack

Status (2026-11-11): **a target, not yet true.** This describes the world-pack format designed in
[DESIGN-world-packs.md](DESIGN-world-packs.md). Today the engine still carries Pip's world in its code; each section says which phase of
that design makes it work. Keep this guide in step as the phases land: when a phase ships, its sections lose their "(phase N)" note.

A world pack is everything that makes a world *that* world: who lives in it, what they need, where they can go, what they do, what can
go wrong, how it looks. The engine supplies the rest: an agent with a memory, feelings, sleep and a day; places to walk between; people to
talk to; things that happen; a referee for everything modules propose; and a view to watch it all in. This guide walks through the
smallest pack that runs, then how it grows. The running example is a post-apocalyptic one, **Ashfall**: a survivor called Wren in a
shelter at the edge of a dead city.

## What the engine gives every world
Before writing anything, know what you don't have to:
- **The mind**: memory and journal, recall, the nightly reflection and night pass, emotions, expectations, wishes, notes, and the tools
  for them (`note_to_self`, `recall`, `feel`, `settle`, ...). Worded around your agent's name.
- **The day**: real time, sleep and waking, bedtime and wake hours, resting.
- **Places**: a map that grows as places are found, walking between them (`go_to`), places invented from what characters mention.
- **People and talk**: visitors (the owner and friends, through the web chat or Matrix), `say`, voices modules own, conversation memory.
- **Happenings**: the dice's checks, the words, and how the agent takes them in.
- **Belongings and a purse**: items by kind, and a currency.
- **The world view**: a map and a scene for every place, drawn from layouts, and a plain page to watch it on (the agent's state, its
  scene, what its modules show it, what happened lately) until the pack brings its own.
- **The builder**: a night-time role that proposes rules and places within your bible, for the owner to approve.

`worlds/ashfall` is this guide's world built (0.44.0): a shelter, the ruins and the river flats to scavenge and forage, health and
radiation, raids, and a village of voices. Its CI test runs a day of it with fake models and fails if anything of Pip's world comes
through (`tests/test_ashfall.py`). Read it alongside this guide.

## 1. The smallest pack that runs
Four files and one module. With these, Wren lives in a shelter, gets tired and sleeps, talks to visitors, remembers, and can walk to
places as they're found. Nothing else happens yet, and that's fine.

```
worlds/ashfall/
  world.json
  persona.md
  narrator.md
  stats.json
  modules/shelter.{json,py}
```

**`world.json`** (works today): who the agent is, and what the world runs.
```json
{"name": "Ashfall", "api": 1,
 "agent": {"name": "Wren", "pronoun": "she", "kind": "a survivor", "lives": "lives alone in a shelter under a dead city"},
 "modules": ["std:cutaway", "std:gathering", {"module": "std:crafting", "params": {"most": 2}}, "ashfall:shelter", "ashfall:raids"]}
```
`agent.kind` is how the narrator refers to her in a word. `modules` (0.44.0) are what the world runs, in order: `std:<name>` one the
engine ships (`app/module_library/`), `<pack>:<name>` the pack's own (`modules/<name>.json` and `.py`, trusted like the engine's), or
`{"module": ..., "params": {...}}` to set its params (over its defaults and anything the settings set). A module that builds from parts
needs them listed too (`std:outdoors` uses seven). The kinds of thing a module takes and gives are kept to the world's (a world without
seeds gathers none). A pack that names no `modules` runs everything the engine ships, as Pip's world does. The home (its key and label)
is in `places.json`.

**`persona.md`** (works today; `PERSONA_PATH` overrides it): who the agent is, in the second person, as the agent reads it every tick. Who she is,
how she talks, what she cares about, what she wants. Not the world's rules: those come from the guide.

**`narrator.md`** (works today): the narrator's voice and the world in a paragraph. The engine adds its own fixed instructions (never decide
for the agent, never change a result, keep things plausible, the content floor); this file says what plausible means here.
```
A dead city under a grey sky, twenty years after the ash. Survivors live in shelters and a walled village by the reservoir; the city
is picked over, dangerous and slowly being reclaimed by weeds. Tell things plainly and without melodrama: hardship is ordinary here,
and so are small kindnesses. Nothing is magic; the monsters are animals the ash changed, and they behave like animals.
```

**`stats.json`** (works today): what she needs. At least one stat; energy is the usual first, since sleep and rest restore it.
```json
{"energy": {"start": 1.0, "per_hour": -0.03, "asleep_per_hour": 0.25, "resting_per_hour": 0.3, "alert": {"below": 0.2}, "low_at": 0.25,
            "restored_by": ["rest", "sleep"], "floor": 0.1, "tires": true, "tired_below": 0.3, "scale": "0=exhausted"}}
```
`good` is `high` unless you say `low`; `low_at` is where the world starts sparing her; `tires` marks the stat work wears down;
`away_per_hour` (0.44.0) is its rate while she is out of her home (radiation builds outside, and falls at home).
`worlds/pip/stats.json` has every field.

**The home's layout**: a place module that lays out the shelter (works today; see DESIGN-modules.md, "Parts and layouts", and the
shipped `home` layout in `app/module_library/` and Ashfall's `modules/shelter.py`). At its smallest: a ground box, a building, and
anchors tagged `agent` (where she stands), `seat` and `workbench`, so the renderer can draw her poses.

Start it with `WORLD_PACK=worlds/ashfall` (works today). Check the dashboard: the scene, the journal filling, the Work tab's modules all live.

## 2. Give the day something to do
An agent with nothing to do will mostly think, note and sleep. Add features, smallest first. Each is a module, from the standard library
or your own.

**Needs that matter** (works today): a stat that rises and something that lowers it. Hunger and food:
```json
"hunger": {"start": 0.0, "per_hour": 0.04, "alert": {"above": 0.8}, "low_at": 0.8, "good": "low", "restored_by": ["eat"],
           "plain_meal": 0.3, "scale": "1=starving"}
```
and in **`items.json`**, an item kind that restores it and something to start with (a food's `restores` says what it restores and by
how much; one without restores `food_default` of whatever `eat` restores):
```json
{"kinds": ["food", "scrap", "tool", "medicine"], "food_default": 0.3,
 "start": [{"name": "tinned beans", "kind": "food", "qty": 4, "description": "dented tins, still sealed", "attrs": {"restores": {"hunger": 0.5}}}],
 "finds": {"ruins": [["scrap metal", "scrap", 30, [1, 3], "bent sheet and rebar"], ["tinned beans", "food", 8, [1, 1], "a tin, still sealed"]]}}
```

**Somewhere to go and something to find** (works today; gathering is the shipped `gathering` module): `places.json` names the home, the
places the world starts with, and the kinds of place it can grow. See `worlds/pip/places.json` for every field.
```json
{"home": {"key": "shelter", "description": "your shelter", "offers": ["sleep"], "about": "a concrete bunker", "aliases": ["home", "bunker"],
          "called": "shelter"},
 "start": [{"key": "the old mall", "description": "a collapsed shopping centre, half flooded", "walk": 12, "kind": "yard", "tag": "salvage",
            "offers": ["gather"], "daylight_only": true, "verbs": {"gather": ["scavenge what's left", null]}}],
 "kinds": {"ruins": {"help": "a ruined building to scavenge", "words": ["ruin", "mall", "tower", "station", "depot"],
                     "verbs": {"gather": ["scavenge what's left", "scavenging"]}, "loot_kinds": ["scrap", "food", "tool", "medicine"]}},
 "fallback_kind": "ruins", "words": {"trade": ["camp", "trader"], "reserved": ["home", "shelter"], "features": ["ruins?", "camp", "reservoir"]}}
```
The `gathering` module's `gather` tool works wherever a place lists `gather` among its verbs, from the `finds` tables in `items.json`
(keyed by place); its params name the abilities gathering practises. `WILD_PLACES` can leave
some of the starting places out.

**A feature of your own** (works today): a module can be a whole feature. The shipped `garden` (`app/module_library/garden.py` and
`.json`) is the example to copy: tools the agent uses (`plant`, `harvest`, at home), its own store (the plots), what it takes and gives
(a seed in, food out), a status section the agent sees every tick ("Your garden: plot 1: peas growing, ready in about {in:...}"), a
logged moment that wakes the agent (a crop ripening), and what other modules may ask of it (`hurry`, `crop`, `add_plot`). Ashfall's
version might be a still for clean water, or a salvage bench. See DESIGN-modules.md, "What a feature needs", for every hook.
A feature's own events (works today, 0.46.0) say how the engine reads them: what the agent remembers of a salvage run, how it feels, the
first time it found a working radio, what it says of her scavenging, and what the feed shows (DESIGN-modules.md, "A module's own
events"; crafting's `read_of` is the full example).

**Trade** (works today; the shipped `trade` module): give a place kind `trades: true` (and `stalls: true` for a market) and its
`finds` are what its booth sells; the village's market and Wren's own stall then work as Pip's do. Its prices, tills and stall live in
the module's store, so a world that trades differently (barter, ration chits) copies `app/module_library/trade.py` and changes it.

**Making things** (works today; the shipped `crafting` module): projects on the agent's own plans, judged by the die and the narrator,
with experiments, plan revisions and craft skills; a finished project becomes one of its creations. The abilities a stage exercises
are the pack's (`content.json` `crafting`); a world that makes things differently (scavenged repairs, rationed parts) copies
`app/module_library/crafting.py` and changes it.

**Books** (works today; the shipped `reading` module on the engine's `books` source): with a library mounted (`LIBRARY_PATH`), the
agent reads the owner's real books at the `library` place. Ashfall's version of it (a ruined archive) is a module of its own that asks
the same source (`"sources": ["books"]`) and words it as salvaged pages, or ships a list of its own and asks nothing.

**People** (works today for voices; phase 5 for characters with letters and visits): a village of survivors starts as a module with
`voices`: the quartermaster, the medic, a child who follows Wren around. Each `on_message` keeps its own memory and `ask`s for its
words; see `app/module_library/workings.py` (companions) for the pattern. With `std:letters`, they can also write.

## 3. Let things go wrong
**Tone** (works today): `tone.json` says what the world's words and events may be. Ashfall allows more than Pip's world:
```json
{"deny": ["gore", "torture\\w*"], "big_words": [], "text": {"max": 420},
 "sizes": {"stat": {"minor": 0.05, "medium": 0.15, "major": 0.35}, "coin_caps": {"minor": [3, 0.1], "medium": [10, 0.2], "major": [25, 0.35]}}}
```
Words are regular expressions, matched whole; a size table you give replaces the engine's, one you leave out keeps it. See
`worlds/pip/tone.json` for every size. The engine's floor still holds whatever this says: no sexual content, nothing encouraging
self-harm, nothing about real people.

**Stakes** (works today, 0.43.0): a stat that can run out, and what happens then (`at_zero`).
```json
"health":    {"start": 0.9, "per_hour": 0.01, "low_at": 0.3, "at_zero": "knocked_out", "out_hours": 4, "recovers_to": 0.4, "scale": "0=dying"},
"radiation": {"start": 0.0, "per_hour": 0.002, "good": "low", "low_at": 0.6, "at_zero": "weak", "label": "radiation sickness"}
```
`knocked_out`: whatever she was doing ends, and she comes to in the shelter `out_hours` later with the stat at `recovers_to` (by
default a little past `low_at`). `weak`: whatever she was doing ends, and until the stat is off its low side she can only eat, rest,
sleep, talk and think. Nothing is permanent: no death, no lost memory. The world hurts her through a happening's `harm`
(`{"kind": "harm", "stat": "health"}`, a bad turn sized by `tone.json`'s `harm`; unlike other bad turns it isn't spared when she is
low, but never lands while she is already down) or a module's `affect`.

**Happenings** (works today as `happen`; phase 2 moves the categories to data): include `std:happenings` with params, and give it the
world's categories: `raid` (bad: `harm`, `food_loss`), `salvage` (good: `item`), `ashfall` (bad: `energy`, `radiation`: any stat by its name), `kindness`
(good: a gift from someone in the village). Each says its tones and what may change; the engine sizes every effect from `tone.json`.

**Monsters**: a rule module with `happen` (an attack, sized by severity) and, if they should be met, `voices` (things that growl back) and
a layout's live elements for where they prowl. They can hurt through `harm`; they can't decide for Wren.

## 4. Make it look like itself
**Scene vocabulary** (works today): `scene.json` lists what the narrator picks from when it chooses how people and places look:
`look` (heights, hair, skin, clothes), `look_hints` (words in a persona that settle a feature), `props` (each with the words that bring it
into a scene), `scene` (walls, roof, palette, setting), `setting_words`, `kind_setting`, and `coastal_words` (what puts a place by the
water). The browser draws only the values it knows (see `worlds/pip/scene.json`), so for now a pack chooses among those; new ones need
textures or sprites (below).

**Layouts** (works today): every place kind needs a layout module (`kinds: ["ruins"]`) built from parts. Start from the shipped
`outdoors` and `market` layouts in `app/module_library/`, Pip's `home` (`worlds/pip/modules/home.py`) or Ashfall's `shelter`, and change
the parts and textures; the shapes, anchors and live elements are the same in any world. An anchor with `words` is where the agent paces
while what it is doing says one of them (Pip's garden path: "garden", "harvest"...); a shape with `when: ["has:<anchor>"]` shows only
while a module shows something on that anchor.

**The agent** (0.48.0): how a scene draws the agent. `sprite.json` is its own pixel frames, `{"palette": {...}, "frames": [...]}`,
ten of them in order: 0-1 standing, 2-5 walking, 6 asleep, 7-8 working (a tool up, then down), 9 sitting (Pip's is
`worlds/pip/sprite.json`). Without one, it is drawn like a person, from `"look"` in `world.json`'s agent (words from `scene.json`'s
`look` lists: Ashfall gives Wren auburn hair and a scarf), or from its name and persona.

**The page** (0.48.0): a pack's `web/` folder is its page, served at `/ui/` (Pip's dashboard is `worlds/pip/web/`). It may load the
engine's scene and map renderer (`./world/scene.js`, `./world/map.js`), which a pack can't replace, and read `/state`, `/standing`,
`/events`, `/published` (what each live module publishes), `/characters`, `/world/scene` and the rest. A pack without one gets the
engine's plain page.

**Textures** (later): a pack can add textures as small generator functions or images in `scene/`.

## 5. Let it grow
**The bible** (works today; `WORLD_BIBLE_PATH` overrides it): `bible.md` tells the builder what belongs in this world
and what doesn't, so its nightly proposals fit. Ashfall's might allow danger and loss but not cruelty, and ask for rules that make the
world feel lived in: a curfew bell, a trader's caravan every few days, the reservoir's level after rain.

**People** (0.50.0): a module brings someone into the world with `character` (a name, a word for their role, who they are, what the
agent would know of them, and `home`: where they live). Whoever is at a place is met in person there, through the engine's talk scenes:
Ashfall's `village` module brings Marta, Ezra and Jun to the village, one a day. Someone brought with `writes: true` also exchanges
letters with the agent over hours (a neighbour, a distant cousin, a radio operator), and a module can ask them to write first. Someone brought without a home gets one of their own,
as `places.json` `dwellings` says (`{"kind": "neighbor", "called": "{name}'s home"}` in Pip's world; a `dwelling` otherwise). Every
kind of place is the world's: the agent's `home`, the dwellings', the library's (`library.kind`), the places it starts with and the
kinds it can grow, and a layout module may cover only those.

**The guide** (works today; since 0.49.0 every page says when it applies): `guide/*.md` tells Wren how her world works, in the second
person, a few lines a page: home, her needs, the places, the people. Each page starts with a front matter saying where it goes and
what it needs, and the engine names no page:

```
---
order: 60
when: tool start_project
---
```

`when` is conditions joined by "and": `always`, `tool a|b` (any of those tools is enabled), `setting name` (on) or `setting name=value`,
`library` (books are mounted), `stakes` (a stat can run out), `reflection` (the agent reflects at night). `bullet: yes` puts a page
in the closing "Guidelines" list. A page without front matter is always told, after the rest. A page that can't be read stops the
pack from loading, with what's wrong with it (`app/guide/__init__.py`).

**Plans** (0.49.0): what the agent has going that its sleeping self may put on hold (crafting's projects, a world's repairs) is
whatever a module publishes as `plans`, with `pause` and `resume` among its answers (docs/DESIGN-nightpass.md).

**Real-world sources** (works today for the books and the weather): decide whether the world touches the real one. Pip's world uses the
shipped `sky` module, which asks the `weather` source and publishes the world's `weather` and `season`. Ashfall probably wants its own
weather instead: a module that invents ash days and acid rain and publishes them as `weather` (and its own `season`), asking no source;
no web search; and maybe the owner's books as a ruined archive.

**Registries** (works today): `content.json` holds the world's lasting effects (what a finished project can change, and the line that
says so), its abilities (what a working thing can give: the time, news), crafting's abilities (what a stage of work exercises) and what
the first happening of each kind is called. See `worlds/pip/content.json`.

## Checklist
- [ ] `world.json`: name, agent (name, pronoun, kind), home, modules
- [ ] `persona.md`: who the agent is
- [ ] `narrator.md`: the world in a paragraph, and how to tell it
- [ ] `stats.json`: at least energy
- [ ] A layout for the home, with `agent`, `bed` and `seat` anchors
- [ ] `items.json`: kinds, something to start with, what can be found
- [ ] `places.json`: somewhere to go, and the kinds of place the world can grow (each with a layout)
- [ ] Features: `std:` modules included and configured, or the pack's own
- [ ] `tone.json`: what the world allows (without it, the engine's sizes and only its floor's words)
- [ ] `bible.md` and `guide/*.md`
- [ ] How the agent looks: `sprite.json`, or a `look` in `world.json`
- [ ] Optionally `web/`: a page of its own (otherwise the engine's plain page)
- [ ] Run a day: the scene draws, the journal fills, nothing in the log says "refused" or "failed"
