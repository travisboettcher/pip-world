# Design: happenings (small, unscripted events from the world)

Status (2026-11-03): design, nothing built. Idea from the owner: things should sometimes happen *to* Pip, written by the model so they are not scripted,
but small, drawn from a fixed list of categories (so the model cannot, say, kill Pip), with a deterministic roll for whether the outcome is good, bad or
neutral. The happening is seen through the emotion system: it is written to move a specific emotion (say sadness), and Pip keeps some say in how much it
lands. Replaces the ROADMAP's "LLM-free surprises" item: the randomness stays deterministic, the telling is the model's.

## Why
Pip's days are all its own doing: it plants, rests, visits Oriel, sells tomatoes. Nothing arrives from outside except a visitor or a letter, so the diary
fills with Pip's own intentions and the world feels inert. Happenings give the world a voice: a storm over the beans, a mouse in the pantry, a
half-remembered thing on a shelf. They also give the engine an organic way to add pressure we have been wanting (a glut that can spoil, prices that gossip,
a creation that needs tending) without a script for each case.

## Principles
- **The engine decides what can happen and what it changes; the model decides how it reads.** The same referee pattern as projects and creations. The model
  never emits a state change. It picks nothing mechanical: category, tone, size and every effect are chosen and capped in code before it is asked to write.
- **A fixed menu, with hard caps.** A category is a row in a table: what must be true in the world for it to apply, the effects it may have and their
  limits, which emotions it may touch. Nothing outside the menu can happen, and no effect can remove something essential (the last tool, a project, a note, a
  creation) or hurt Pip (no injury, illness or death categories exist).
- **Deterministic dice.** Whether it happens, which category, whether it is good, bad or neutral, and how big are rolls from a seeded RNG whose seed is stored with
  the happening, so any one can be replayed and tests can pin them.
- **Small by default.** A happening is a pebble. About one or two a day; most are neutral or mildly good or bad; the big end is rare and still capped.
- **Grounded in the world.** The model is handed facts from the world (the weather, the plot that is ripening, a creation by name, a neighbor, a place Pip
  has been) and may use only those; it cannot invent people, places or objects that the engine did not offer.
- **Truth is in the effects line.** Every happening ends with what the engine actually changed ("(You find 2 hazelnuts.)", "(Plot 2 will ripen about an hour
  later.)"), appended by the engine, as with neighbor hand-overs. If the prose says more than that, the prose is flavour. Pip's guide says so.
- **Pip keeps agency over its feelings, not over the weather.** It cannot refuse a rain shower, but it can take it in stride (see "Through the emotions").

## The pipeline
1. **Trigger (code).** The monitor (every 30 s) rolls a small chance, shaped so that a day has `HAPPENINGS_PER_DAY` on average (default 2) with a minimum gap
   (`HAPPENINGS_MIN_GAP_HOURS`, default 3), none while Pip sleeps or in the first hour after waking, none while a happening is pending delivery, and a bit
   more likely when Pip's own day has been quiet (few tool calls, long waits), so happenings fill silence rather than interrupt busy work.
2. **Category (code).** Weighted choice among categories whose `eligible(world)` is true and that are off cooldown (a category does not repeat within
   `COOLDOWN` hours; the same *effect kind* is not used twice in a row).
3. **Tone (code).** Good, bad or neutral from base weights (35 / 25 / 40), then adjusted: after two bad ones in a row bad is x0.3; if hunger is high, energy
   is low or valence is already deep negative, resource-costing bad outcomes are removed and bad becomes "bad but only a feeling"; the first week runs gentler.
   Each category lists which tones it supports (a kindness is only good; a mishap only bad or neutral).
4. **Size (code).** Small, or rarely medium (about one in eight). The size scales the effect numbers inside their caps.
5. **Effects (code).** The category's effect for this tone and size, with parameters chosen from world facts (which plot, which stack, how many).
6. **Author (one model call, the GM).** Given the category, tone, size, the chosen effects in plain words, a small packet of world facts, the emotion lens
   (below) and the last few happenings (so it does not repeat itself), it returns `{title, text, felt_as}`: two or three sentences in the second person,
   a short title, and which emotion it leans toward from the allowed set. A validator rejects text that names a person, place or object not in the packet,
   mentions a number or item the effects do not, runs long, or uses a word on a short deny list; one retry, then the deterministic template for that
   category is used (so the world still works with no model). Cost: one cheap call, about 1.5k tokens, a couple of times a day.
