# Design: modules (the world writes its own features)

Status (2026-11-09): **designed, not built.** It replaces the roadmap item "Sandboxed code execution". The owner chose this direction on 2026-11-09:
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
{"name": "gear-clock", "kind": "thing", "api": 1, "subject": "Gear Clock",
 "hooks": ["install", "time", "action"], "reads": ["time", "self"],
 "proposes": ["state", "perceive", "schedule", "offer", "show", "consume"],
 "show": [{"type": "wall", "tags": ["inside"], "place": "subject"}],
 "consumes": {"oil": 1}}
```

## The hooks (API version 1)
Code is Python, in one source file per module, defining any of these functions. Each gets one `ctx` dict and returns a dict.

| Hook | When | Input beyond the usual |
|---|---|---|
| `install(ctx)` | once, when it goes live | none |
| `tick(ctx)` | every engine tick (only if declared; budgeted) | none |
| `time(ctx)` | at a time it asked for with `schedule` | `ctx["due"]` |
| `event(ctx)` | on an event kind it declared (`arrived`, `garden`, `stall_sale`, ...) | `ctx["event"]` (public fields only) |
| `action(ctx)` | when Pip uses one of its offers | `ctx["action"]`, `ctx["args"]` |
| `build(ctx)` | parts only: when a scene needs it (cached by parameters) | `ctx["params"]` |

Each call's input `ctx` holds: `now` (world time, local), `seed` (for a seeded `random.Random`), `state` (its own), and the views it declared in `reads`:
- `time`: hour, minute, weekday, season, daylight;
- `weather`;
- `pip`: where it is, what it's doing, whether it's asleep (never its private diary or emotions);
- `here`: the place the module lives at, who is present, what is set out there;
- `places`: public facts about real places (key, label, kind, hours, open);
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
- `consume`: items Pip's creation uses up from Pip's belongings (only those listed in `consumes`, up to their amounts).
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
{"id": "face", "sprite": {"rows": ["..kk..", "..."], "palette": {"k": "#3a2a1c"}}, "size": 0.8,
 "at": {"type": "wall", "tags": ["inside"], "near": "window"},
 "motion": {"kind": "swing", "period": 2}, "light": {"colour": "#ffc070", "strength": 0.4},
 "tip": {"title": "Gear Clock", "text": "Ten past four, and running."}}
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
2. **Parts** (modules of kind `part`): `build(ctx)` takes parameters and a seed and returns geometry in local coordinates, plus the
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
A separate container, **`pip-runner`**, in the same compose file:
- on an `internal: true` network shared only with `agent-world`, so it has no route out;
- read-only root filesystem, a small tmpfs, `pids_limit`, no capabilities, running as `nobody`;
- one small HTTP service. Each request (module source plus `ctx`) runs in a fresh subprocess with rlimits: CPU 0.5 s, memory 128 MB, wall
  time 2 s, output 64 KB;
- Python with an import allowlist (`math`, `random`, `itertools`, `functools`, `collections`, `dataclasses`, `json`, `re`, `datetime`,
  `statistics`, `string`, `heapq`, `bisect`) enforced by an import hook and checked in the AST before running. No `open`, `eval`, `exec`,
  `__import__`, or dunder access in the AST.

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
