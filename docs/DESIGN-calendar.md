# Design: a calendar in the journal

Status (2026-11-19): built (0.63.0), on Ashfall first; Pip's world gets it with its move to the main line.

## Why (the owner, 2026-11-19)
Promises with a time had nowhere to live but the to-do list, which has no time. Pip's neighbour asked it over on Thursdays at half
past four: from 3 November it rewrote that to-do about forty times (lately ten a day, "Thursday: leave for the marsh by 16:12..."),
and twice kept it on the wrong day ("Carrot for Oriel delivered in person; the Thursday promise is kept", on a Saturday). In Ashfall,
Sela promised to come to Wren's in the morning, with nothing to bring it back at the right time.

## Decisions (the owner)
- A section of the journal: the calendar.
- The agent is woken when it's time to set off (walk included); from rest, not from sleep (a morning one is there at waking).
- Ashfall first; Pip's world on its move to the main line.

## How
- `note_to_self` with `section: calendar`, `when` (words the engine reads: "Thursday 16:30", "tomorrow morning", "Friday 4:30 pm",
  "2026-11-24 09:15"; a day alone is its morning, 8:00; a weekday whose time has gone this week is next week's), `where` (a place
  it knows, optional) and `repeat: weekly` (optional). Stored as a note with `due_at`, `place` and `every`.
- Each wake shows the next three days ("Thursday 19 November, 4:30 pm (today, in about 6 hours) at the woods: ... a 20-minute
  walk: set off by 4:10 pm"), "It's time to set off" once it is, "Now, here" when it's there, and, once, what it missed.
- The monitor (no model) wakes the agent once when it's time to set off, notes whether it's at the place from half an hour before
  to an hour after, and an hour after settles it: kept, missed, or (with no place) its time came; a `calendar` event says which. A
  weekly one moves on a week; another is crossed off with that outcome. `resolve_note` calls one off.
- A to-do that is about the same thing as an open calendar entry is refused ("that's in your calendar, which will remind you").
- The dashboard's journal has a calendar tab; a guide page (both worlds) says when to use it.