7. **Apply and tell (code).** Effects are applied, the emotion lens is applied (below), the row is saved, a `happening` event is logged and Pip is woken if it
   is awake (not urgent: a visitor still comes first). Pip sees it in its prompt as "Something happened: ..." with the effects line, until it has acted on a tick
   after it.

## Categories (v1)
Each is a table row: `needs` (world facts), `tones`, `effects` (per tone, with caps), `lens` (emotions it may touch).

| Category | Needs | Good | Bad | Neutral | Effects and caps |
|---|---|---|---|---|---|
| `garden` | a crop growing | a mild spell: a plot ripens sooner | a bad turn: a plot ripens later; or one unit of yield lost from one plot | a change in the air, nothing changes | growth +-15% of the time left on one plot; yield -1 on one plot, never below 1 |
| `creature` | home | a visitor leaves a feather or seeds | nibbles at the pantry | watches from the fence | +1-2 of a seed or material; -1-3 of one food stack of 10 or more, never below 5 |
| `pantry` | a food stack of 20 or more | none | some of it turns: damp, mice, a split crate | a check of the shelves | -10% of that stack, min 1, max 6. Spoilage as a happening, not a clock |
| `found` | anywhere outdoors or home | a small find | a dud (a rusty nail, nothing gained) | an odd thing noticed | +1-3 of a common item from the known-items table; never a tool |
| `mishap` | a creation or a tool | none | a creation needs tending now (existing "stopped" state) | a squeak, nothing wrong | creation stops until tended; energy -0.05 |
| `neighbor` | a known neighbor | word of something good for them | a small worry for them | gossip | neighbor `life_update`; may mention a place through the existing mention path; no items |
| `memory` | 7+ old notes or a first | a fond thing surfaces | a wistful one | a puzzling one | emotion only: cites one real diary entry or first the engine picked |
| `body` | awake | "you slept well"-style ease | a stiff back, a headache-free ache | a yawn | energy and hunger +-0.05 |
| `market` | a shop or market Pip knows | a rumour of a good price | a rumour of a glut | a rumour | one item's local price +-8% at one booth, through the existing nudge |
| `kindness` | a known neighbor or the owner | an anonymous gift | none | none | +1 small item, or +3 coins at most |
| `atmosphere` | none | none | none | a sound, a light, a smell | emotion only, surprise or anticipation at most +4 |

Things that are never a category: anything that removes a creation, project, note, tool or place; any loss of coins beyond a few; injury, illness, death,
danger to others; real people other than the owner and the neighbors the engine knows; anything that makes a promise (a happening cannot offer Pip something
later: only what is in the effects line is real).

## Through the emotions
Each happening carries a **lens**: the emotion or emotions it is meant to move and by how much, from the existing eight and the existing `nudge`.
- **Defaults by tone and size** (code): a small bad one moves one of sadness, fear, anger or disgust by 4-6; a medium by 8-12. A good one moves joy, trust or
  anticipation by 3-5 / 6-9. A neutral one moves surprise or anticipation by 2-4, or nothing.
- **The model chooses the colour, not the amount.** `felt_as` must be one of the emotions the category and tone allow (a mouse in the pantry may read as
  anger or sadness, not joy); the engine picks the amount. A bad storm that the model frames as fear is fear 5; framed as sadness it is sadness 5.
- **Half now, half pending.** On the happening, half of the lens is applied immediately (the first jolt). The other half is held as *pending* for 30 minutes.
- **Pip's say.** If Pip takes it in stride in that window, with the existing `settle` (its description gains "or take something that just happened in stride")
  on the lens emotion, the pending half is cancelled (and the usual settle effect still applies, within its daily limit). If it does not, the pending half sinks
  in when the window ends. So Pip can choose to let a mouse ruin its afternoon or to shrug, and either is a recorded choice the reflection can notice. Good
  happenings are simply felt in full (nothing is lost by savouring), and a future `feel` self-report could weigh in here.
