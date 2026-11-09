# Design: the world view (a map and scenes)

Status (2026-11-08): designed; **step 1, the map, built (0.12.0)**. The owner chose the direction from five throwaway prototypes (links below). Read-only: the view
shows the world; it never changes it.

## What it is
The dashboard's World tab grows into two views of the same live state:
- **The map**: a parchment overworld, generated in the browser from a fixed seed around the engine's real place coordinates. Only what Pip
  has walked to is painted; the rest is blank parchment that fills in as Pip explores. While Pip walks, its marker moves along the road.
- **The scene**: wherever Pip is, a small HD-2D diorama of that place (pixel-art textures on simple 3D shapes, flat sprite characters,
  a fixed camera, a gentle depth blur, warm light), showing what is actually happening there: who is present, what is for sale, what Pip
  is doing, the time of day and the weather.

Prototypes (private artifacts; snapshots of the live API on 2026-11-08, not wired to it):
the map https://claude.ai/artifact/HMZ2beA9z1TMrvSDsqhwVe ·
the workshop https://claude.ai/artifact/SXFc6LkS3aNGZLjuLyJ3nN ·
Oriel's cottage https://claude.ai/artifact/W4e6JerVDhidnUkCeZ3UjN ·
Brygdon market https://claude.ai/artifact/9ibofMSUHx9NSZwq6G3CtC.

## What the owner decided (2026-11-08)
- The **Octopath Traveler (HD-2D) look**, but leaning harder into 2D: a **fixed** camera (orthographic, one angle, never orbits), the whole
  frame drawn at **512 × 288** and scaled up with crisp pixels, so the 3D shapes read as pixel art.
- Buildings are **opened like a dollhouse** (no front wall, no front roof slope), so the life inside shows in the same view as the yard.
- The glow is **light**: it catches only real lights (windows, lamps, lanterns, fireflies); the grade is warm with a little contrast and
  saturation. An earlier pass was "washed out rather than warm"; don't go back there.
- The **parchment map** is the part the owner likes most.
- Textures and sprites are **generated in code** for now; hand-made art is a later pass (see "Assets").

## Principles
- **The engine stays the source of truth.** The view only reads. Anything shown that isn't in the engine (a tide, a shopper, a curlew) is
  decoration, deterministic from the clock and the place's key, and never presented as a fact (it has no tooltip claiming otherwise).
- **No per-place hand-building.** Most places are invented by the GM while Pip lives (Saltholm, Brygdon, Oriel's cottage). Every scene
  comes from a **template per place kind**, filled from the place's record. A new place gets a scene the moment it is real.
- **Stable.** The same world draws the same way every time: the map from a world seed, a scene's layout from its place key. A new place is
  fitted in; nothing reshuffles.
- **Facts in tooltips.** Hovering anything shows the engine's own data behind it (a plot's growth, a booth's stock, a creation's quality).
- Same public/owner split as the rest of the dashboard (DESIGN-public-view.md): the public view gets the map and the scenes, with names
  redacted and no visitor or letter text.

## Architecture
All rendering happens in the browser. The engine adds two read-only endpoints and a few stored fields; nothing in the loop changes.

**Front end** (`web/world/`, plain ES modules like the rest of `web/`):
- `map.js`: map generation and drawing (Canvas 2D, as in the prototype).
- `kit.js`: the scene kit: renderer at 512 × 288, the fixed orthographic camera, lighting from time/season/weather, the post pass (depth
  blur, light bloom, warm grade, vignette), tooltips by raycast, sprite billboards, reduced-motion and low-power handling.
- `art.js`: texture and sprite generators behind one interface (`texture(name)`, `sprite(name)`), so the later art pass swaps an atlas
  in without touching the templates.
- `templates/<kind>.js`: one per place kind (below).
- `world.js`: the World tab: fetches, chooses map or scene, switches between them.
- **three.js r128, vendored** in `web/vendor/` (MIT, with its licence file) rather than loaded from a CDN: the dashboard is served from the
  homelab and should not depend on a third-party host. Same for the post-processing passes (EffectComposer, RenderPass, ShaderPass,
  UnrealBloomPass and their shaders).

**API** (`app/world_view.py`, routes in `main.py`, both added to the public allowlist):
- `GET /world/map`: everything the map needs in one call:
  `seed` (a world seed, created once and kept in `meta.world_seed`), `places` (key, label, kind, x, y, status real/heard, visited, first
  visited), `roads` (from home to each visited place, with how often Pip has walked it), `pip` (where it is, or the walk in progress:
  from, to, started_at, ends_at), `now` (time, season, weather).
