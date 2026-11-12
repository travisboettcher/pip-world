# Design: a neighbor (slow letters)

Status (2026-10-29): built and tested (unit tests and real-model runs). Since 0.37.0 (world packs phase 5b) the neighbour is invented, and
asked to write first, by the shipped `neighborhood` module (structured asks, the `character` and `letter` hooks); letters and answers
stay the engine's, as below. Phase 4 of
DESIGN-creations.md, made concrete.

## Why
Every person Pip knows is Morgan: every people note, belief and diary entry about someone else. All of its materials
and seeds come from him. A second character gives the new people memory something to work with (Pip forming its own
view of someone who isn't the visitor), gives the world another source of things, and gives Pip a reason to make
gifts. Letters are slow, so this is cheap and doesn't crowd Pip's day.

## Who the neighbor is
Not hand-written: following the "open-ended by default" principle, the GM **invents** the neighbor the first time
the service starts with `NEIGHBOR=1` (the default): a name, a private persona (who they are, their life, how they
write), and a one-line public `about` - what Pip knows of them (`Lives across the meadow; keeps bees`). The
neighbor's first letter introduces them and arrives a little later. If the GM call fails, it's retried after an hour;
there is no canned fallback neighbor.

The neighbor has a life of their own: every letter they write may carry a `life_update` (one sentence: what's new
for them), and the last few are kept and fed back into their next letter, so their story moves on between letters.

## Letters
Table `letters`: sender, recipient, text, what was enclosed (Pip -> neighbor), the parcel (neighbor -> Pip),
`deliver_at`, `delivered_at`, attempts, and which letter it answers.

- **Pip writes**: `write_letter(to, text, enclose?)`. Delivery takes `LETTER_DELAY_MINUTES` (default 120, +-30%).
  At most `LETTERS_PER_DAY` (3) so Pip can't flood the post. `enclose` gives away one item (one unit) or one
  creation: it leaves Pip's belongings, and the neighbor is told what it is.
- **The neighbor reads it on delivery** and writes back (one GM call in the neighbor's voice, with their persona,
  recent life, the last few letters both ways, and what was enclosed). The reply travels back with the same delay,
  so an answer arrives roughly 4 hours after Pip writes.
- **The neighbor writes first** now and then: every `NEIGHBOR_WRITES_EVERY_HOURS` (default 30, +-30%), unless a
  letter between them is already on the way.
- **Parcels**: a neighbor letter may enclose a small parcel (a material, seeds, food or a tool; quantity 1-3), at
  most `PARCELS_PER_DAY` (1). Seeds get the usual defaults, so Pip can plant them.

A letter for Pip lands in the inbox with the neighbor as sender (and wakes Pip), so everything that already works
for visitors works for letters: perception, diary moments ("A letter came from ..."), recall ("X wrote to you"),
and the nightly reflection, which writes people notes about the neighbor. Pip is told that letters are answered with
`write_letter`, since the neighbor can't hear `say`.

## In the prompt
- `Your neighbors (you can only reach them by letter, with write_letter)`: name and `about`
- letters on the way, both directions, with how long ago they were sent

## Visits
In the first real run the neighbor invited Pip over ("come on a Thursday") before the world had places, so for a
while both sides were told everything happens by letter. Now that places exist (DESIGN-library.md), each neighbor's
home is a place, "<Name>'s home":
- `go_to <name>` walks there (`WALK_MINUTES`); the first visit gets a lasting description written from who they are.
- On arrival the neighbor greets Pip (once per visit); `say(text, to=<name>)` gets a spoken answer that wakes Pip,
  capped by `COMPANION_REPLIES_PER_HOUR`. Their lines are `companion` events with `visit: true`, so memory, recall
  and reflection see the conversation, and later letters remember it.
- Neighbors don't move: they're told Pip may visit them but they don't go out visiting. Things Pip says to them
  while not there get "write_letter, or go_to their home to visit"; anything unanswered is dropped when Pip leaves.
  Pip leaves when it *sets off*, not when it arrives elsewhere: on the walk home it can't be heard and gets no answers
  (the first real visit, 2026-10-31, had Pip and the neighbor trading goodbyes all the way down the path).
- While the neighbor hasn't answered yet, Pip is told so ("give them a moment"): replies take a GM call, and Pip
  otherwise asked the same question three times in a minute.
- A visit is remembered: the neighbor line says when Pip last visited, and an open to-do naming the neighbor that was
  written before the latest visit gets "[you've since visited X - is this done? ...]" (like the wishlist's "you've since
  received"). Without it the visit scrolled out of recent events and Pip did the same "walk over to X" to-do again.
- Work and gardening still need Pip at home.

## Variety
Two of three test inventions were a clock- or music-box-mender, though nothing in the prompt mentions clocks (the
model's own lean, probably from "workshop"). The invention prompt asks for a life genuinely different from Pip's,
without naming any examples. A neighbor is invented once and kept; to get a new one, delete the `characters` row
with `kind = 'neighbor'` (and its letters) and restart.

## Guards
Letter text and parcels are model-written: parcels are validated (kind, quantity 1-3, name length) and capped per
day; letters are clipped. A neighbor letter that can't be written (GM failure) is retried up to 3 times, then dropped
quietly. Creations given away keep existing in the database (`given_to`) but leave Pip's world: they stop running,
and a companion creation goes silent.

## Not now
The neighbor visiting Pip, handing things over in person (letters can enclose gifts), more than one neighbor (the
table allows it), Pip trading or selling.
