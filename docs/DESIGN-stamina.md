# Stamina: energy is what an agent can spend

Status: approved (the owner, 2026-11-24); 0.68.0. Ashfall first, then Pip's world.

## Why
Two limits ran side by side and never met. Energy was an in-world number that hardly mattered: it fell 0.05 an hour awake, nothing an
agent did spent it, and agents went to bed at "evening" with plenty left (Tansy at 12:23, sleeping 18 hours, since bed always meant
"until morning"). The daily token budget was an out-of-world wall: on 2026-11-24 Oriel spent hers talking with Pip from 08:10 and hit
it at 14:21 with no warning; nothing in her world had told her she was tiring.

The owner's idea: energy is the in-world face of what an agent can spend. Thinking and talking tire you; rest and sleep restore you;
the day's budget stays as a hard ceiling behind it.

## How it works
- **Energy is stamina, measured in tokens.** Each agent has a `stamina`: how many tokens a full bar of its tiring stat (`tires`, energy
  in both worlds) holds. Every model call it makes spends energy in proportion to its tokens (`tokens / stamina`), on top of the
  time-based fall the stat already has (the owner: time awake still tires). Talk lines, world turns, reflections, the night pass: all
  count, for whoever made the call.
- **Rest and sleep restore it**, at the rates the world already gives (`resting_per_hour`, `asleep_per_hour`). Restoring energy is what
  lets an agent spend again: the day's spending is paced by how much it rests, and the hard daily budget (`DAILY_TOKEN_BUDGET`, per
  agent) stays behind it as the owner's ceiling.
- **Stamina differs per agent** (the owner): world.json `stamina` on an agent, else the tiring stat's `stamina` in stats.json, else a
  default. Oriel is old and tires easily; Tansy, young, goes on.
- **Tired shows, and bites before empty.** The perception says how the agent feels in words (wide awake / a little tired / tired /
  exhausted), not only the number. Below `tired_below` it's tired, as now. At its `floor` it is exhausted: it can only do small things
  (the stakes' weak set: eat, rest, sleep, a few words, its notes and feelings), and a talk it's in ends ("too tired").
- **Naps.** Going to bed before the evening cut-off (`NAP_BEFORE_HOUR`, by default two hours before `BEDTIME_HOUR`) is a nap: it lasts
  until the agent is rested (at its asleep rate), at least 20 minutes and at most 2 hours. Bed after the cut-off is the night's sleep,
  until morning, as now. A nap doesn't run the day's reflection or the night pass; the night's sleep does, once.
- **Running out of budget is falling asleep.** When an agent reaches its daily budget, it doesn't stand there silent: it's exhausted
  and sleeps until morning (where it is, if it can't get home), and anyone speaking to it hears it's asleep.
- **Messages wait.** A visitor's message (the owner's included) no longer wakes a sleeping or exhausted agent: it waits in the inbox and
  is the first thing the agent sees when it wakes (the owner, 2026-11-24). Today a visitor wakes a sleeper; this changes that.

## Numbers
First guess, 300k-800k tokens a bar and -0.03 an hour: replayed against Monday's real calls (2026-11-24), Oriel was exhausted at 08:10
and Pip at 08:38, before their talk began; ordinary world turns alone cost about 100k tokens an hour. So a bar is about a day's
ordinary spending, and time awake tires less:
| | |
|---|---|
| awake, idle | -0.02 an hour (was -0.05): about a third of a bar over a day |
| a call | -tokens / stamina |
| resting / asleep | +0.3 / +0.25 an hour: a 2-hour nap restores half a bar |
| default stamina | 2.5M tokens |
| Pip's world | Pip 2.5M, Oriel 1.2M (she tires quickly), Abel 2M, Tansy 3M, Lio 2.5M |
| Ashfall | Wren 2.5M, Ivo 3M, Hester 2M, Tobin 3M, Sela 2M, Marta 1.5M |

Replayed on Monday's calls (no naps taken, to see where they would come): Oriel, talking with Pip from 08:10, is tired at 10:37 and
exhausted at 10:59 (she hit her 2M budget at 14:21 instead); Pip, on his heaviest day, tired at 12:47 and exhausted at 14:22; Abel and
Lio, on ordinary days, end the afternoon at 0.3-0.4, tired by the evening.

## Ashfall's first day (2026-11-25), and 0.68.1
Naps came and were short (Hester 17:32 for two hours, then 38 minutes, to bed at 20:10; Marta a nap at 18:32, to bed at 20:32; Ivo to
bed at 22:02, where before everyone went at about 17:30), naps brought no reflection, ordinary days fitted their budgets (1.6-1.7M),
and "too tired" ended talks. Two loops:
- Tobin, at Hester's while she napped and then slept, had words waiting for her: every turn of his opened a talk that ended at once
  ("asleep"), 1,547 of them from 17:32 to midnight, and he never went to bed. Wren, exhausted from 15:34, had 44 talks with Sela end
  "too tired" before a word. Now no talk starts with one asleep or exhausted: the words are answered in a turn of the other's, and
  speaking to them says so ("is asleep", "is too tired to talk now").
- Exhausted only limited what Wren could do, not whether she went on: 43 lines and 35 activities later she was out of budget at
  16:40. Now an exhausted agent who is awake dozes off where it is, without a call to the model: a nap by day, the night by night.

## What changes in the engine (generic)
- `stats.py`: the tiring stat's drain from a call's tokens (`spend(state, tokens)`, called where usage is added); `stamina` from the
  agent or the stat.
- `world_pack.Agent.stamina`; stats.json `stamina` on the tiring stat.
- `sleep.py`: `fall_asleep` decides nap or night; `NAP_BEFORE_HOUR`; the nap's length from energy; reflection and the night pass only
  after a night.
- `stakes.py`: exhaustion at the tiring stat's floor uses the existing `weak` tools; `talk.cut_short` ends a talk for an exhausted speaker.
- `loop.py`: budget reached means asleep until morning; a visitor's message no longer wakes a sleeper (`urgent` wakes go).
- The perception's tiredness words; the guide's sleep page (naps, tiredness).

## Done when
- A call's tokens lower the caller's energy by `tokens / stamina` (each agent its own), and time awake still lowers it.
- Bed before the cut-off is a nap until rested (20 min to 2 h) with no reflection; after it, sleep until morning with one reflection.
- An exhausted agent can only eat, rest, sleep, speak briefly and think, and its talk ends.
- An agent at its daily budget sleeps until morning; a message to it waits, unread, until it wakes.
- Replayed on Monday's Pip-and-Oriel calls, Oriel is exhausted a couple of hours into the talk, not at her budget in the afternoon.
- Ashfall for a day: no agent hits its budget; bedtimes move from 17:30 to the evening; naps happen and are short.
