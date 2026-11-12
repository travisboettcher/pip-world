# Design: modules (the world writes its own features)

Status (2026-11-10): designed; **step 1 (the runner, the protocol, the dry run, approval, and the clock's workings as a module) built (0.17.0)**; **step 2 (show and anchors; the wall and stall pictures as modules) built (0.18.0)**; **step 3 (Pip programs its creations; the owner is told of anything waiting) built (0.19.0)**; **step 4 (the builder, for rules) built (0.20.0)**; **step 5 (parts and layouts; the woods as a layout) built (0.21.0)**; **step 6 (the builder proposes places) built (0.22.0)**; **moving features into modules under way (0.23.0: the outdoors scene)**. It replaces the roadmap item "Sandboxed code execution". The owner chose this direction on 2026-11-09:
both Pip and the world write code, and every module needs the owner's approval at first.

## Why
Until now every feature has been written by hand in the engine: the gear clock is a `timekeeper` capability, pictures on the workshop wall are a
template slot, a market is a `PlaceKind`, and its scene is a hand-written three.js template. The owner never meant the world to be a list of
features like that. Two things should be able to grow it instead:
- **The world** (a new *builder* role beside the GM) adds what the world needs: a fair every Thursday, a tide that floods the marsh path,
  a new kind of place and how it looks.
- **Pip** makes things that really work. When it finishes a creation, it writes how that creation behaves.

The engine keeps the job only it can do: it is the **referee**. It holds the state, enforces the invariants (coins and items are conserved,
Pip can't be in two places, nothing changes without a logged reason) and gives code a small, stable set of **hooks** to write against. Code
never touches the database or the network.

## Principles
- **The engine stays generic; world features are modules.** A feature that can't be written as a module shows a missing generic hook;
  add the hook (naming no feature), never a feature-specific branch. See DESIGN-world-packs.md and CLAUDE.md.
- **Modules propose; the referee decides.** Every change a module wants is a *proposal* that the engine checks and applies, or refuses
  with a reason the author can read. That is the same pattern the GM already follows: the engine decides, the model narrates.
- **Pure functions.** A hook gets everything it may know as JSON (time, a seed, the parts of the world it declared it reads, its own state)
  and returns JSON (new state, proposals, what to show). It has no side effects and no clock or randomness of its own, so every call can be
  replayed from the log.
- **Declared, not discovered.** A module's manifest says which hooks it uses, what it reads, what it may propose, and where it shows
  things. The engine gives it exactly that, and a dry run checks it keeps to it.
- **Two authors, two sets of limits.** The builder may add rules that move items and coins, within caps. Pip's code may only make its own
  creation behave; it can't change the world's rules.
- **Nothing runs unseen.** Every module, its code, its state and every call it made can be listed, read and switched off.
- **Prove the hooks on our own features first.** The gear clock, the pictures on the wall and one existing place get rewritten as modules
  before any model writes one. If they can't be expressed cleanly, the hooks are wrong.

## Modules
A module is a row in a new `modules` table: `id, name, kind, author (world | pip), api (version), manifest (JSON), source, state (JSON),
status (proposed | dry_run | waiting | live | disabled | rejected), version, created_at, approved_at, notes`. Changes create a new version;
earlier ones are kept, so the owner can go back.

Kinds:
- **thing**: an object with behaviour, usually one of Pip's creations (`subject` = the creation). It lives where the object is.
- **rule**: world behaviour not attached to one object (a weekly fair, the tide, a shopkeeper's habits).
- **part**: something a scene is built from (a stall, a cottage, a pier, a standing stone): its geometry and its anchors (see Places and anchors).
- **place**: a place's mechanics and its layout made of parts.

A manifest:
```json
{"name": "gear-clock-workings", "kind": "thing", "api": 1, "subject": "Gear Clock",
 "hooks": ["on_install", "on_time", "on_action"], "reads": ["subject"],
 "proposes": ["schedule", "offer", "runtime", "log", "perceive", "wake", "consume"],
 "consumes": {"*": 5}, "tends": "tend"}
```

## The hooks (API version 1)
Code is Python, in one source file per module, defining any of these functions. Each gets one `ctx` dict and returns a dict (or nothing).

| Hook | When | Input beyond the usual |
|---|---|---|
| `on_install(ctx)` | once, when it goes live | none |
| `on_tick(ctx)` | every engine tick (only if declared; budgeted) | none |
| `on_time(ctx)` | at a time it asked for with `schedule` | `ctx["due"]` |
| `on_event(ctx)` | on an event kind it declared (`arrived`, `garden`, `stall_sale`, ...) | `ctx["event"]` (public fields only) |
| `on_action(ctx)` | when Pip uses one of its offers | `ctx["action"]`, `ctx["args"]` |
| `on_build(ctx)` | parts only: when a scene needs it (cached by parameters) | `ctx["params"]` |

Each call's input `ctx` holds: `now` (world time, local), `seed` (for a seeded `random.Random`), `state` (its own), `offers` (its current
ones), and the views it declared in `reads`:
- `time`: hour, minute, weekday, season, daylight;
- `weather`;
- `pip`: where it is, what it's doing, whether it's asleep (never its private diary or emotions);
- `here`: the place the module lives at, who is present, what is set out there;
- `subject`: a thing's creation: its name, quality, description, capabilities and runtime;
- `places` (later): public facts about real places (key, label, kind, hours, open);
- `items`: Pip's belongings as names and quantities (Pip's own creations only see this if they declare it);
- `facts`: what other modules have published (read-only).

What a hook may return (each key needs a matching entry in `proposes`):
- `state`: its new state (a JSON object, at most 16 KB).
- `publish`: facts for other modules to read, like `{"fair_today": true}`. Its own namespace only.
- `perceive`: one line Pip will see next tick (at most 200 characters, rate-limited per module). This is the only way a module speaks to Pip.
- `log`: an event for the diary, the public view and memory (`kind = "module"`, with the module's name).
- `schedule`: when to call `time` next (one pending time per module).
- `offer`: actions Pip can take on it: a name, a line of help, arguments, where. They appear through the existing `use` tool (`use(thing,
  action, ...)`), so Pip's tool list doesn't grow. A place module's offers appear while Pip is there.
- `consume`: items Pip's creation uses up from Pip's belongings (only those listed in `consumes`, up to their amounts; `"*"` means any
  material). If Pip doesn't have them, the whole call is refused, and on an action Pip is told what it needs.
- `runtime` (things only): its creation's fields that the engine's own readers use (`clock_set_at`, `clock_offset`, `tended_until`,
  `halted_at`, `stop_logged`, `needs_part`; `null` clears one). So the clock face, Pip's sense of time and the scene keep reading one source.
- `wake`: wake Pip now (a few times a day at most).
- `reply` (on_action only): what Pip is told it did.
- `transfer` (builder only): move items or coins between parties the engine knows (Pip, a character, a place's stock). The referee checks
  ownership and conservation. Making or destroying items needs a `source` or `sink` declared in the manifest, with a daily cap.
- `affect` (builder only): small nudges to Pip's energy, hunger or mood, capped per day, each with a reason that gets logged.
- `ask_gm`: a request for prose ("describe the fair's opening"). The answer arrives in `ctx["gm"]` on the next call. It is budgeted, and
  the result is checked like any other GM text.
- `show`: what to draw in the scene (next section).

Anything outside this list, or over a limit, is refused for that call. The module carries on, and the refusal is logged and told to its author.

## Showing things: objects and anchors
`show` returns scene objects:
```json
{"id": "face", "sprite": {"rows": ["..kk..", "..."], "palette": {"k": "#3a2a1c"}}, "size": 0.8, "frame": false,
 "at": {"type": "wall", "place": "subject", "tags": ["inside"], "near": "back-wall-by-window"},
 "motion": "sway", "tip": {"title": "Gear Clock", "text": "Ten past four, and running."}}
```
A sprite is a pixel grid (the same format as Pip's pixel drawings), a texture from the generated set by name, or a part (below). Motion is a
small fixed vocabulary (sway, bob, swing, spin, walk along an anchor, blink), and so is light. A tooltip is plain text.

The important part is `at`: it is an **anchor query**, not a position or a fixed name.

## Places and anchors
The owner doesn't want places hard-coded either, so anchors can't be a fixed list like "back wall", "shelf" or "stall table". A fixed list
only works for places we drew. Instead, **anchors are published by whatever a scene is built from**, and modules find them by what they
are, not by name.

### Three layers
1. **Geometry primitives** (fixed, in the browser's kit): box, plane, cylinder, cone, sprite, light; textures from the generated set
   (`plaster`, `planks`, `thatch`, `cobble`, ...) or a pixel grid; colour and tint. This is the only drawing code that stays hand-written.
   It is the vocabulary, not the features.
2. **Parts** (modules of kind `part`): `on_build(ctx)` takes parameters and a seed and returns geometry in local coordinates, plus the
   **anchors** that geometry has. A cottage part returns walls, roof and floor, plus anchors like "a wall, inside, 4 units wide, facing
   the camera", "a floor, inside", "a doorway". A stall returns its trestle, plus "a surface, 3 × 1, a counter". A tree returns "ground,
   under the canopy" and "a branch, hanging". The builder can write new parts. Ours get ported to parts (cutaway, stall, tree, well, fence).
3. **Layouts** (in place modules): a ground plan placing parts. Each entry has a part, parameters, a position, and a role ("the house",
   "Pip's stall"). The layout also gives the ground, the setting and the light. A place's anchors are the anchors of its parts, put into
   scene coordinates, each tagged with its part's role.

### An anchor
```json
{"id": "house.wall.back", "type": "wall", "tags": ["inside", "house"], "at": [x, y, z], "normal": [0, 0, 1],
 "extent": [4.0, 2.2], "role": "house"}
```
**Types are a small fixed set of physical relations**, because that's what code needs to place something sensibly: `wall` (vertical, faces
out), `surface` (horizontal, things stand on it: shelves, tables, counters), `floor` (inside ground), `ground` (outside ground), `hang` (a
point things hang from), `water`, `seat`, `path` (a line people walk along), `sky`. Tags are free words the part chooses (`inside`,
`counter`, `garden`, `quay`, `bench`), so new parts can describe new things without changing the engine.

### A query
`at` asks for `type`, and may add `tags` (all must match), `role` (which part), `place` (`here`, `subject`, or a place key) and `near`
(an anchor id, a role, `pip`, or another object). The engine resolves it **on the server**, the same way every time: it picks the matching
anchor closest to `near` that still has room, packs objects along it in order (oldest module first, then by object id), and hides what doesn't
fit. A query with no match shows nothing and logs why. The dry run reports it, so the author can fix it.

Because the server resolves positions from declared geometry, the browser only draws what it's given. A new place needs no new browser code.

### The places we already have
Until a hand-written template has been ported to a layout, it publishes an **anchor manifest**: a JSON file per template
(`web/world/anchors/home.json`, ...) listing its anchors in its own coordinates. The Python side reads it to resolve queries, and the template
draws whatever objects land on its anchors. This is how the first ports (the clock, the wall pictures) work before layouts exist. The
manifest is checked by a test that loads the template headless and compares.

### Places as modules
A place module has three things:
- **Mechanics:** hours, whether it's open in the dark, and its offers. These replace a `PlaceKind`. For now it may also name an existing
  kind to reuse `gather`, `browse` and the market's trading, so the economy stays in one place.
- **A layout:** parts on a ground plan.
- **A footprint and setting** for the map: size, and terrain it wants (shore, wood, hills).

The engine still owns how a place enters the world. A place module is a proposal for *what* a place is; it becomes real the way invented
places already do. A character mentions it, Pip hears of it, the map places it with the world seed, and it becomes real on Pip's first
arrival (DESIGN-invented-places.md). So the world grows from what people say, not from the builder dropping places in.

## Pip's creations as code
When a project finishes, the creation exists as it does today (a description, a quality and capabilities, so nothing waits). Pip may then
write how it behaves:
- A new tool, `program(creation, code)`, does a dry run and shows Pip the result: errors, the first calls, what it would show. Pip can
  iterate up to a few times, like `draw` with `replaces`. `program` is enabled only when `MODULES` is on.
- **Craft still matters.** The referee applies the creation's quality: a `rough` creation's hooks sometimes don't fire, or it drifts. Its
  quirks become engine-side failures layered over Pip's code. Skill keeps meaning something, and code isn't an end-run round the projects system.
- Pip's guide gets a short API page with two small worked examples. The tool description names the occasions: a creation that should do
  something on its own, or something visitors or Pip could use.
- Once approved, the module replaces the creation's built-in capability behaviour. If it is disabled, the built-in behaviour comes back.

## The builder
A new GM-side role that runs in the night pass (DESIGN-nightpass.md), **at most one proposal a night**. It gets:
- a short world bible (tone, what kind of world this is, what it isn't);
- the module catalogue (what exists, with one-line descriptions);
- recent events and happenings, open wishes, and places heard of but not real yet;
- the API page.

It proposes one module, or a revision of one of its own, with a reason. Gaps are what it should fill: something a character keeps
mentioning, a market with nothing happening on market day, a place heard of with no parts that fit it. Pace and a coherence check (a second
GM pass: "does this fit the world bible and what's already here?") keep the world from filling with noise.

## The sandbox
A separate container, **`pip-runner`** (the same image, `python -m app.runner_service`):
- **no network at all** (`network_mode: none`). The engine reaches it on a Unix socket in a volume they share (`pip-runner-socket`,
  `MODULE_RUNNER=unix:///run/pip-runner/runner.sock`). That is stronger than an internal network, and hll can't declare one anyway; in
  the homelab the runner is its own single-service hll file for that reason;
- read-only root filesystem, a small tmpfs, `pids_limit`, no capabilities, no new privileges, running as `nobody`;
- one small stdlib HTTP service. Each request (module source plus `ctx`) runs in a fresh `python -I -S` subprocess with rlimits: CPU 1 s,
  address space 512 MB, no files written, few descriptors, wall time 3 s, output 64 KB;
- Python with an import allowlist (`math`, `random`, `itertools`, `functools`, `collections`, `dataclasses`, `json`, `re`, `datetime`,
  `statistics`, `heapq`, `bisect`) enforced by an import hook and checked in the AST before running, and only safe builtins. No `open`,
  `eval`, `exec`, `getattr`, `type`, `global`, no attribute starting with `_`, no `.format` (it can reach attributes). `string` was
  left out: its `Formatter` can too.

The engine sends a call and validates what comes back against the manifest. The container is the wall; the AST and import checks make
mistakes fail early and readably, and are not the security boundary.

Budgets per module per day: calls, CPU seconds, `perceive` lines, `ask_gm` requests. A module over its budget sleeps until tomorrow. Three
failed calls in a row disable it, and its author is told why.

## Lifecycle and approval
`proposed` → **dry run** → `waiting` → (owner) → `live` or `rejected`; later `disabled` (by failures, the owner, or the author's own new version).
- **Dry run:** the module runs on a copy of the database for six simulated hours, plus each declared event once and each offer once. The
  report covers errors, refusals, budget use, what it would log and say to Pip, and anchors that didn't resolve. A scene preview (a headless
  render, like our screenshot checks) is attached when the module shows anything.
- **Approval:** an owner-only page in the dashboard, **Proposals**, never public. It shows the code, manifest, reason, dry-run report and
  preview, with Approve and Reject, and an optional note. The same is available from `pipchat modules`. A note goes back to the author:
  Pip sees it in perception as a fact ("Your program for the Gear Clock wasn't taken up: ..."); the builder sees it in its next night's input.
- While Pip's program waits, Pip is told it's "waiting to be tried". How that's framed in-world is open (see Open questions).
- Approval stays **on for both authors** until the owner turns it off per author (`MODULES_APPROVAL=world,pip` → `pip` → none).
- **Live modules** are listed on a **Modules** page (public: name, author, what it does, and the code for Pip's own; the builder's code is
  public too once live, like the gallery). Each one has a call log and a switch.

## Settings
`MODULES` (off by default in bare `Settings()`, on from env once built), `MODULES_APPROVAL` (`world,pip`), `MODULE_BUILDER_PER_NIGHT` (1),
`MODULE_RUNNER_URL`, and per-call and per-day budgets.

## Step 1 as built (0.17.0)
- `app/sandbox.py` (the checks and the limited subprocess), `app/runner_service.py` (the runner, on a socket or a port), `app/modules.py`
  (manifests, the runner clients, `context`, the referee's `plan` and `apply`, `call`, `step`, `perception`, `act`, the lifecycle and the
  dry run), tables `modules` and `module_calls` (the newest 200 calls per module).
- Kinds `thing` and `rule`; reads `time`, `weather`, `pip`, `subject`, `items`, `facts`; proposals `state`, `publish`, `perceive`, `log`,
  `schedule`, `offer`, `consume`, `runtime`, `wake` and `reply`. `show`, `transfer`, `affect`, `ask_gm` and `places` come with later steps.
- A call's proposals are checked together and applied together, or not at all. Code that fails three times in a row (not counting the
  runner being down) is switched off and its author told why. Budgets per day: 600 calls, 12 lines for Pip, 24 events, 4 wakes.
- Offers reach Pip through `use_item(item, purpose, action)` and, for the offer a thing's manifest names in `tends`, the `tend` tool. Pip
  sees a thing's actions on its line under "Things you've made"; lines from modules come under "Things in the world".
- **The clock's workings** (`app/module_library/timekeeper.py`): the world proposes it once for each creation that keeps time and needs
  tending. It notices the clock stopping (instead of the engine's built-in check, which steps aside while a module runs it), offers
  `tend` (mending it with a part first if a mishap broke it) and `set`, and changes only the creation's runtime, so the clock face, Pip's
  sense of time and the scene are unchanged. Switch it off and the built-in workings carry on.
- The owner decides in the dashboard's Work tab (Modules) or with `pipchat modules [show|approve|reject|off ID] [--note]`; the API is
  `GET /modules`, `GET /modules/{id}` (public: live and switched-off ones, with their code), `POST /modules/{id}/approve|reject|disable`
  (owner only).

## Step 2 as built (0.18.0)
- `app/anchors.py` reads the anchor manifests in `web/world/anchors/` (home, neighbor, market, shop, library, outdoors) and packs objects:
  matching anchors in published order (`near` first), objects along each in turn from its left edge with a small gap, the next anchor when
  one is full, a wall object only if it fits the wall's height. Types built so far: `wall`, `surface`, `floor`, `ground`, `hang`
  (no template publishes a `hang` yet). A frame adds two pixels round a picture; `size` is the longest side (0.2 to 1.5, default 0.6).
- `show` (at most 8 objects per module, each with its own id; pixel sprites only, checked like Pip's drawings; `motion` is `bob`, `sway`
  or `spin`) is stored on the module and replaced by each new `show`. `at.place` is `home`, `subject` (a thing's creation, at home while
  Pip has it) or a place key.
- New reads: `works` (Pip's newest 12 pixel drawings, with their grids and subjects) and `stalls` (every line on Pip's stalls).
- The scene data carries `objects`, already placed, for every live module, oldest first; the browser's `moduleObjects` (templates/parts.js, now `web/world/parts.js`)
  draws them for every template (a picture flat on a wall, standing on anything level), with tooltips and motion.
- The dry run reports where each object would go (`placed`) and what wouldn't (`unplaced`, which makes it not clean).
- Ported: **`gallery-wall`** (Pip's three newest pixel drawings, framed on the workshop's back wall; it listens for `made_work` and
  `revised_work`) and **`stall-pictures`** (on Pip's market stall, copies of a drawing framed and a creation as Pip drew it; it looks again every
  ten minutes). The world proposes both once. The hard-coded wall slots in `home.js` and the stall pictures in `market.js` and the scene data
  are gone, so until the owner approves them, no pictures hang. A creation drawn with `draw(of=...)` still wears its picture (that is its look,
  not a slot).

## Step 3 as built (0.19.0)
- **`program(creation, code, events?)`** (at home; only with `MODULES=on`). Pip writes only the code: the engine works out the manifest
  (`program_manifest`): the hooks the code defines, everything Pip's programs may read (`time`, `weather`, `pip`, `subject`, `items`) and do
  (`state`, `perceive`, `log`, `schedule`, `offer`, `show`, `consume` (up to 2 of any of Pip's materials), `runtime`, `wake`), the `events`
  Pip lists for `on_event`, and `tends: "tend"` for a thing that needs tending. The world's other powers (`publish`, `works`, `stalls`,
  rules) aren't Pip's, and Pip's things show themselves only where they are (`at.place` is `subject`).
- Pip is told the trial run in words (`trial_text`: how many calls, what went wrong, what was refused, what it would say and note, what using
  it does, what it offers, where it shows itself) and that it waits to be tried. A new version supersedes one still waiting. Six programs a
  day.
- **Craft over code** (`misfires`): a hook in a thing Pip made sometimes doesn't fire, by its quality (rough 25%, sound 8%, fine 2%,
  masterwork never), decided by a seed from the module, hook and moment, so it is the same on replay. Never on install, never in a trial
  (a trial shows the program, not its luck), never for the world's modules. Using it says "it doesn't respond this time".
- **One module runs a thing**: when Pip's program goes live, any other live module for the same creation (the world's clock workings, say)
  steps aside. The `tend` tool uses the program's `tend` offer if it has one, and the built-in tending otherwise.
- Pip sees each creation's program ("working (version 2)", "waiting to be tried", "not taken up: <note>", "switched off: <why>") and hears
  when one starts working, isn't taken up or is switched off. The guide gains a page on programs with a small example (`guide/programs.md`).
- **Telling the owner** (`notify_owner`, every engine step): a Matrix `m.notice` from Pip's account, once, when a module waits for approval
  (with its reason, the trial in a few words, a link to the dashboard if `DASHBOARD_URL` is set, and the `pipchat` command) and when one is
  switched off because its code kept failing (not when the owner did it). Pip never sees these: its sync skips its own account. They go to
  Pip's room, or `MODULES_NOTIFY_ROOM`. A failed send is tried again next step; each is logged as an `owner_notice` event.

## Step 4 as built (0.20.0)
- **`app/builder.py`**, once a night right after Pip's nightly reflection (whatever it found), when `MODULE_BUILDER=on` and the runner is up.
  It marks the night as done first, so a failure isn't retried until the next night.
- **The draft** (one GM call, `max_tokens` 4000): the world bible (the world pack's `bible.md`, or the owner's own at `WORLD_BIBLE_PATH`), the
  catalogue of modules (with the owner's notes on the world's own), the last two days of public events, Pip's open wishes, places only
  heard of, and the API page (`app/builder/api.md`, with the event kinds and every anchor by kind of place filled in). It answers
  `propose`, `revise` (one of its own, by name) or `nothing`; "most nights, nothing is a fine answer".
- **The check**: a second, separate GM call against the bible and the catalogue: does it fit, add something new, and stay quiet? If not, it
  is dropped.
- **The trial**, as for any module; if the code is refused or the trial isn't clean, the builder gets **one fix** (the problem in the
  words Pip would get), which replaces the first try. Then it waits for the owner (and the owner gets the Matrix notice).
- A rule's manifest comes from its code, as Pip's does: every read but `subject` (now including **`places`**: the real places with their
  keys, labels and kinds) and the rule proposals `state`, `publish`, `perceive`, `log`, `schedule`, `show` and `wake`.
- Each night's outcome is a `builder` event (proposed, nothing, dropped, failed, with why), shown in the dashboard feed.
- Trials now run a **whole simulated day** (30-minute steps) and note where everything shown along the way went, so a picture that only
  appears at dusk is checked too, and a module that would go over a daily budget isn't clean. Rules and Pip's programs can read
  `pip.at_home`.
- Tried against a copy of the live world with the live model: unprompted, it chose nothing ("I don't see a gap that fits"); asked to
  propose, it wrote a seasonal dusk lamp that is noticed only when Pip is home and awake, once a day, clean on trial. An early version
  asked for an anchor that doesn't exist and named Pip's home wrongly, which is why the API page now lists the real anchors and keys.

## Step 5 as built (0.21.0)
- **The shape vocabulary** (`app/geometry.py`): `box` (with one `material`, or `faces` {top, side} for a block of ground), `plane`,
  `cylinder` (radius at the bottom, `top` at the top), `cone`, `sphere`, `ico`, `dodeca`, `gable` (a triangle: width and height),
  `sprite` (a pixel grid, or one of the browser's small sprites: reed, flower, curlew, spark, coin), and `light` (a `lamp` light comes up at
  dusk). Each has `at`, `rot` in degrees (heading first: Euler order YXZ, so turning a part only adds to its heading), `scale`, `sway`,
  `shadow` and `tip` (`$label` and `$description` stand for the place's). Materials are named after the generated textures (grass,
  planks, thatch, stone, leaves, stripes...: `TEXTURES`), with `repeat`, `color` (planks and leaves take it; stripes take `color` and
  `color2`), `metal`, `rough`, `emissive`, `lamp`, `double` and `opacity`. Seasonal textures (grass, cliff, leaves) follow the season in the
  browser. Every refusal names the shape and what to fix.
- **Two module kinds**, the world's only: a **part** (`on_build` gets `params` over its manifest's defaults, `season` and `seed`, and
  returns up to 400 shapes and 24 anchors) and a **place** (`manifest.place` names the place it lays out; `on_build` returns
  `{"parts": [{part, params, at, turn, role}], "shapes", "anchors"}`, up to 80 parts). Their trial is a build: a part with its defaults, a
  place with the parts it names (live, or still waiting, so a layout and its parts can be proposed together).
- **Building** (`app/layouts.py`, every engine step): a live place is built when it has no layout, when the season turns, or when a part
  it uses has a new live version; each distinct part and params is run once, moved and turned into place (`geometry.place`: anchors get
  the role as an id prefix and a tag), checked (3000 shapes at most, anchor ids unique) and kept on the module. A failed build keeps the last
  good one, is logged (`layout_failed`) and is tried again after an hour. One live place module per place: a new one replaces the old.
- **Drawing**: the scene data carries `layout` (its shapes and anchors) for a laid-out place, and the browser draws it with one renderer,
  `web/world/layout.js`, instead of the place's template: shapes, swaying leaves, lamps, tooltips; Pip on the anchor tagged `pip` (searching
  across it while gathering); people beside it (`people`); finds on `finds`. Module objects go on the layout's anchors.
- **The library**: parts `round-tree`, `pine-tree`, `well`, `stall` (two awning colours, a counter) and `cutaway` (width, depth, height,
  walls, roof, door; its inner wall faces are planes inside the walls; back wall, floor and front are anchors), and the place
  `woods-layout`: the woods' land, 11 round trees and 18 pines from the parts, and anchors for Pip, finds and the clearing. The world
  proposes them all once; the woods keep their hand-written scene until they're approved. Checked against the hand-written woods in
  renders (the same land and trees; only the scatter differs), and a probe yard with a cutaway, a well and a turned stall.

## Step 6 as built (0.22.0)
- **A new place as a module** (`app/module_places.py`): a place module with `new` in its manifest describes a place that doesn't exist
  yet: `label` (its name as people say it), `kind` (one of the existing place kinds, so gathering, browsing and trading work as for any
  place), `description`, `distance` (near or far), `items` (up to six things to find or buy there), `setting` (wood, heath, shore, ...)
  and, for a shop or market, `opens` and `closes`. Its key is worked out from the label as for any mentioned place (the proper-noun core:
  "Hollis's seed shop" is "Hollis"); a name that's already a place is refused, except a new version's own.
- **How it enters the world**: nothing happens until the owner approves it. Then one of the characters Pip knows (a neighbor or a
  resident, the same one for the same place) mentions it: it is recorded as heard-of, with that mention, a walk time from its distance, and
  its setting as its scene details, and Pip hears "Oriel Vantosh told you about Hollis: ...". The map shows it like any heard-of place and
  `go_to` works. On Pip's first arrival it becomes real exactly as the module describes (its kind kept as approved, its items as what can be
  had there), with no GM design. Its layout is its `on_build`, built and drawn as in step 5.
