# Design: places, and the library (Calibre, or any folder of books)

Note (2026-11-01): where the books come from is now a provider (`library.py` core; `library_calibre.py` and `library_folder.py` register by name; `LIBRARY_PROVIDER`,
default `auto`). This document describes the Calibre provider, which is where the library started.

Status (2026-10-29): built and tested (unit tests with a synthetic Calibre library, and a real-model run against
the homelab library); not yet deployed.

First real run: nudged by a visitor, Pip walked over (the GM described the room from the real shelves - Call of
Cthulhu, Numenera, Pathfinder beside the Docker Cookbook), searched for something to help its clock, read 45 minutes
of *Deep Magic 1: Clockwork* (a summary plus two quotes), wrote about it in its diary, walked home and went back to
work. Calibre's `metadata.db` was byte-for-byte unchanged.

## Why
`location` has always been "workshop" and never changes. The homelab already has a real library: calibre-web serves
a Calibre library of ~300 books (programming, tabletop RPG sourcebooks, travel guides; mostly PDF, some EPUB/MOBI).
Making that a place Pip can walk to gives the world a second location, and gives Pip something to read that isn't
made up: what it learns there is real, and it can feed projects ("after reading about ... I want to build ...").

## Places
A small registry: `workshop` (home: the garden and work happen here), `library` (only if the Calibre library is
mounted), and each neighbor's home ("<Name>'s home", see DESIGN-neighbor.md). `go_to(place)` is a short walk (`WALK_MINUTES`, default 10): it uses the same real-time session machinery
as work, so Pip is "walking" until it arrives, then wakes there. While walking, nothing else can start; resting
waits until arrival.

Location now matters: `work_on`, `plant` and `harvest` need Pip at home ("you're at the library; go home first").
Eating, writing, notes, recall, talking and letters work anywhere - visitors and the post find Pip wherever it is.

Each place gets a short description the first time Pip arrives: the GM writes it once (for the library, from what's
actually on the shelves) and it's kept, so the place is consistent.

## The library
Read-only: `../calibre/library` is bind-mounted at `/library` with `:ro`, and `metadata.db` is opened with
`mode=ro`. Pip can never change the real library. calibre-web keeps working as before.

- **Catalogue**: Calibre's `metadata.db` (titles, authors, tags, series, descriptions, formats).
- **`browse_library(query?)`** (at the library): with a query, searches titles, authors, tags, series and
  descriptions; without, wanders a few shelves at random (by tag). Shows up to 8 books with `#id`, author, tags and
  whether Pip can read it (PDF/EPUB with text; MOBI and picture-only books can't be read).
- **`read(book, minutes)`** (at the library): a reading session, 15-90 min, real time, like work. When it ends, the
  engine extracts the next stretch of text from Pip's bookmark (about `READ_CHARS_PER_MINUTE` x minutes, default
  700/min, capped at 24k chars) off the main loop, and one GM call condenses it into what Pip read: a 2-4 sentence
  summary of that stretch, 0-2 short quotes (under 25 words, verbatim), and how far into the book it is. Raw book
  text never goes into Pip's prompt, only the summary. Resting stops early with a shorter stretch.
- **Bookmarks**: table `bookmarks` (book, title, position, sessions, finished). Pip picks up where it left off;
  books it's partway through are shown at the library. Pages without text (pictures) are skipped; if a book has
  essentially no text, reading it says so.
- Text extraction: EPUB via `zipfile` + an HTML-to-text pass over the spine; PDF via `pypdf`, page by page. A
  position is (section, offset), where a section is a PDF page or an EPUB chapter.

## Memory and the rest of the world
- A `reading` event per session: shown in perception, a diary moment when Pip finishes a book, indexed for
  `recall` ("You read The Strange: ..."), and part of the nightly reflection, so what Pip reads can become insights.
- The UI and `pipchat` show where Pip is; `pipchat library` lists bookmarks; `GET /library/search?q=` and
  `GET /library/bookmarks`.

## Not now
Borrowing books to read at home, a librarian character, more places (they'll reuse the registry and `go_to`).
