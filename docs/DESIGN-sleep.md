# Day, night and sleep

Pip had no sense of time of day: it ticked every minute around the clock, and the nightly reflection fired at a
fixed hour whether or not Pip was ever "asleep". This adds a day/night rhythm and real sleep.

## Behaviour
- **Time of day** (local clock): morning / afternoon / evening / night, plus "day N of your life here" in the
  perception. Night is `BEDTIME_HOUR` (22) to `WAKE_HOUR` (6). Pip sees words, not clock time (a clock it makes
  can tell it the time).
- **`sleep` tool**: at home, Pip can go to bed **whenever it likes** (changed 2026-10-31: it was night-only, and on its first day Pip tried
  six times in the evening and was refused each time). It sleeps until the next `WAKE_HOUR`. Sleeping stops any
  work session, recovers energy faster (`SLEEP_RECOVER_PER_HOUR`) and slows hunger (half rate). Pip is never forced:
  if it stays up, the perception just says it's night and it can go to bed. By day the perception gives the *usual* bedtime ("You usually go
  to bed around 10 pm, but you can sleep whenever you like") instead of a gate; Pip's energy, which it already sees, is what should steer it. No rule
  forces or forbids an early night. Naps are `rest(minutes)`.
- **No ticks while asleep.** The heartbeat sleeps until wake time, which also saves roughly a third of the token
  spend. Alerts, ripe crops, creations and the neighbor's letters do **not** wake Pip; they are there in the
  morning. A visitor's message or gift, or `POST /tick`, wakes it early (it's told so, and can go back to bed).
- **Reflection happens in sleep.** When Pip falls asleep, the day's reflection runs (once per sleep) and its
  results are what Pip wakes up with. `REFLECT_HOUR` remains only as a fallback when Pip hasn't slept for over a
  day or sleep is off.
- **Firsts as facts.** The first sleep and first waking are reported plainly ("this is the first time you've gone
  to sleep"); what Pip makes of it is up to Pip. Part of the introspection work (see ROADMAP).

## Settings
`SLEEP=1`, `BEDTIME_HOUR=22`, `WAKE_HOUR=6`, `SLEEP_RECOVER_PER_HOUR=0.25`; add `sleep` to `TOOLS`.

## State
`agent.activity = "sleeping"`; meta `sleep_started`, `sleep_until`, `reflected_sleep`, `born_at`, `first_sleep`.
Events: `woke` (hours slept, early or not, first).