- Everything goes through `emotions.nudge` with a cause ("happening #12: the mouse"), so the emotion log shows why Pip is sad, and the reflection and turning-point
  detector already read it.

## What Pip sees and remembers
- A prompt block while a happening is fresh: the text, the effects line, and what is pending ("this may weigh on you for a while").
- A `happening` event in the feed and the log (public view: the text and category, effects line included, names redacted as usual), importance scaled by size,
  so it is offered as a diary moment and reaches the nightly reflection and `recall`.
- `firsts`: the first time a category occurs is a first ("the first time a mouse got into your pantry").
- The model call is told Pip's recent happenings but not Pip's feelings or persona text beyond the engine's facts, so it narrates the world, not Pip's mind.

## Data and API
- Table `happenings(id, ts, category, tone, size, seed, context JSON, effects JSON, lens JSON, pending JSON, text, title, status, author)` where `author` is `gm`
  or `template`, and `status` is `applied`, `cancelled` (settled), `skipped` or `rejected` (validator).
- Events: `happening` (applied), `happening_settled`, `happening_rejected` (owner only).
- `GET /happenings` (owner and public), `pipchat happenings`, a "Lately" card on the Now tab. Setting `HAPPENINGS=off|log|on` (default `off` for the first
  deploy; `log` rolls and authors but applies nothing, so the owner can read them first), `HAPPENINGS_PER_DAY`, `HAPPENINGS_MIN_GAP_HOURS`.

## Safety and testing
- The mechanical layer (eligibility, rolls, caps, pity, effects, lens, pending, settle) is plain code with a seeded RNG, so it takes the usual red/green and
  mutation gate. The model sits behind one function, `author()`, tested with the fake backend: validator cases (invented names, extra numbers, long text, deny
  words), the retry, and the template fallback.
- Invariants as tests: no effect can take a stack below its floor, remove the last tool, touch a project, note or creation except through the listed effect,
  or make a purse negative; total emotion movement per day is capped; a day never exceeds `HAPPENINGS_PER_DAY` by more than one.
- `log` mode and an owner command to replay a seed make it reviewable before anything is applied.

## Risks
- **The model embroiders** (a mouse that "ruined everything"). The effects line is the truth, the validator rejects mismatched numbers and items, and Pip's guide
  says that only the line counts.
- **Repetition.** Category cooldowns, effect-kind spacing, recent happenings in the author prompt, and a first-seen bonus for new categories.
- **Feedback spirals.** Pity weights, caps on daily emotion movement, resource-costing outcomes suppressed when Pip is low, sleep and decay still do their work.
- **Mood by remote control.** Several bad happenings in a row would steer Pip's emotions. The pity rule, the half-pending design and `settle` are the checks, and `log`
  mode lets the owner see the distribution before it applies.
- **Public view.** The text is public (like the diary) and may name a neighbor; redaction already hides real names. Happenings never include visitor text.

## Build order
1. **Engine, no model.** Table, categories (garden, creature, pantry, found, body, market first), triggers, rolls, caps, effects, lens, pending and settle,
   `log` mode, templates for the text, API and `pipchat happenings`. All tested.
2. **Author.** The GM call, the world-facts packet, the validator, the retry and fallback, the prompt block, the feed line, firsts.
3. **The rest of the categories** (mishap, neighbor, memory, kindness, atmosphere) and the Now-tab card, public view, reflection hooks.
4. **Later:** happenings that offer a choice with engine-checked options (a stray cat follows Pip home: keep it?), night happenings written for waking, happenings
   that a neighbor originates, and a seasonal layer.

## Questions for the owner
1. Frequency: two a day on average, three hours apart at least, is my guess. More, fewer, or none at night?
2. Coins: may a bad happening cost coins (a few at most), or is the purse off limits?
3. Should some categories be off-limits on principle (for example `mishap` stopping a creation, `pantry` spoilage)?
4. Half now, half pending with `settle` as the escape is my suggestion for Pip's agency. Would you rather Pip be asked its stance first (accept, shrug,
   dwell), at the cost of an extra tick?
5. Start in `log` mode for a few days, and read what the model writes before anything applies?