- **The builder may propose a place** (`module: "place"` in its draft, with the fields above and layout code), rarely: the bible says a
  place is a big addition, and the API page lists the place kinds, settings, textures, the live parts with their params, how the ground and
  anchors work (Pip, finds, people, and a `counter` for a shop or market), and that until someone tells Pip, nobody knows it's there. The
  check sees the place's description. The one fix may change the place's fields as well as its code.
- **The layout renderer** sets a shop's or market's goods out on the surface tagged `counter`, with its keeper standing behind.
- Tried with the live model on a copy of the live world, asked for a place: it proposed a ruined chapel on the heath, then a mill on the
  river (both turned down on details that are now accepted or explained: an hour of 24, anchors without a size, a stream hidden under the
  ground), then a seed shop up from the harbour: clean on trial, laid out as a thatched shop on a cobbled lane, mentioned by Oriel on
  approval. Hand-written templates stay for every place without a layout; retiring them one by one is now possible, not done (done in 0.24.0).

## Moving features into modules (from 0.23.0)
The owner's direction (2026-11-10): remove what can now be a module; where something can't be expressed, that is a missing hook or
ability, to consider.

**Two changes that make removal safe:**
- **Shipped modules** (`author: "library"`, the files in `app/module_library/`) are the engine's own code, reviewed like it: they go live
  without approval when their trial is clean, and run in a local sandbox when there's no runner, so a deployment without `pip-runner`
  (or with `MODULES=off`, which now governs only the world's and Pip's modules) still has them. `MODULE_LIBRARY` (on from the environment,
  off in bare test settings) switches them off.
