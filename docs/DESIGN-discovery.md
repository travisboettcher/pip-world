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

## Discovery
- **Partial plans.** The GM plans only what Pip could know to do now (1-3 firm stages) and lists up to 3
  `open_questions` (what Pip doesn't yet know). It also writes 1-3 `hidden` facts about how the thing really works,
  which Pip never sees until discovered. A project with open questions is not finished when its known stages are:
  it is at a crossroads.
- **`experiment(project, hypothesis, minutes)`** is a real-time session (kind `experiment`). When it ends, the
  engine rolls (ingenuity + knowledge, difficulty, fatigue) for an outcome: `nothing`, `clue`, `insight`,
  `surprise`. The GM only judges relevance and narrates: if the hypothesis has nothing to do with the hidden facts it
  says `relevant: false` and the engine downgrades to a clue at best. On insight the engine reveals one hidden
  fact (becoming a finding), may answer an open question, and adds the follow-on stages the GM proposes (capped,
  sanitized). A surprise also lets the GM add one new open question or need.
- **Pity timer.** After two dry experiments (nothing/clue) on a project the next relevant one is an insight, so a
  project can't be stuck forever. Irrelevant hypotheses don't count as dry.
- **`revise_plan(project, because)`** is for what Pip learned elsewhere (web_search, the library, a visitor). The
  GM accepts or declines; if accepted it may add stages, drop *unstarted* stages, answer a question or confirm a
  hidden fact the source plausibly covers. Needs some work or an experiment since the last revision.
- The engine owns every number and the rolls; the GM invents within constraints and never decides success.
  Everything it returns is validated (stage caps, material caps, vocabulary).

## Prior art
- Voyager: iterative prompting with a growing skill library; AutoDiscovery: surprise-driven hypothesis search;
  Reflexion: verbal reflection after failure; AIMA's learning agent (the experiment is the "problem generator",
  the findings are the learning element's output). Verify these before citing publicly.

## Deploy
Add `experiment,revise_plan` to `TOOLS` in `.env`.
