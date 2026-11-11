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
- **The world view**: a map and a scene for every place, drawn from layouts.
- **The builder**: a night-time role that proposes rules and places within your bible, for the owner to approve.

## 1. The smallest pack that runs
Four files and one module. With these, Wren lives in a shelter, gets tired and sleeps, talks to visitors, remembers, and can walk to
places as they're found. Nothing else happens yet, and that's fine.

```
worlds/ashfall/
  world.json
  persona.md
  narrator.md
  stats.json
  modules/shelter-layout.{json,py}
```

**`world.json`** (phase 1; `name`, `api` and `agent` work today, the rest later): who the agent is, the home, what's included.
```json
{"name": "Ashfall", "api": 1,
 "agent": {"name": "Wren", "pronoun": "she", "kind": "a survivor"},
 "home": {"key": "shelter", "label": "the shelter", "kind": "home"},
 "modules": ["ashfall:shelter-layout"],
 "settings": {"wake_hour": 6, "bedtime_hour": 22}}
```
`agent.kind` is how the narrator refers to her in a word. `home` is the place she starts and sleeps. `modules` are what the world includes:
`ashfall:` names the pack's own (in `modules/`), `std:` the engine's standard library.

**`persona.md`** (works today; `PERSONA_PATH` overrides it): who the agent is, in the second person, as the agent reads it every tick. Who she is,
how she talks, what she cares about, what she wants. Not the world's rules: those come from the guide.

**`narrator.md`** (works today): the narrator's voice and the world in a paragraph. The engine adds its own fixed instructions (never decide
for the agent, never change a result, keep things plausible, the content floor); this file says what plausible means here.
```
A dead city under a grey sky, twenty years after the ash. Survivors live in shelters and a walled village by the reservoir; the city
is picked over, dangerous and slowly being reclaimed by weeds. Tell things plainly and without melodrama: hardship is ordinary here,
and so are small kindnesses. Nothing is magic; the monsters are animals the ash changed, and they behave like animals.
```

**`stats.json`** (phase 3): what she needs. At least one stat; energy is the usual first, since sleep and rest restore it.
```json
{"energy": {"start": 1.0, "decay_per_hour": 0.03, "low": 0.25, "restored_by": ["rest", "sleep"], "floor": 0.1}}
```

**The home's layout**: a place module that lays out the shelter (works today; see DESIGN-modules.md, "Parts and layouts", and the
shipped `home` layout in `app/module_library/` for a full example). At its smallest: a ground box, a building from the `cutaway` part,
and anchors tagged `pip` (where she stands), `bed` and `seat` (renamed `agent` in phase 1), so the renderer can draw her poses.

Start it with `WORLD_PACK=worlds/ashfall` (works today). Check the dashboard: the scene, the journal filling, the Work tab's modules all live.

## 2. Give the day something to do
An agent with nothing to do will mostly think, note and sleep. Add features, smallest first. Each is a module, from the standard library
or your own.

**Needs that matter** (phase 3): a stat that rises and something that lowers it. Hunger and food:
```json
"hunger": {"start": 0.0, "rise_per_hour": 0.04, "high": 0.8, "restored_by": ["eat"]}
```
and in **`items.json`** (phase 2), an item kind that restores it and something to start with:
```json
{"kinds": {"food": {"restores": {"hunger": 0.3}}, "scrap": {}, "tool": {}, "medicine": {}},
 "start": [{"name": "tinned beans", "kind": "food", "qty": 4, "description": "dented tins, still sealed", "restores": {"hunger": 0.5}}],
 "finds": {"ruins": [["scrap metal", "scrap", 30, [1, 3], "bent sheet and rebar"], ["tinned beans", "food", 8, [1, 1], "a tin, still sealed"]]}}
```

**Somewhere to go and something to find** (phase 2 for data, phase 5 for gathering as a module): `places.json` names the places the
world starts with and the kinds it can grow.
```json
{"start": [{"key": "the old mall", "kind": "ruins", "distance": "near", "description": "A collapsed shopping centre, half flooded."}],
 "kinds": {"ruins": {"help": "a ruined building to scavenge", "words": ["ruin", "mall", "tower", "station", "depot"],
                      "verbs": {"gather": ["scavenge what's left", "scavenging"]}, "loot": ["scrap", "food", "tool", "medicine"]}}}
```
Include `std:gathering` in `world.json` and the `gather` tool works wherever a place's kind has the verb, from the `finds` tables.