- **Kind-level layouts**: a place module may cover `kinds` instead of one `place`. It is built for every real place of those kinds without
  a layout of its own, and its `on_build` is told the place's details (`ctx["details"]`: key, label, kind, setting, walls, roof, palette,
  props, coastal), so one module can stand in for a hand-written template. It is rebuilt when those details change. A place's own layout
  still comes first.

**Abilities added for the first removal** (the outdoors template): shapes can `animate` (`flow`: the texture drifts; `tide`: rises and
falls with the tide clock), a `hitbox` is an invisible box carrying a tip, and Pip sits on an anchor tagged `seat` when its pose is sitting.

**Done**: the gallery wall and stall pictures (step 2); the clock's workings (step 1, shipped live for every timekeeper); the outdoors
scene: `web/world/templates/outdoors.js` and its anchor manifest are gone, replaced by the `outdoors` kind layout (wild places, yards,
sights) and parts `scrap-heap`, `shed`, `bench`, `standing-stones`, `lighthouse`; `woods-layout` is no longer shipped (the kind layout
covers the woods; where it's already live it still takes precedence). Checked against the hand-written junkyard in renders.

**Live elements, and the last templates retired (0.24.0).** Every scene is now a layout. What changes with the world is drawn by the
renderer on anchors a layout tags for it, so the layout stays plain geometry and the facts stay the engine's:
- **Live elements** (`web/world/layout.js`): `pip`, `seat`, `bed`, `workbench`, `reading`, `garden-path`, `browse`, `visitor` and
  `pip-stall` are where Pip stands, sits, sleeps, works (with sparks), reads (with a book), gardens, browses and keeps its stall, by its
  pose; `plot` (in order) is a garden plot with its crop growing, drawn only for plots the garden has; `clock`, `shelf` and `walkers` hold
  Pip's creations; `resident`, `resident-evening` and `resident-walk` are where whoever lives there is by the time of day (out on the flats
  at a morning low tide, away on market day); `people`, `crowd` (shoppers walking round while it's open), `finds`, `wares` (a neighbor's
  goods), `counter` and `stock` (a shop's goods and keeper), `booth` (a market's booths in turn, each with a keeper). Tips can say
  `$resident`, `$wares`, `$stock`, `$stall`, `$hours`, `$note`, `$belongings`, `$project` as well as `$label` and `$description`.
