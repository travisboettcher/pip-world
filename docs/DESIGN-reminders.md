# Design: "this reminds you of..." (memory step 3)

Status (2026-11-08): designed, not built. Extends [DESIGN-memory.md](DESIGN-memory.md) step 3, and folds in three mechanisms from
[RESEARCH-self.md](RESEARCH-self.md) that belong to the same machinery: episodes stored with their context (Pink et al. 2025; Tulving's
recall frame), activation that fades with time and is refreshed by use (ACT-R, MemoryBank), and a small competition for the prompt's
attention whose winners and losers are logged (Global Workspace / LIDA).

## Why now
Pip's long-term memory only comes back when Pip asks for it. In the live world (2026-11-08: 996 ticks, 648 indexed memories, 12 day
summaries, 27 insights) Pip called `recall` **twice**. Everything older than the last 15 events, the last 3 days' summaries, the top 5
beliefs and 5 people notes is effectively gone unless Pip thinks to look. People do not work like that: being at Oriel's brings back the
last visit, a gift of wire brings back the clock it went into, a happening that looks like an old one brings that one back. The aim is
that the right old memory arrives on its own, a couple at a time, as a fact with its date and context, and that Pip may use it or not.

Rule as everywhere: the engine chooses what comes to mind and states it as a fact; Pip writes any sentence about it. No LLM calls.

## 1. Episodes keep their context
A memory today is a line of text and a timestamp. To be cued by a situation, and to be recalled with "where you were and how you were",
each indexed memory gets a context row, written by the engine when it is indexed:

```
memory_context(source, ref, place, people JSON, activity, mood, feeling, project, importance,
               uses JSON,            -- timestamps it was used: written, recalled, acted on
               shown_at REAL, faded INTEGER DEFAULT 0, PRIMARY KEY (source, ref))
```
- `place`: Pip's location at the time (the place label; `None` while walking). `people`: names in the event (sender, `to`, a
  companion's or neighbor's name, a gift's giver) plus whoever Pip was with in person. `activity` and `mood` from the agent row;
  `feeling`: the strongest emotion then, if emotions are on. `project`: the active project's title, if any. `importance`: the event's
  existing importance (or the reflection's / note's own).
- Backfill: existing rows get `people` from their event data and `importance`, nothing else (place and mood then are unknown; a recall
  frame simply leaves out what is missing). Guarded by a meta flag like the recall backfill.

## 2. Activation: fading, refreshed by use
Each memory has an activation computed from its uses, ACT-R's base level: `A = ln(sum over uses of (hours since that use) ^ -0.5)`.
A memory used often or lately is easy to bring to mind; one never touched fades smoothly. A **use** is:
- being written (the first use),
- being found by Pip's own `recall`,
- being reminded *and taken up*: on the tick after a reminder, Pip's output (say, notes, diary, tool arguments) shares at least three
  content words with it (the same check as `State.related`).

Being shown is not a use on its own. Otherwise whatever came to mind once would keep coming back because it came to mind (a loop the
research warns about), and a memory Pip ignores would never fade.

