# Discovery and transferable abilities

Two linked changes to projects (see DESIGN-creations.md for the base design).

Problem: the GM hands Pip a complete stage list up front, so a project is a checklist. Skills are per craft
("clockmaking"), so practice in one place does nothing for another.

## Abilities (transferable, narrated)
- A fixed vocabulary: `precision`, `patience`, `ingenuity`, `knowledge`, `handiness`. Stored as xp in `abilities`.
- The GM tags each stage with 1-2 abilities it exercises (sanitized to the vocabulary; default `handiness`).
- A work session grants its minutes, split across the stage's abilities. Reading grants `knowledge`; experiments
  grant `ingenuity` and `knowledge`.
- The roll uses the mean level of the stage's abilities, plus half the level of the craft ("familiarity", the old
  per-craft xp, kept as a domain bonus). Existing craft xp seeds the abilities once (meta `abilities_seeded`).
- Pip is told in words ("your hands are steady", "patient"), never numbers. The API and pipchat still show numbers
  for the owner.

## Who does what
The plan is **Pip's**. The GM is the world: it reviews, judges and describes, and holds the truth. The engine
owns the numbers and bounds what the GM can do.

- **Pip** writes the steps (`start_project(name, goal, steps)`), says how it will go about each session
  (`work_on(..., approach)`), proposes hypotheses (`experiment`), and edits its plan whenever it likes
  (`revise_plan(steps, drop)`). If Pip has no steps it is told to look things up first.
- **GM** (never rewrites, adds or removes Pip's steps):
  - *reviews* the plan at the start: tags each step with abilities, sets craft/difficulty/tools, may offer one
    "concern" if the plan is plainly unworkable, and writes the **open questions** and **hidden facts** (how the thing
    really works) that Pip can't know yet;
  - *arbitrates* work: given Pip's approach, the die and the hidden facts, it picks a verdict (blowup, setback, slow,
    good, breakthrough) and writes what happened, plus an optional lesson or revealed fact;
  - *judges* experiments (relevance, what was observed) and knowledge Pip brings from elsewhere.
- **Engine**: rolls the die (skill, tools, difficulty, fatigue), clamps the GM's verdict to **one step** either way of
  the die (so a blowup needs a bad roll *and* a reckless approach, and the GM can't hand out breakthroughs),
  applies consequences from a fixed vocabulary (blowup: -25% of the stage's progress, -0.1 energy, one unit of a
  material lost), enforces caps, and keeps the pity timer.

## Discovery
- **Partial plans.** Pip plans what it knows; the GM adds open questions and hidden facts. A project with open
  questions is not finished when its steps are: it is at a crossroads, and Pip has to find the way.
- **Failure teaches.** A session's ruling may include a lesson (a finding) or reveal a hidden fact, so trying and
  failing is also how Pip learns.
- **`experiment(project, hypothesis, minutes)`** is a real-time session. The engine rolls
  `nothing`/`clue`/`insight`/`surprise` (ingenuity + knowledge, difficulty, fatigue); the GM says whether the
  hypothesis was relevant (irrelevant ones teach nothing) and describes what Pip saw. Insight/surprise reveal a hidden
  fact and may answer a question; a surprise can add a new question. Pip decides what to do next; experiments add no
  steps (except a plain "put it all together" step when the last question is settled and nothing is left).
- **Pity timer.** After two dry experiments the next relevant one is an insight.
- **Research.** `revise_plan(..., because)` brings in what Pip learned from `web_search`, the library or a visitor.
  The GM accepts it only if it plausibly settles an open question or matches a hidden fact, and only once per bit of
  new experience (work or an experiment since the last claim). Editing steps never needs this.

## Prior art
- Voyager: iterative prompting with a growing skill library; AutoDiscovery: surprise-driven hypothesis search;
  Reflexion: verbal reflection after failure; AIMA's learning agent (the experiment is the "problem generator",
  the findings are the learning element's output). Verify these before citing publicly.

## Deploy
Add `experiment,revise_plan` to `TOOLS` in `.env`.
