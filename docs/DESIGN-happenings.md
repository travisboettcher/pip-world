# Design: happenings (small, unscripted events from the world)

Status (2026-11-03): **phase 1 built (0.5.0)**: the engine, the author, `feel`, live; see "What 0.5.0 builds" at the end for what is still to come.
Design v2 follows. v1 went to the owner with five questions; this version folds in the answers: a percentage chance per
three-hour slot instead of a daily count, a severity scale (50 minor / 45 medium / 5 major) as the main limit instead of off-limits categories, coins on the
table, the emotion lens independent of whether the outcome is good or bad, Pip's own reading of the event decided by Pip through the same emotion system, and
live from the first release.

Idea from the owner: things should sometimes happen *to* Pip, written by the model so they are not scripted, drawn from a fixed menu so the model cannot do
anything it likes, with deterministic dice for the outcome, and seen through an emotion that Pip may read quite differently. Replaces the ROADMAP's
"LLM-free surprises" item.

## Why
Pip's days are all its own doing: it plants, rests, visits Oriel, sells tomatoes. Nothing arrives from outside except a visitor or a letter, so the diary fills with
its own intentions and the world feels inert. Happenings give the world a voice (a storm over the beans, a mouse in the pantry, a half-remembered thing on a
shelf) and give the engine an organic way to add pressure we have wanted: a glut that can spoil, prices that gossip, a creation that stops.

## Principles
- **The engine decides what happens and what it changes; the model decides how it reads.** The same referee pattern as projects and creations. Category, severity,
  tone, lens and every effect are chosen and capped in code before the model is asked to write. The model never emits a state change.
- **Severity is the limiter, not the topic.** Almost any kind of thing may happen to Pip. What is bounded is how much it can change, on a three-step scale
  (minor / medium / major) with caps per step. A few rails protect the simulation, not the content (see "Rails").
- **Tone and lens are separate.** *Tone* (good, bad, neutral) is what the engine does to the world. *Lens* is the emotion the event is written through. They
  usually agree, but a bad outcome can be written through joy (a mouse so small and shameless in the garden that you cannot be cross) and a good one through sadness
  (the good find is bittersweet). The lens is rolled, not chosen by the model.
- **Pip interprets.** The author's lens says how the event is *written*; how it *lands* is Pip's reading (see "Through the emotions"), and Pip may read it as
  something else entirely. All emotion movement still goes through the one existing appraisal path.
- **Deterministic dice.** Whether it happens, which category, tone, severity and lens are rolled from a seeded RNG whose seed is stored, so any happening can be
  replayed and tests can pin them.
- **Truth is in the effects line.** Every happening ends with what the engine actually changed ("(You find 2 hazelnuts; 3 coins fall through a hole in your
  pocket.)"), appended by the engine, as neighbor hand-overs are. The prose may be vivid; only the line is real, and Pip's guide says so.
- **Grounded in the world.** The model gets facts (weather, the plot that is ripening, a creation by name, a neighbor, a place Pip has been) and may use only those.