**Trade** (phase 4/5): include `std:market` with params (the currency's name, how prices move), and give a place kind `trades: true`.
The village's market and Wren's own stall then work as Pip's do.

**People** (works today for voices; phase 5 for characters with letters and visits): a village of survivors starts as a module with
`voices`: the quartermaster, the medic, a child who follows Wren around. Each `on_message` keeps its own memory and `ask`s for its
words; see `app/module_library/workings.py` (companions) for the pattern. With `std:letters`, they can also write.

## 3. Let things go wrong
**Tone** (phase 3): `tone.json` says what the world's words and events may be. Ashfall allows more than Pip's world:
```json
{"refuse_words": ["gore", "torture"], "big_words_from": "medium", "bad_weight": 1.0,
 "caps": {"coins": {"major": [25, 0.35]}, "harm": {"minor": 0.05, "medium": 0.15, "major": 0.35}}}
```
The engine's floor still holds whatever this says: no sexual content, nothing encouraging self-harm, nothing about real people.

**Stakes** (phase 6): a stat that can run out, and what happens then.
```json
"health":    {"start": 1.0, "low": 0.3, "at_zero": "knocked_out", "restored_by": ["rest", "use:medicine"]},
"radiation": {"start": 0.0, "high": 0.6, "shown": "radiation sickness", "restored_by": ["use:rad pills"], "harms": {"health": 0.02}}
```
`knocked_out` costs time and wakes her in the shelter with a happening saying what happened; nothing is permanent.

**Happenings** (works today as `happen`; phase 2 moves the categories to data): include `std:happenings` with params, and give it the
world's categories: `raid` (bad: `harm`, `food_loss`), `salvage` (good: `item`), `ashfall` (bad: `energy`, `radiation`), `kindness`
(good: a gift from someone in the village). Each says its tones and what may change; the engine sizes every effect from `tone.json`.

**Monsters**: a rule module with `happen` (an attack, sized by severity) and, if they should be met, `voices` (things that growl back) and
a layout's live elements for where they prowl. They can hurt through `harm`; they can't decide for Wren.

## 4. Make it look like itself
**Scene vocabulary** (phase 2): `scene.json` lists the props, settings, looks and palettes the narrator picks from and the renderer
draws: `"settings": ["ruins", "wasteland", "village", "reservoir"]`, `"props": {"barricade": ["barricade", "wall"], "geiger": ["geiger",
"counter"]}`, `"palettes": {"ash": ["#6b6862", "#a39e93", "#c9b38c"]}`.

**Layouts** (works today): every place kind needs a layout module (`kinds: ["ruins"]`) built from parts. Start from the shipped
`outdoors`, `market` and `home` layouts in `app/module_library/` and change the parts and textures; the shapes, anchors and live elements
are the same in any world.

**Textures** (phase 2): a pack can add textures as small generator functions or images in `scene/`.

## 5. Let it grow
**The bible** (works today; `WORLD_BIBLE_PATH` overrides it): `bible.md` tells the builder what belongs in this world
and what doesn't, so its nightly proposals fit. Ashfall's might allow danger and loss but not cruelty, and ask for rules that make the
world feel lived in: a curfew bell, a trader's caravan every few days, the reservoir's level after rain.

**The guide** (works today: the engine reads the topics it knows, `app/guide/__init__.py`; phase 5 lets features bring their own):
`guide/*.md` tells Wren how her world works, in the second person, a few lines a page: home, her needs, the
places, the people. Features bring their own pages (`std:market` brings the market's); the pack adds what's particular to it.

**Real-world sources** (phase 5): decide whether the world touches the real one. Ashfall probably wants its own weather (a module that
invents ash days and acid rain and publishes them as the world's weather), no web search, and maybe the owner's books as a ruined archive.

## Checklist
- [ ] `world.json`: name, agent (name, pronoun, kind), home, modules
- [ ] `persona.md`: who the agent is
- [ ] `narrator.md`: the world in a paragraph, and how to tell it
- [ ] `stats.json`: at least energy
- [ ] A layout for the home, with `agent`, `bed` and `seat` anchors
- [ ] `items.json`: kinds, something to start with, what can be found
- [ ] `places.json`: somewhere to go, and the kinds of place the world can grow (each with a layout)
- [ ] Features: `std:` modules included and configured, or the pack's own
- [ ] `tone.json`: what the world allows (or the engine's gentle defaults)
- [ ] `bible.md` and `guide/*.md`
- [ ] Run a day: the scene draws, the journal fills, nothing in the log says "refused" or "failed"