- **Conditional shapes**: `when` (a list, all must hold) of `open`, `shut`, `day`, `night`, `high-tide`, `low-tide`, `winter`,
  `not-winter`, `resident-home`, `resident-away`, `pip-stall`, `no-pip-stall` and `booth-1`...`booth-8` (a booth stands at that stall
  today). A part entry in a layout can carry `when` too, for all of its shapes (a market's stall shows only when it has a booth).
- **Motion and light**: `animate` adds `spin` (a lighthouse's beam) and `wander` (a sprite pacing back and forth: curlews); a sprite can
  show one `frame`; a material's `lamp` can be a strength (0-2), and `beam` is a faint additive light that shows only in the dark. A
  `torus` shape (coils of rope); sprites `note` and `carrots`; textures `chart` and `book`. A layout can set its own `camera`.
- **Reserved anchors**: an anchor tagged `reserved` is the renderer's own (Pip's seat, the plots, the clock spots, a shop's counter):
  module objects never go there, and the builder isn't told about it. A home layout's own anchors come first, so pictures still hang where
  they did.
- **Shipped layouts** `home`, `neighbor`, `market`, `shop`, `library` (kind layouts; their details pick a coast or a meadow, a harbour,
  beehives, a lighthouse...), ported from the templates and checked against them in renders of every view (the workshop at work and
  asleep, Oriel's cottage, Brygdon market, Saltholm shop, the library while reading). The `stall` part rolls its awning up when shut.
- **Shipped modules are upgraded**: when a release changes a shipped module that is live, its new version is proposed (and goes live on a
  clean trial); one the owner disabled or rejected is left alone. The first parts, proposed before shipped modules had their own author,
  count as shipped. A place module replaces another only if it covers the same place, or every kind the other laid out.
- Gone: `web/world/templates/` (home, neighbor, market, shop, library), `web/world/anchors/*.json` and the template fallbacks in
  `anchors.py` and the builder's anchor list. A place with no layout built yet shows a note instead of a scene, and nothing modules show
  is placed there.

**Creations' workings as modules (0.25.0).** What a creation does on its own now runs as code:
- **Reads**: `garden` (the plots: crop, state, minutes to ripe), `visitors` (`{waiting}`: messages waiting for Pip), and `pip` now
  says `hunger`, `energy` and `mood`. Pip's programs may read the garden and visitors too; the builder's rules read everything but a subject.
- **Effects**, each capped per day and checked by the referee: `affect` (`{energy, mood}`: up to 0.1 energy either way, a word or two
  of mood; 6 a day), `garden` (`{hurry}`: cut the growing time left by 1-20%; 24 a day), `find` (`{item, qty}`: one or two of something
  the manifest's `finds` names, added to Pip's belongings as found by the thing; 4 a day). Pip's programs can't propose them: Pip can't
  grant itself energy or crops. The builder's rules don't propose them yet (that comes with happenings).
- **The engine's own modules have room for a busy day**: a shipped module may make 3000 calls, 100 lines to Pip and to the record, and
  wake Pip 12 times a day (the world's and Pip's keep the old limits), since a creation's workings tick every minute.
- **`workings`** (replacing `timekeeper`) is the shipped module for every creation that runs down, says things, senses or helps: upkeep
  and stopping, the clock and setting it, periodic lines, the sensor (crop ripe, a visitor, dawn, dusk, hungry, tired: an alert and a
  wake when it comes on), and the helper (find, hurry the crops, comfort). Its manifest has only the hooks its creation needs (`on_tick`
  only for one that ticks) and its creation's `finds`. When it is live the engine's built-in tick leaves that creation alone entirely;
  when it isn't (switched off, failing, no library), the built-in tick runs as before. A clock's workings that were already live are
  upgraded to it. Companions (`companion`), news (`provides`) and lasting room in the world (`world`) stay in the engine: the first two
  need the model, the last happens once.

**Customers at Pip's stall as a module (0.26.0).**
- **Reads**: each `stalls` line now says its `ask`, the going price here (`fair`), how many sold today (`sold_today`) and whether it is
  `selling` (Pip is there, awake and not walking, and the market is open); `pip` says whether Pip is `walking`.
- **`sell`** (`[{place, item, qty}]`, up to 3 lines a call): customers buy from Pip's stall. The referee allows only lines on the stall,
  only where Pip is selling right now, at most what is there and what the market still takes today (8 of a thing), and always at Pip's
  own ask: a module decides how many people stop, never the price. The sale is paid, logged and nudges the local price exactly as before
  (`market.sell_units`). Pip's programs can't sell.
- **`stall-customers`** (shipped rule, `on_tick`): about two customers an hour at the going price, more when cheaper, none when far dearer,
  credited at most an hour at a time; the first look only starts the clock. While it is live the engine's own stall customers stay
  quiet. Fixed alongside: a shipped module's larger call allowance (0.25.0) was not applied when calling it.

**Voices: things Pip can talk to, owned by modules (0.27.0).** The owner's question: if companions didn't exist, could the builder add
something Pip converses with, without the engine knowing about it? Now it can. Four general primitives, none about companions:
- **`voices`**: a module declares up to 4 names it speaks as, each somewhere (`"home"`, `"subject"`: where its creation is, or a place's
  key), with a line of `about`. A name already in the world (a character, another module's voice) is refused; a creation's own old
  companion character steps aside for its module. `say(to=...)` finds module voices before characters, but only where Pip is ("can't
  hear you from here" otherwise), and Pip's prompt lists who is here to talk to.
- **`on_message`**: what Pip said to one of its voices, delivered on the next engine step (`ctx["message"] = {to, text, from, ts}`). A
  module hears only what was said to its own voices, and keeps the conversation in its own state. A voice whose module has no
  `on_message` hears nothing ("said it to the Statue").
- **`ask` / `on_answer`**: a module writes its own prompt (up to 2000 characters, at most 600 back, a `purpose` to tell answers apart);
  the engine asks the model (`gm.words`: plain words, trimmed at a word), and hands the words to `on_answer` (`""` if none came). At most
  3 wait at once; 12 a day for the world's modules, 150 for the engine's. A trial doesn't call the model: it stands in "(the model's
  words)" and the report lists every prompt it would send (`asked`) and every line it would say (`spoken`), so the owner sees them before
  approving.
- **`speak`**: a line as one of its own voices, logged as the same event every character's line is (`companion`: perception, memory,
  conversation threads, firsts and the public feed treat it alike); `to_pip` wakes Pip. 24 a day for the world's, 150 for the engine's.
The builder's rules may use all four. Pip's programs can't (yet).

Built on them, in the shipped `workings`:
- **Companions**: a creation with a mind of its own is a voice where it is (so Pip talks to it at home, not from the market), chatters on
  its own every so often (about its `chatter_minutes`, never waking Pip), and answers what Pip says (at most 4 answers an hour, waking
  Pip), with the model given who it is, what it is, how Pip is, and the last few lines between them, as before. A stopped one says
  nothing; one sold or given away does nothing at all (the workings now go quiet for any creation that's gone, which in 0.25.0 would
  have failed). While it is live the engine's own companion code leaves that creation alone (removed entirely in 0.29.0).
- **News**: a receiver offers `listen`; up to 3 bulletins a day come through (the model writes them from the day, the season and the
  weather, about Pip's own small world only), told to Pip when they arrive. Using the receiver without `listen` no longer asks for a
  bulletin while its workings are live.

**Happenings as a module (0.28.0).** The owner's rule: the engine keeps the checks where they are generic and broadly applicable.
- **`happen`** (any author but Pip; 2 a day for the world's modules, 8 for the engine's): `{category, tone, severity, effects?, about?,
  names?, fallback?, night?}`. A module says *what kind* of thing changes, as intents: `coins`, `item` (a find from this world, or a
  gift), `food_loss`, `crop` (time, yield, or ruin), `energy`, `hunger`, `price`, `stop` (a creation that needs tending), `news` (a
  neighbor), `memory` (an old thought of Pip's comes back: the diary stays with the engine). The engine makes them real by the severity
  with the same tables and caps its own happenings use, checks every target, and that the tone fits: a good turn only gives, a bad one
  only takes, a neutral one changes nothing. The referee checks only the shape and the day's room (`happenings.room_for`: switched on,
  nothing waiting to be taken in, the day's limit, Pip awake and not walking); the world is checked when it is written, and a happening
  that no longer fits is dropped with the reason logged (`happening_dropped`), so a module's state is never lost to a refusal. It is then
  written by the model with the same checks (a module's `about` is given to the writer to keep to; its `names` must be real), falls back
  to the module's own `fallback` or a plain line by tone, is recorded, applied and taken in by Pip as any happening is; the event says
  `by` which module.
- **Reads**: `people` (who lives here: names and kinds, nothing private), `creations` (running, tended), `happenings` (the recent record,
  today's count, `room`, whether an old thought could come back), and `pip.coins`.
- **`params`** for any module (plain values or short lists): settings it is given in `ctx["params"]`. A shipped module's params can come
  from the engine's settings: the happenings rule gets `HAPPENINGS_CHANCE`, `HAPPENINGS_SLOT_HOURS`, `HAPPENINGS_SEVERITY`,
  `HAPPENINGS_SEASONS`, `WAKE_HOUR` and `BEDTIME_HOUR`, and a change to them (or to a shipped manifest) proposes its new version.
- **`happenings`** (shipped rule, `on_tick`): the dice as before: a roll per slot of the awake day in its first half hour (not while Pip is
  walking or something waits), the slots slept through rolled on waking (a hit happened in the night: no market or neighbor news), a
  category the world allows and the season favours that hasn't come up in twelve hours, a tone (bad much less likely after two bad ones),
  a size, and what changes. While it is live the engine only resolves happenings (Pip's reading of them) and no longer rolls. Not kept:
  the dice record for replaying a roll (`happening_rolls`), which the engine's own rolling still writes. Trials list what would happen.
- The builder's rules may propose happenings too.

**The engine's fallbacks removed: creations and companions (0.29.0).** A creation's capabilities now run only in its `workings`
module: the engine's own tick (periodic lines, sensors, helpers, the stop notice), its `tend`, and its companion characters (a chatter
timer and answers for every talking creation) are gone, as are bulletins asked for while using a receiver. What stays generic:
- **Using a thing** (`use_item` without an action) still asks the GM what happens, with a mood and energy if they follow; the GM is now
  shown the thing's own actions (its workings' offers, `{name, help}`) and says which one Pip did, if any (`action`), and the engine carries
  that out through the module (`modules.act`): winding a clock by hand tends it, as before, without the engine knowing what tending is.
- **`tend`** is the action the workings name (`tends`); a thing with no live workings "doesn't need tending".
- **A thing that runs down must offer tending**: a trial notes it and approval refuses it (`modules.untended`), so neither the world nor
  Pip's own program can leave a clock that nobody could ever wind again.
- `say(to=...)` no longer answers for a creation's old character: a thing talks only through a voice.
- The module library must be on (`MODULE_LIBRARY`, on from the environment) for creations to do anything at all; bare test settings
  leave it off, and the tests that need workings set it.
**The rest removed: stall customers and happenings' dice (0.30.0).** The engine no longer has customers (`stall_step`, `stall_tick`,
the Poisson draw) or happenings' dice (slots, rolls, categories, their planners, season weights, tone weights, cooldowns, the night roll,
`build`, `create`) or the categories' fallback words: all of that lives only in the shipped `stall-customers` and `happenings` rules, which
are now tested directly too (their Python is imported and called with a context like the engine's: `test_customers.py`,
`test_happenings_rule.py`). What the engine keeps is what any world needs: `sell` and its checks, `market.sell_units`, where Pip is
selling (`selling_at`), and a little stall housekeeping (`market.prune`: a creation sold or given away elsewhere comes off the stall);
for happenings, `happen` and its intents, the amounts and caps, the words and their checks, `record`, how Pip takes a happening in, and
`step`, which now only lands the meaning of what Pip has been shown. Gone with the dice: the replay of a roll (`/happenings/{id}/replay`,
`pipchat happenings --replay`); a module's calls are recorded, seeded and replayable like any other's.

**What a feature needs (0.35.0, world packs phase 4; DESIGN-world-packs.md, "Phase 4 in detail").** For a feature to be a module, the
engine knowing nothing of it, a pack's or the engine's own modules (not the world's builder, and not Pip's programs) may also use:
- **`tools`** in the manifest: `[{name, help, params, where}]`, `params` a small JSON schema (`{type: object, properties, required}`, each
  argument a string, integer, number or boolean, with `description` and `enum`), `where` one of `anywhere`, `home` or a place key. They
  are offered with the engine's own tools where they apply (and not at a closed place), their arguments checked first (a number given
  as a string is taken), and used through `on_action` with `ctx["tool"]` and `ctx["args"]`; its `reply` is the result. Each use is a
  `tool` event like the engine's own (public, with its result). A name may not be an engine tool's. A tool's `first` ("planted
  something") makes its first use a first and each use that changed something a diary moment; one that changed nothing is a no-op.
- **`store`**: `{collection: {key: value or null}}`, merged on each call, read back as `ctx["store"]`; kept by the module's name (a new
  version keeps it), at most 8 collections of 200 keys and 64 KB.
- **`take`** and **`give`**, with `belongings` in the manifest (`{takes: [kinds], gives: [kinds], most}`): `take` `[{item, qty}]` from what
  the agent has, `give` `[{item, qty, kind, description?, attrs?}]` (plain attributes; `restores` names only the world's stats). The `items`
  read now carries each item's `attrs`.
- **`status`**: `{title, lines, ready?, next_at?}`, replaced on each call (`{}` clears it): a section of the agent's prompt every time, on
  `/status`, `/standing` and the dashboard. `{in:<time>}` in a line is worded by the engine as it is shown ("45 min"). `ready` (something waits for the agent now) and `next_at` (when something next will) feed the free-time line.
- **`log`** may be `{text, kind, feel?}`: the event (`module`) carries the kind as `moment`; the pack's `content.json` `module_firsts`
  (`{"<module>:<kind>": "had a crop ripen"}`) names a first of it, and `feel` (`{"joy": 3}`, at most 5 either way) moves the agent's
  emotions.
- **requests**: a module lists what it `answers` (`{word: what it does}`) and has `on_request` (`ctx["request"]` = `{what, args, from,
  apply, tone?, severity?}`; it may `reply`, or `refuse` with a reason). Another module proposes `request` (`{module, what, args?}`), heard on the target's next step.
  A happening's effect may be `{"kind": "request", "module", "what", "args"?}`: the module is asked to say what it would change (`apply`
  false; its reply is the effect's line, so it must give one) before the words are written, and to make the change after. A world effect's
  `does` may be `request:<module>:<what>` (the reply is its note). The module asked is the authority on its own state, sized by the
  severity it is told.
- **Places (0.36.0, phase 5a)**: the `here` read (the place the agent is at: its key, label, kind, whether it's open, its find table,
  verbs, stock, and the kind's session lengths, capacity, refill, shop hours, trading; none while walking) and the `abilities` read
  (levels); `practice` (`{ability: minutes}`, 240 a call), `deplete` (`{amount, place?}`), `doing` (`{activity, description}`), `give`'s
  `at` (where it was found, for `where_to`), and `owe` (`{place, items}`: on account at a place that trades, until the market is a
  module). A tool's `where` may be `offered`: wherever a place's verbs list the tool, worded the place's own way. `log` may carry `items`
  (what came of the moment: each a first, "found X") and `tool` (the agent's sense of what its tools are good for reads it); a moment is
  shown among recent events and can be recalled. The agent read carries its `name`.
- The garden is the first feature built on them: `module_library/garden.py`; gathering the second: `module_library/gathering.py`. The `garden` read and proposal are gone (read its `facts`;
  ask it to `hurry`), and so is the `crop` happening intent (ask it: `request` to `crop`).
- **`session`** (from `on_action`; it needs `on_time` too): `{minutes (1 to 240), label, working?}`. The agent is busy with `label` until it
  ends, then `on_time` runs with `ctx["session"]` = `{label, interrupted, minutes}`; resting ends it early (`interrupted` true); a
  `working` one tires like work.

**What's left, and what it needs** (each gap is a candidate hook or ability):
| Feature | Blocked by |
|---|---|
| Neighbors' letters, weather, sleep, reflection, memory | engine systems by design (the agent's own life, or outside data): not candidates |

## Steps
1. **The runner and the protocol.** `pip-runner`, the `modules` table, manifests, a dry run, the Proposals page and the `pipchat`
   command. Port **the gear clock** to a `thing` module (written by us, authored as `world`), covering `state`, `schedule`, `perceive`,
   `offer` and `consume`. Its built-in `timekeeper` capability stays as the fallback.
2. **Show and anchors.** Anchor manifests for the existing templates, `show`, server-side anchor resolution, and drawing objects in the
   templates. Port **the wall pictures** (a `rule` hanging Pip's newest pixel drawings on `wall`, `inside`, at `subject` = home) and **stall
   pictures**, then remove the hard-coded slots from `home.js` and `market.js`.
3. **Pip programs its creations.** `program`, the dry-run loop, quality layered over code, the guide page, and approval.
4. **The builder, for rules.** The night-pass role, the world bible, pace and the coherence check, with approval.
5. **Parts and layouts.** A geometry vocabulary, `build` for parts, and a generic layout renderer in the browser. Port the stall, cutaway,
   tree and well to parts, and port **one existing place (the woods)** to a layout, checked against the hand-written scene in screenshots.
6. **The builder proposes places.** Place modules (mechanics, layout, footprint), entering the world through the existing discovery path.
   The hand-written templates retire one by one as layouts replace them.

Each step ships on its own (`MODULES` gates it), with tests, mutation testing and a release like the others.

## Measures
How many modules each author proposes, how many get approved, and why rejections happen. How often live modules fail or hit budgets. How often
Pip uses offers. Whether Pip writes programs for its creations unprompted. Whether the world's new rules show up in Pip's diary as things it noticed.

## Risks
- **Noise:** a builder adding things every night makes a world with no character. One a night at most, a coherence pass, the owner's
  approval, and a world bible.
- **Escape:** visitors' words reach Pip, and Pip writes code. The container, its network and the limits are the boundary. The referee
  limits what even working code can change.
- **Hard to follow:** emergent behaviour is hard to debug. Pure hooks with logged inputs make every call replayable, and the Modules page
  shows each one's history.
- **Rotting API:** modules outlive the code they were written against. `api` is versioned, old versions stay supported, and a change runs
  every live module's dry run again.
- **Cost:** model-written code means more tokens at night and during `program`. Budgets, and only one builder proposal a night.

## Open questions
- **How Pip experiences approval.** Is "waiting to be tried" an in-world thing (a character who inspects inventions?), or a plain fact?
- **Who else runs modules** once there are more agents (roadmap item). The hooks take an `agent` where they now say `pip`, so this stays possible.
- **Owner edits.** Should the owner be able to edit a proposed module's code before approving it, or only send notes?
- **Shared parts.** Can Pip write parts (for how its creations look), or only the builder? Leaning towards both, with Pip's parts only
  usable by its own things.