## How often: a percentage per slot
Awake time is divided into **three-hour slots** from the wake hour: with the default 06:00 wake and 22:00 bedtime that is 06, 09, 12, 15, 18 and 21. Each slot has
one roll, at its start, with a **10% chance** (`HAPPENINGS_CHANCE=0.10`, `HAPPENINGS_SLOT_HOURS=3`).
- Six slots a day: the chance of at least one happening in a waking day is 1 - 0.9^6, about 47% (the owner's "about 50%"), and the mean is 0.6 a day, roughly
  one every day and a half or two. A happening is an occasion, not a drip.
- A slot is rolled once, at its start, and recorded in `happening_rolls(slot, ts, roll, hit)`, so a restart cannot roll it twice and the owner can audit the dice.
  A slot missed because the service was down for more than half an hour is skipped, never rolled late. No slot is rolled while Pip sleeps, walks, or while an
  earlier happening is still unresolved.
- The roll uses a per-install salt (stored in the database) with the slot as the seed, so it is reproducible by us and not guessable from outside.

## The pipeline
1. **Slot roll (code):** as above. A miss ends it.
2. **Category (code):** weighted choice among categories whose `needs(world)` holds and that are off cooldown (a category does not repeat within 12 hours).
3. **Tone (code):** good 35 / bad 25 / neutral 40, adjusted: after two bad in a row bad is weighted x0.3; if hunger is high, energy low or the purse empty, outcomes that
   would cost those things are removed from the pool. Each category lists the tones it supports.
4. **Severity (code):** minor 50% / medium 45% / major 5%, for good and bad. Neutral is always minor with no mechanical effect.
5. **Effects (code):** the category's effect for this tone and severity, with parameters chosen from world facts and capped (below).
6. **Lens (code):** a lens emotion from a table by tone, with a real chance of crossing over (see "Lens"). The lens amount depends on severity.
7. **Author (one model call, the GM):** gets category, tone, severity, the effects in plain words, the lens emotion, a small packet of world facts and the last few
   happenings (to avoid repeating). It returns `{title, text}`: two or three second-person sentences written through the lens, in proportion to the severity.
   A validator rejects text that names a person, place or thing not in the packet, mentions a number or item the effects do not, runs long, or contradicts the tone
   (a minor event written as catastrophe). One retry, then a deterministic template for that category is used, so the world works with no model. About 1.5k tokens.
8. **Apply and tell (code):** effects applied, the event logged (`happening`), the emotion appraisal run, Pip woken if awake (not urgent), the row saved.

## Severity scale and caps
Caps are per severity; where a cap depends on Pip's holdings it is the smaller of the fixed number and a share of what Pip has, and nothing goes below its floor.

| | Minor (50%) | Medium (45%) | Major (5%) |
|---|---|---|---|
| Lens amount (emotion points) | 4 | 9 | 16 |
| Crop growth on one plot | +-5% of time left | +-15% | +-30%, or the plot's crop is ruined (empties it) |
| Crop yield on one plot | -1 (floor 1) | -1 to -2 (floor 1) | the plot's harvest is lost |
| Food stack lost to pests or damp | 1 | 10-25% of the stack, at most 10 | up to 50%, at most 25 |
| Items found or given | 1 of a common thing | 2-4 | 4-6 |
| Coins lost or found | up to 3, at most 10% of the purse | up to 10, at most 20% | up to 25, at most 35% |
| Energy or hunger | +-0.05 | +-0.12 | +-0.25 (never below 0.1 energy) |
| A creation | a squeak, nothing wrong | it stops until tended | it stops and `tend` needs a small material the engine names (phase 2) |
| A market price at one booth | +-5% | +-12% | +-25% |

What stays out is about the simulation, not the subject: nothing deletes a note, project, creation, place or the persona; no purse goes negative; hunger and energy
keep floors; no happening makes a promise about the future (only the effects line is real); no real person other than the owner and neighbors the engine knows.
Death and serious injury are not categories because the engine has no way to recover from them (question 1).

## Categories (v1)
Each is a table row: `needs`, supported tones, effects by tone (using the caps above). The lens is rolled independently of any of it.

| Category | Needs | Good | Bad | Neutral |
|---|---|---|---|---|
| `garden` | a crop growing | a mild spell: ripens sooner; a better yield | a bad turn: ripens later, a lost yield | a change in the air |
| `creature` | home | leaves a feather or seeds | nibbles the pantry | watches from the fence |
| `pantry` | a food stack of 20 or more | none | some of it turns: damp, mice, a split crate | a check of the shelves |
| `found` | any place | a small find, or a few coins | a hole in a pocket: coins gone | an odd thing noticed |
| `mishap` | a creation or a tool | none | a creation stops until tended | a squeak, nothing wrong |
| `neighbor` | a known neighbor | word of good news for them | a worry for them | gossip |
| `memory` | 7+ old notes or a first | a fond thing surfaces | a wistful one | a puzzling one |
| `body` | awake | slept well | a stiff back, a rough day | a yawn |
| `market` | a shop or market | a rumour of a good price | a rumour of a glut | a rumour |
| `kindness` | a known neighbor or the owner | an anonymous gift (item or coins) | none | none |
| `atmosphere` | none | none | none | a sound, a light, a smell |

## Lens
The lens emotion is chosen from a table by tone, with a **crossover chance** so that the same outcome can be told several ways:

| Tone | Usual lens (about 80%) | Crossover (about 20%) |
|---|---|---|
| bad | sadness, fear, anger, disgust | joy, anticipation, trust (the amusing or tender side of a bad turn) |
| good | joy, trust, anticipation | sadness, fear (bittersweet, or uneasy luck) |
| neutral | surprise, anticipation | any |

The author is told its lens as an instruction about *voice*, not outcome: "write this through joy". A mouse in the garden through joy is as valid as one through anger;
the effects are the same either way. This is the "event written to affect sadness" idea: the lens fixes the emotion the event is written to move, and Pip decides how
much of that it takes.

## Through the emotions
**How emotions move today.** There is one path. Every logged event passes the emotion module's appraisal table (`emotions._appraisal`): a work setback moves sadness
and anger, a gift moves joy and trust, a ripened crop moves joy, and so on, through `nudge`, each move logged with its cause. The numbers decay toward baseline, a
night's sleep eases them, and Pip's only say is `settle` (ease a strong feeling, a few times a day). Nothing lets Pip interpret an event. Happenings use the same path
and add the missing piece.

**Two-step appraisal (the author's lens, then Pip's reading):**
1. **First jolt (immediate).** The `happening` event is appraised in the existing table: *surprise* rises by 30% of the lens amount. Every event is a little startling,
   whatever it means.
2. **Meaning (held, then resolved).** The remaining 70% is held as the happening's *meaning*, to be applied once to one emotion. By default that emotion is the
   lens. But Pip is shown the event ("Something happened: ... How it lands is up to you.") and may use `feel` to say how it takes it:
   `feel(emotion, about?)`, where `emotion` is one of the eight or `nothing`. The meaning then goes to **that** emotion instead (or is dropped for `nothing`),
   recorded as `read_as`. So the author writes it through sadness, and Pip may read it as joy, trust, or a shrug.
3. **When it resolves:** at Pip's `feel`; or after Pip has been shown the happening once and has had one more tick; or after 45 minutes awake, whichever comes first.
   While Pip sleeps nothing resolves, so the meaning lands on waking, on whichever reading Pip gives it.
4. **The amount is the engine's.** Pip chooses where the meaning goes, not how much. `feel` cannot amplify, and a happening is resolved once.
5. **Recorded.** `happening_felt` (the event that carries the resolved moves, appraised through the same table) stores lens, `read_as` and whether it differs. The
   reflection and the self-knowledge work can use it: how often Pip reads things differently from how the world told them is a fact about Pip.

`feel` is also the self-report verb planned in DESIGN-emotions.md (step 4). With no happening waiting it only records a report next to the engine's numbers, for the
introspection-accuracy fact; it moves nothing. `settle` stays what it is.

## What Pip sees and remembers
- A prompt block while a happening is unresolved or fresh: the text, the effects line, and the sentence that how it lands is Pip's to say.
- `happening` and `happening_felt` events in the feed and log (public view: text and effects line, names redacted as usual), importance scaled by severity, so they
  are offered as diary moments and reach the nightly reflection and `recall`.
- `firsts`: the first of a category is a first. The author is told recent happenings but not Pip's feelings or persona, so it narrates the world and not Pip's mind.

## Data, settings and API
- `happenings(id, ts, slot, category, tone, severity, lens, seed, context JSON, effects JSON, meaning JSON, read_as, text, title, author, status)`; `author` is `gm`
  or `template`; `status` is `applied`, `resolved`, `skipped`, `rejected`. `happening_rolls(slot, ts, roll, hit)`.
- Settings: `HAPPENINGS=on|off` (default **on**; `log` remains as an owner option that rolls and writes but applies nothing), `HAPPENINGS_CHANCE=0.10`,
  `HAPPENINGS_SLOT_HOURS=3`, `HAPPENINGS_SEVERITY=50,45,5`, plus a safety `HAPPENINGS_MAX_PER_DAY=3`.
- `GET /happenings` (owner and public), `pipchat happenings`, `/happenings replay <id>`, a "Lately" card on the Now tab.

## Safety and testing
- Everything mechanical (slots and rolls, eligibility, tone, severity, caps, effects, lens, meaning and resolution) is plain code with a seeded RNG: red/green and
  the mutation gate. The model sits behind one function, `author()`, tested with the fake backend: the validator cases, the retry, the template fallback.
- Invariants as tests: no stack goes below its floor; the purse never goes negative; energy and hunger keep their floors; nothing touches notes, projects,
  creations or places except through a listed effect; one happening resolves once; the lens amount per severity is fixed; no more than `HAPPENINGS_MAX_PER_DAY` a day.
- Live from the first release, so the guard rails are the caps, the validator and the effects line; every happening is visible in the feed and in `/happenings`,
  and `HAPPENINGS=off` switches it off at once.

## Risks
- **The model embroiders** (a mouse that "ruined everything" at minor severity). The effects line is the truth, the validator checks proportion and mismatched numbers.
- **Repetition.** Category cooldowns, recent happenings in the prompt, a first-seen bonus for new categories. At about 0.6 a day it is a rare occasion, which helps.
- **Mood by remote control.** Several bad happenings in a row would steer Pip. The pity rule, severity weights and Pip's own `feel` are the checks; at 10% a slot a
  streak is rare.
- **Pip never uses `feel`.** Then the lens default applies, which is the world's reading. The guide and the prompt block tell Pip it can, and the share of readings
  that differ is visible.
- **Public view.** The text is public like the diary and may name a neighbor; redaction already handles real names. Happenings never include visitor text.

## Build order
1. **Engine, author and `feel`, live:** tables, slots and rolls, categories (garden, creature, pantry, found, body, market first), tone, severity, caps, effects, lens, the
   two-step appraisal and `feel`, the GM author with validator and template fallback, prompt block, feed line, API, `pipchat happenings`. All tested. `HAPPENINGS=on`.
2. **The rest of the categories** (mishap, neighbor, memory, kindness, atmosphere), the Now-tab card, the public view and the reflection hooks.
3. **Later:** happenings that offer a choice with engine-checked options (a stray cat follows Pip home: keep it?), the major creation repair, night happenings written for
   waking, happenings a neighbor originates, a seasonal layer.

## Remaining questions for the owner
1. Death and serious injury are left out because the engine cannot recover from them. Should a major happening ever carry that as pure flavour (no mechanical effect), or
   stay out entirely?
2. `feel` is a new tool (it was already planned for introspection). Are you happy with a dedicated tool, rather than extending `settle`?
3. The first jolt is surprise at 30% and the rest is meaning at 70%. Different split?
4. Pip reading an event as `nothing` drops the meaning entirely. Fine, or should a shrug still leave a trace?

## What is built (0.5.0 and 0.6.0)
**0.5.0:** slots and rolls (`happening_rolls`), severity, tone with the pity rule, lens with the crossover, the caps, effects and their descriptions, the model author with its
validator and templates, the two-step appraisal (`happening` then `happening_felt`) through the existing emotion table, the `feel` tool, the prompt block, feed lines,
`GET /happenings` (owner and public), importance and recall, `HAPPENINGS=on|log|off`.
**0.6.0:** all eleven categories (`garden`, `creature`, `pantry`, `found`, `body`, `market`, plus `mishap`, `neighbor`, `memory`, `kindness`, `atmosphere`); the major
creation repair (a stopped creation may need a part of a junkyard material before it can be tended again, shown in its status line); neighbor news joins the neighbor's life
as the happening's title; a memory happening brings back a real note older than two days; `body` also moves appetite; firsts (the first of each category, and the first time Pip
reads something differently from how it was told); the "Lately" card on the Now tab; `pipchat happenings` and `pipchat happenings --replay ID` (also `GET /happenings/{id}/replay`, owner
only), which rolls a slot again from its stored seed to check the dice.
Deviations from the design above:
- Found coins are a fixed range per severity (1-3, 3-10, 8-25); only a *loss* is capped by a share of the purse.
- A happening is resolved by its status (`applied` to `resolved`), not a flag in the meaning.
- Replay re-rolls the slot and shows the recorded decisions; it does not rebuild the choice, since that depends on the world as it was.
Still open: happenings that offer a choice, night happenings written for waking, happenings a neighbor originates, a seasonal layer.
