# Design: emotions

Status: **steps 1-2 built 2026-10-31** (state, appraisal, log, API, `pipchat emotions`, `/emotions`, the Now-tab meters, the prompt readout, and a `settle`
action). Steps 3-4 (behavioural effects, nightly arc, `feel`) are not built. Idea from the owner, 2026-10-30: "a more complex emotion system, with core emotions that run from 0-100 and
combined inform Pip's behavior".

## What exists
Pip has `mood` (one free word it sets itself, e.g. "hopeful"), hunger and energy. Mood is whatever the model last wrote; nothing produces it and
nothing depends on it. So feelings are decoration: a project that blows up, a visitor leaving, a week alone and a breakthrough all leave Pip's
state identical.

## Principles
- **A functional model, not a claim.** These are numbers an engine keeps because they make Pip's behaviour more coherent and more interesting, not a
  statement that Pip feels. Docs and UI say "emotion state", never "feels".
- **The engine owns the numbers; Pip owns the words.** Same split as the rest of the world: emotions move by deterministic rules from logged events, and
  Pip describes and acts on them. We do not tell Pip how to react.
- **Bounded, visible, reversible.** Every influence on behaviour is small and capped; everything is logged, so you can see why Pip was in a mood.
- Builds on, and feeds, what is already there: appraisal from events and expectations/surprise; the nightly reflection; turning points; firsts.

