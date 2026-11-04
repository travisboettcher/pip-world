# Design: wishes of every kind

Status (2026-11-04): built (0.8.0). Prompted by Pip's answer to a visitor who asked what it wished it could do: a fine set of needle files, and to run its own market stall.
Both had been on Pip's mind for days and it had said nothing, and it had never gone looking for the files.

## What was wrong
- **Wishes were things.** The wishlist was described as "things you want - objects, experiences, people", and in practice held only objects. An activity Pip would like to do, an ability
  it wished it had, something it wanted to understand: none of those got written down, so none could be told to anyone.
- **A wish was not connected to anything.** Pip wrote "a finer set of needle files" on 2 November and never ran `where_to`, never looked at what a booth sold, and wrote no to-do. Even if it had asked,
  nothing in the world named fine needle files: a built-in place's stock is only learned by finding things there, and the one market Pip knew (Brygdon) was *bare*: its design had come back with
  no stock, so Pip could sell there but not buy, and `buy` could not see a market's stock at all.
- **Nobody was told.** Pip only said what it wished when asked.

## What changed
1. **A wish has a kind**: `thing`, `activity`, `ability` (something it wishes it could do but cannot) or `idea` (something it wishes it understood). `note_to_self(section=wishlist, kind=...)`; no kind is a
   thing. The tool and the guide say the wishlist is for anything wished for, and that a wish Pip cannot yet act on should say what stops it. Wishes carry their kind through `/notes` (a small tag in the Journal tab).
2. **A wish for a thing says where it could be had.** In the prompt, beside the wish: "[you could try: Brygdon sells needle file (12 coins); the junkyard has turned up needle file]": shops and markets that
   stock something like it, with today's price, then places Pip has been that have turned it up. At most two, never for other kinds.
3. **The night's reflection may add wishes.** It is asked for at most two things Pip found itself wishing for since it last slept (activity, ability or idea), validated (a known kind, a short text, not a repeat of an
   open wish) and filed. This is Pip noticing, not a question put to it.
4. **Wishes that are not things are told to Pip's friend, unasked.** One postcard a day at most (`WISH_SHARE=on`), through the same channel and limits as its other postcards: the newest such wish, and a second or third if they fit
   in the card. A postcard that fails is tried again an hour later; each wish is told once. The guide tells Pip that its wishlist is read, so it is a way of telling.
5. **A trading place is never bare.** A shop or market whose design names nothing for sale is given a standard stock drawn from what Pip can find elsewhere (`STAPLE_COUNT` kinds, within the kind's tool limit), and
   one already real and bare (Brygdon) is stocked once at startup. `buy`, `browse` and `where_to` now read a market's stock (a market has no gathering, so they used to see nothing).

## Not done
- Fine needle files are still not anywhere in the world: the staples are drawn from the junkyard and woods tables, which hold a plain needle file. A wish for something the world does not have stays a wish, and
  that is meant to be a way of telling its friend.
- Wishes are not yet closed automatically when something that meets them is bought; the existing "you've since received" prompt covers gifts only.