- `GET /world/scene?place=<key>` (default: where Pip is): the place record (kind, label, description, hours, open now, `scene` details,
  below), **who is present** (via `places.place_of`, so Oriel is at Brygdon on her market day), **booths** (`market.booths`, each with stock
  left and today's prices), **Pip's stall** there, **Pip** (activity, description, mood, the current session and its kind and progress),
  and the kind-specific extras: at home the garden, creations (with the clock's face from `creations.clock_face`) and belongings; at the
  library the book being read; in the wild what can be gathered (`gathering.glimpse`, names only). Plus `now`.
- Public responses go through the same redaction as `/events` (`public_view`): character names as configured, no visitor text, no letters.

## The map
As prototyped (`pip-map.html`), moved into `map.js`:
- **Land** = seeded value-noise FBM with a domain warp, plus a broad continental rise around Pip's places, an ocean side and a hills side
  chosen from the seed, and a small rise under every place so each always sits on land. Moisture is a second noise field.
- **Biomes** from height and moisture (sea, shallows, beach, marsh, grass, forest, hills, peaks, snow), painted as washes, hill-shaded,
  over a procedural parchment (stains, darkened edges).
- **Ink**: the coastline and two offshore ripple lines by marching squares; glyphs for mountains, hills, trees and marsh tufts on a
  jittered grid; dotted roads that wander a little; small ink drawings and label plaques per place kind; a compass rose; a cartouche; a
  **scale bar in minutes of Pip's walking** (a map unit is a minute's walk in the engine).
- **Explored**: paint fades out a little beyond each visited place and along the roads walked; everything else is blank parchment.
  A heard-of place appears as a pencilled "?" with its name in italics where its rough distance and direction put it (if the engine has
  a position for it), so Pip's knowledge and its experience look different.
- **Stability**: the land is a function of the seed and the places. Adding a place only raises land near it (the rise is local), so the
  rest of the map doesn't move. The drawn sheet is cached in the browser by seed + place list.
- **Pip on the map**: a small flag at its place, or moving along the road during a walk (`started_at` to `ends_at`). Clicking a place opens
  its scene as it is now (a peek; see Open questions).

## Scenes
**The kit** (from the prototypes): 512 × 288, fixed orthographic camera, generated pixel textures with nearest filtering, sprites as
camera-facing planes that cast shadows, a sun and sky from the time of day (later season and weather), point lights for windows and lamps
that come up at dusk, motes that become fireflies at night, the post pass, hover tooltips. 30 fps cap, paused when the tab is hidden; the
post pass is skipped on weak devices (a frame-time check) and with reduced motion only the motion stops.

**Templates, one per place kind** (the built-in home, library and neighbors' homes, plus the invented kinds in `place_kinds.py`; the prototypes cover the first three):

| Kind | Scene | Filled from |
|---|---|---|
| home | the workshop cutaway: bench, stool, shelf, clock; garden plots; fence, path, bridge | garden, creations (each by capability: the clock shows its real face and drift, a walker walks), belongings, the current session |
| neighbor | a cottage cutaway with the neighbor in it; a yard; their trade on show | the character's look and persona details, what they've told Pip (the `told` list feeds props: a tin by the door), wares, market day (away: a note on the door) |
| market | a square of booths, houses around it, a well or cross, people | booths and stock, characters with a stall here today, Pip's stall, hours (awnings roll up when shut) |
| shop | a shopfront and counter with the keeper, shelves or drawers of stock | the booth's stock and prices, the keeper (a resident), what Pip has on account |
| library | tall shelves, a reading table, a lamp | the book Pip is reading and its progress |
| wild | open ground: woods, flats, shore, by the place's description | what can be gathered there (shown as small sprites), the current gather session |
| yard (the junkyard, a quarry, a tip) | heaps of scrap or spoil, a shed | what can be gathered |
| sight | a scenic spot with a viewpoint | the description |

**Variation from the record** (so invented places look like themselves): when a place becomes real, the GM picks its scene details once,
from a **fixed vocabulary**, and the engine validates and stores them on the place as `scene` (JSON):
- `walls` (plaster and timber, whitewash, stone, brick, planks), `roof` (thatch, slate, shingle, tile), `palette` (one of eight),
- `setting` for outdoor kinds (wood, heath, shore, marsh, hills, riverside),
- `props`: up to four from a catalogue the kit can draw (lighthouse, well, nets, lanterns, barrels, drawers, rope coils, boats, beehives,
  washing line, signpost, crates, cart, chimney smoke, flower boxes, standing stones…).
Unknown values are dropped; if the call fails, the details are chosen deterministically from the kind, the place key and keywords in its
description ("harbour" brings rope and boats). Existing real places get theirs once, by a small backfill.

**Characters** get a `look` the same way, once, when they are invented: height, hair, two clothing colours, an accessory (shawl, apron,
hat, glasses, satchel), all from fixed lists, so the sprite generator can draw them. Oriel's would come out tall, white-haired, grey shawl.
Pip's own sprite is fixed. Shoppers and passers-by are decoration: generated from the place key, never named.

**Pip's activity → pose**: a work or experiment session → at the bench, hammering; reading → in a chair with a book; gathering → crouched,
searching; a walk → the map; asleep → eyes shut, "z"; a timed wait or rest → sitting; otherwise idle. The `description` is the tooltip.

**Live state on show** (each a mapping from an engine fact to a visual, kept in one table in `world.js`): opening hours (shut: awnings
rolled, lights off, no keeper); who is present; stock left (fewer goods on the table as it sells); Pip's stall and its sales (a coin pop
per `stall_sale` event, from the event stream); crops by growth; creations by state (a stopped clock's pendulum hangs still); weather (rain,
snow, overcast light) and season (palette tint, leaves); a happening as a small transient prop where the engine names a thing (later).

## Switching between them
The World tab opens on the scene where Pip is. When a walk starts (`/stream` already pushes events), it cuts to the map with Pip's marker
moving for the length of the walk, then opens the scene at the place it arrives. A small toggle shows the map at any time. Everything
refreshes from the stream; no polling beyond what the dashboard does today.

## Assets
**The build needs none.** Everything in the prototypes is drawn in code, and the first version keeps it that way. Fonts come from Google
Fonts (OFL) like the rest of the dashboard; three.js is MIT.

**The later art pass** is where hand-made art pays off, mostly for **characters** (Pip, the neighbors, people), which are what the eye goes
to; generated materials (thatch, plaster, cobbles, grass) hold up better. Options, in the order I'd suggest:
1. **Pixel sprites authored as data in the repo**: small indexed-palette sheets written by hand (by the owner, or drafted by Claude and
   tuned by eye), loaded through `art.js`. No licences to track; fits the code-generated textures.
2. **CC0 packs** (no attribution needed, safe for this public repo): good for props and tiles. The catch is style: a pack sets its own look,
   and mixing two rarely works, so it would replace the generated textures wholesale rather than sit beside them.
3. **Commissioned art**: the best result, at a cost.
CC-BY art is usable too, but it needs an attribution file kept up to date; CC0 avoids that. Whatever the source, `art.js` keeps the swap
to one place.

## Tests
- API: `/world/map` and `/world/scene` shapes; the world seed is created once and stable; `place_of` drives presence (Oriel at Brygdon on
  her day); booths, stock, prices and Pip's stall match `market`; the public versions drop and redact as `/events` does.
- `scene` and `look` details: validation against the vocabulary, the deterministic fallback, the one-time backfill.
- Front end: the map generator and the fact-to-visual table are pure functions; they get a small Playwright smoke test (load the World
  tab against a fixture API, check the canvas draws and no console errors), run locally and in CI with the browser the image already has.

## Plan
1. **The map** (it stands on its own, and is the owner's favourite): `/world/map`, the world seed, `map.js` in the World tab replacing the
   current 2D map, Pip's walking marker, heard-of places.
2. **The scene kit and the home scene**: `/world/scene`, vendored three.js, `kit.js` and `art.js`, the workshop template on live data,
   switching between map and scene.
3. **Neighbor, market and shop** templates; character `look`.
4. **Library, wild, yard, sight** templates; place `scene` details from the GM, with fallback and backfill.
5. **Weather, seasons, happenings** in scenes.
6. **The art pass** (when wanted): sprites as data, or a CC0 set, behind `art.js`.

## Decided (2026-11-08)
1. **You can go anywhere**: from the map to any place, and see its scene as it is now, even where Pip isn't.
2. **All of it is public** (map and scenes), with the usual redaction.
3. **The sheet starts small and grows outward**: it frames what Pip knows plus a margin (at least 64 minutes' walk across), so a new far place
   widens it; the land itself doesn't change, only how much of it the sheet shows.

## Step 1 as built (0.12.0)
- `GET /world/map` (`app/world_view.py`): `/map`'s places and Pip, plus the world `seed` (made once, `meta.world_seed`), per place `visits` and
  `first_visited` (from the place's facet) and `coastal` (water words in its record, or for a neighbor's home in who lives there), the
  walk's `started_at`/`ends_at`, and `now` (minutes of the day, season, weather). Public.
- `web/world/map.js`, an ES module the dashboard imports, replacing the old SVG map in the World tab (full width). Differences from the
  prototype: **the coast follows the places**: a place by the water has the sea just beyond it, away from home (so Oriel's cottage and
  Saltholm's harbour each get their shore), instead of one fixed western sea; trees take the season's colour; labels find a free side so they
  don't overlap; places Pip has only heard of are pencilled question marks; home reads "Pip's Workshop"; the ring-shaped stains are gone.
- Pan, zoom (buttons, wheel, pinch), "Find Pip" (a phone opens zoomed in on Pip), clicking a place shows what is known of it (kind, visits,
  first visit, walk, by the water). Pip's flag moves along the road during a walk, once a second, without redrawing the sheet; the sheet is
  redrawn only when what it shows changes.
- The map's lettering (IM Fell English, OFL) is served from `web/fonts/`, not from Google.
- Checked by rendering the dashboard on a copy of the live database in headless Chromium (desktop and phone), not yet by a test in CI.