## The state
Eight core emotions, each 0-100 (Plutchik's wheel, which also gives us ready-made combinations):
**joy, sadness, anger, fear, trust, disgust, surprise, anticipation**. Each has a **baseline** (Pip's temperament: e.g. trust 55, joy 45, everything
else lower) and a **half-life** back to baseline (surprise minutes, anger and fear hours, sadness and trust days), so emotions rise on events and settle on
their own. Derived, never stored: **valence** (positive minus negative) and **arousal** (how activated), a one-line **blend** from the strongest pairs
(Plutchik's dyads: joy+trust = warmth, fear+surprise = awe, sadness+disgust = remorse, anticipation+joy = optimism...), and the old `mood` word stays as
Pip's own label.

## What moves them (appraisal: events in, deltas out)
A table in code, like the creation capabilities, scaled by the event's importance. Examples:
| Event | Moves |
|---|---|
| a visitor message / letter from someone Pip knows; a gift | joy +, trust + |
| a visitor leaves and the hours pass with no one (loneliness) | sadness creeping up, trust down a little |
| work: setback / blowup | sadness +, anger + (blowup: fear +) |
| work: good / breakthrough / project finished | joy +, anticipation + (finished: joy ++) |
| a surprise (an expectation badly missed, a first, a hidden discovery) | surprise +, then joy or fear depending on direction |
| hunger high / energy low | anger + (irritable), sadness + (low energy) |
| a postcard goes out; an answer comes back | anticipation +, then joy/trust on the answer |
| sleep, a rest, a good meal | everything eases toward baseline faster |
| a tool refused / a failed attempt | small anger/sadness |
Some events appraise differently by context (a surprise that is better than expected vs worse), using signals we already compute.

## How they inform behaviour ("combined")
Mostly through the model, a little through the engine, nothing scripted:
1. **Pip sees them.** A compact readout in the prompt (the strongest few, plus the blend and valence/arousal in words), so what it chooses is coloured by
   them. The persona says to treat them as real but not as orders.
2. **Dice.** A bounded modifier (at most +-0.05, like a skill) on work and experiment rolls, from a small function of the combination: flow (joy +
   anticipation) helps; anger/fear/sadness together hurt, with fear making Pip more cautious (fewer blowups, fewer breakthroughs). The GM referee is told the
   state as a fact when judging an approach.
3. **Pace and appetite.** High arousal wakes Pip a little sooner on events; sadness makes rest more restorative and work more draining; joy trims decay.
4. **Social pull.** Loneliness (sadness with low recent contact) and anticipation raise the chance Pip *wants* to send a postcard; the hard limits are unchanged.
5. **Memory and reflection.** Strong feelings raise an event's importance (it is remembered); the nightly reflection gets the day's emotional arc as facts
   (peaks, lows, what moved them) to cite, and big swings are a signal for the turning-point detector.
6. **Self-knowledge.** An optional `feel(<emotion words>)` lets Pip *report* how it is; the engine records the report next to the actual state. How well Pip's
   self-reports match the engine's numbers is a measurable fact about its introspection (from RESEARCH-self.md), shown to Pip like the calibration block.

## Records and visibility
Table `emotion_log` (a snapshot every few minutes or on large moves, with what caused the move), a small `emotions` event when something crosses a band, and
`GET /emotions`; `pipchat emotions`; the Now tab gets eight small meters and an hour-by-hour sparkline; the Mind tab gets "the day's arc". Feed lines for big shifts
("Pip is shaken: fear 71 after the blow-up").

## Risks
- **Scripting by the back door.** Mitigation: only small, capped mechanical effects; no instruction ever says how to act; the prompt readout is numbers and a blend.
- **Feedback spirals** (sadness -> worse rolls -> more setbacks -> sadness). Mitigation: caps, decay to baseline, sleep eases everything, and a floor on each
  modifier.
- **Prompt cost and noise.** The readout is a few lines and only shows what is notable.
- **Anthropomorphism.** Mitigation: the framing above; the owner can set `EMOTIONS=off` (numbers still logged) or `EMOTIONS=quiet` (engine effects only, not shown to Pip).

## Build order
1. State, baselines, half-lives and decay; the appraisal table; `emotion_log`; unit tests with synthetic events; API and `pipchat emotions`.
2. The prompt readout, the blend/valence/arousal, persona line; Now/Mind tab display.
3. Behavioural effects (dice, pace, importance), each behind a setting, with tests that bound them.
4. Nightly reflection arc, turning-point signal, `feel` self-reports and the accuracy fact.

## Questions for the owner
1. Plutchik's eight as the core set, or your own list (e.g. add loneliness, pride, curiosity, boredom; drop disgust)?
2. How strongly should emotions move Pip's real outcomes (dice, pace)? I suggest small and capped, with the prompt carrying most of the influence.
3. Should Pip be able to *do* things about how it is (a `comfort`-style tool, a walk, the neighbour), or just have them evolve from events and sleep?
4. Start with display and prompt only (steps 1-2) and watch, before turning on the behavioural effects?


## Decisions (owner, 2026-10-31)
1. Core set: **Plutchik's eight**, as proposed.
2. Influence: **prompt only for now**. The emotion state is shown to Pip; it changes no dice, pace or wake times yet. Revisit after watching it for a while.
3. Agency: Pip gets a **comfort-style action**, the `settle(emotion, how?)` tool.
4. Rollout: **steps 1-2 first**.

## As built (steps 1-2)
- `emotions.py` holds the rules; the numbers live in tables `emotions` (value + time, decayed lazily on read) and `emotion_log` (every move: emotion, delta,
  new value, cause). `State.log` runs registered listeners after each event; `emotions.attach` registers the appraiser, which maps events to moves:
  gift (joy +10, trust +6, surprise +8), a visitor message (joy +5, trust +4, sadness -6), work by result (breakthrough joy +10 / surprise +6 / anticipation +5;
  good joy +4 / anticipation +3; slow sadness +2; setback sadness +8 / anger +6; blowup fear +12 / sadness +8 / anger +8 / surprise +8) plus a `better`/`worse` than
  expected surprise, experiment outcomes, a finished creation (joy +20, anticipation +6), a crop ripening, hunger and energy alerts, a failed tool call, a postcard
  sent, and waking (every emotion closes 40% of its gap to baseline). Loneliness: after 8 hours without a visitor message, sadness +3 and trust -1, at most hourly,
  never while asleep.
- Baselines: trust 55, joy 45, anticipation 35, sadness 15, fear 10, surprise 10, anger 8, disgust 5. Half-lives: surprise 20 min, fear 2 h, anger 3 h,
  disgust and anticipation 4 h, joy 6 h, sadness 1 day, trust 2 days.
- Derived, never stored: **valence** (mean of joy/trust/anticipation minus mean of sadness/anger/fear/disgust) and **arousal**, each with a word, and a **blend**:
  the strongest Plutchik pair whose members are both at least 8 points over their baselines (warmth, awe, optimism, remorse...).
- **What Pip sees** each tick (mode `on`): the up-to-four emotions at least 10 points from baseline with their gap, then "Overall: pleasant, calm; it feels like
  warmth." If nothing stands out, one quiet line. `EMOTIONS=quiet` tracks without showing it; `off` records nothing and removes `settle`.
- **`settle(emotion, how?)`**: eases one emotion by 35 points but never below baseline, only when it is at least 5 over, at most `EMOTION_SETTLE_PER_DAY` (3)
  per local day. Logged as a `settled` event; the dashboard and `pipchat` show why.
- An `emotion` event is logged when a feeling first enters the high band (60+). `GET /emotions[?limit=]`, `pipchat emotions`, Matrix `/emotions`, and the
  Now tab (eight meters, a tick for each usual level) show the state and what moved it.
- Not built: dice/pace effects, the nightly arc, `feel` self-reports, the turning-point signal (steps 3-4).