**Faded.** Below `FADE_BELOW` (an activation a never-used memory reaches after about two weeks; a tuning constant) a memory is marked
`faded`: it no longer comes to mind by itself, and that is logged once (`faded` event with the memory's ref). Nothing is deleted; `recall`
still finds it, says "(you had half forgotten this)", and the find counts as a use, so it can come back. The day summaries, insights and
portraits that Pip wrote about a stretch are memories too and fade the same way, but more slowly (their importance is higher, see 3).
This is the part of step 4 about insights losing rank; step 4's other part (not indexing raw events a day summary covers) stays separate.

## 3. What comes to mind: a cue and a small competition
**The cue**, built by code every world turn from the situation, as two parts:
- *Context*: the people present or writing (inbox senders, the in-person partner), the place when away from home, the active project.
- *Words*: the inbox messages and the partner's last line, a happening's title, a just-received gift's name, the active project's
  current stage, the latest letter's subject. (Not the whole prompt: that would match everything.)

**Candidates**: the top 30 by BM25 over the cue words, plus up to 10 that share a person or place from the context (newest first).
Never candidates: anything shown elsewhere in the prompt this tick (the last 15 events, the diary entries shown, the current portrait,
the 5 beliefs, the recent day summaries, people notes on show), anything younger than 6 hours (it is still in view), faded memories,
and anything reminded in the last 12 hours (`REMIND_COOLDOWN_HOURS`) unless the cue now has a person or place it did not have then.

**Score**, Generative Agents style, each part scaled to 0-1 across the candidates and weighted 1:
`relevance (BM25)` + `importance / 10` + `activation (squashed)` + `context` (0.5 for a shared person, 0.5 for a shared place or project).

**The competition.** Two slots (`REMINDERS_SHOWN`; one in a conversation scene). The best two above `REMIND_MIN` win; most ticks nothing
clears the bar and nothing is shown, which is fine. Different kinds compete on the same score: an old visit, a day summary, an insight
outside the top five, an old open to-do or wish that matches the cue, a person's note when they are not otherwise shown. At most one per
source kind, so two diary lines never crowd out everything else.

**Logged**: every tick with candidates writes a `reminded` event: the winners (ref, score) and the next three losers. "What was on Pip's
mind" is then a fact the dashboard, the reflection and later work (turning points, the salience idea extended to other prompt blocks)
can read.

## 4. How it reads to Pip (the recall frame)
A block in the perception, after the memory section, only when something won:
```
This brings to mind:
- 3 days ago, at Oriel's, while you were visiting, feeling content: Oriel said: "Bring the tin here, Pip, and sit where the warm board is."
- last Tuesday (something you came to believe): Waiting on crops goes faster when I have a small project on the bench.
```
The frame is facts from the context row, each part only if known: when (with the weekday past two days), where (if not home), what
Pip was doing, how it was (mood, or the strongest feeling). `recall` results get the same frame, so a deliberate search also says where
and when. In a conversation scene the one slot is cued by the partner and the talk so far.

## Settings
`REMINDERS=on|log|off` (default on from the environment, off in bare `Settings` for deterministic tests; `log` writes the `reminded`
events without showing anything, for a few days of watching first if wanted), `REMINDERS_SHOWN=2`, `REMIND_COOLDOWN_HOURS=12`; the
weights, `REMIND_MIN` and `FADE_BELOW` are constants in `app/reminders.py`.

## Cost
No LLM calls. One FTS query and a few small reads per world turn. Prompt: at most two lines of about 300 characters (~150 tokens), and
nothing on most ticks.

## Risks
- **The same memory every visit.** The cooldown, "shown is not a use", and the per-kind cap. The `reminded` log makes it easy to see.
- **Irrelevant reminders** from FTS noise ("give" matching "gives"). `REMIND_MIN`, the context bonus and the requirement of a real cue
  term. If it stays noisy, this is the point to try embeddings (sqlite-vec), already on the roadmap.
- **Pip reciting its reminders.** They are labelled as what comes to mind, not as instructions, and the guide says Pip may ignore them.

## Plan
1. `memory_context` written at index time; backfill; recall frame on `recall` results (useful on its own).
2. Uses and activation; `faded` with its event and the "half forgotten" note in recall.
3. Cue, candidates, score, competition, the `reminded` log, the perception block (behind `REMINDERS`), the talk scene's slot.
4. Dashboard: a feed line for faded memories (owner only) and the `reminded` winners in the tick's detail; `GET /memory` gains
   `on_mind` (the latest winners).

## Tests (planned)
Context captured per source kind and backfilled; activation from uses, falling with time, refreshed by recall and by being taken up but
not by being shown; fading at the threshold, logged once, recall still finds it and revives it; cue built from each situation part;
exclusions (in view, too young, faded, cooldown, cooldown lifted by a new person); scoring order and per-kind cap; nothing shown below
the bar; the block's exact wording with partial frames; the `reminded` event; `REMINDERS=log|off`; the talk scene's single slot.

## Open questions
1. Two slots in the world turn and one in a conversation scene, or fewer?
2. Should simply being shown count as a weak use after all? (Proposed: no.)
3. Start with `REMINDERS=on`, or `log` for a few days to look at what would have come to mind first?
