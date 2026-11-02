"""The Calibre library provider: a read-only window onto a Calibre library (the folder calibre-web serves).

The catalogue comes from Calibre's metadata.db, opened read-only; book files are read by the shared readers in library.py.
"""
import os
import random
import sqlite3

from . import library as lib
from .text import clip


@lib.register("calibre")
class Calibre(lib.Library):
    def __init__(self, path: str):
        self.path = path
        self.db_path = os.path.join(path, "metadata.db")

    def available(self) -> bool:
        return os.path.isfile(self.db_path)

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        return db

    BOOK_SQL = """
      SELECT b.id, b.title, b.path,
        (SELECT group_concat(a.name, ' & ') FROM books_authors_link l JOIN authors a ON a.id = l.author
          WHERE l.book = b.id) AS authors,
        (SELECT group_concat(t.name, ', ') FROM books_tags_link l JOIN tags t ON t.id = l.tag
          WHERE l.book = b.id) AS tags,
        (SELECT s.name FROM books_series_link l JOIN series s ON s.id = l.series WHERE l.book = b.id) AS series,
        (SELECT c.text FROM comments c WHERE c.book = b.id) AS description,
        (SELECT group_concat(d.format || ':' || d.name, '|') FROM data d WHERE d.book = b.id) AS files
      FROM books b"""

    @staticmethod
    def _book(r) -> dict:
        files = dict(f.split(":", 1) for f in (r["files"] or "").split("|") if ":" in f)
        fmt = next((f for f in lib.READABLE if f in files), None)
        return {"id": r["id"], "title": r["title"], "authors": r["authors"] or "Unknown", "tags": r["tags"] or "",
                "series": r["series"] or "", "description": clip(lib.html_to_text(r["description"] or ""), 300),
                "formats": sorted(files), "format": fmt, "path": r["path"], "file": files.get(fmt) if fmt else None}

    def book(self, book_id: int) -> dict | None:
        with self._db() as db:
            r = db.execute(self.BOOK_SQL + " WHERE b.id = ?", (book_id,)).fetchone()
        return self._book(r) if r else None

    def search(self, query: str, limit: int = 8) -> list[dict]:
        with self._db() as db:
            rows = db.execute(self.BOOK_SQL).fetchall()
        return lib.rank([self._book(r) for r in rows], query, limit)

    def wander(self, rng: random.Random, limit: int = 8) -> tuple[str, list[dict]]:
        """A few books from one or two shelves (tags), or anywhere if nothing is tagged."""
        with self._db() as db:
            tags = [r[0] for r in db.execute("SELECT name FROM tags")]
            rows = db.execute(self.BOOK_SQL).fetchall()
        books = [self._book(r) for r in rows]
        if tags and rng.random() < 0.7:
            tag = rng.choice(tags)
            shelf = [b for b in books if tag in b["tags"].split(", ")]
            if shelf:
                return f"the {tag} shelf", rng.sample(shelf, min(limit, len(shelf)))
        return "the shelves", rng.sample(books, min(limit, len(books)))

    def overview(self) -> str:
        """A line about what's on the shelves (for describing the place)."""
        with self._db() as db:
            n = db.execute("SELECT COUNT(*) FROM books").fetchone()[0]
            tags = [r[0] for r in db.execute(
                "SELECT t.name FROM tags t JOIN books_tags_link l ON l.tag = t.id GROUP BY t.id ORDER BY COUNT(*) DESC LIMIT 6")]
            titles = [r[0] for r in db.execute("SELECT title FROM books ORDER BY random() LIMIT 8")]
        return (f"about {n} books" + (f"; shelves include {', '.join(tags)}" if tags else "")
                + f"; some titles: {'; '.join(titles)}")

    def extract(self, b: dict, section: int, offset: int, max_chars: int) -> dict:
        """The next stretch of text from (section, offset). Blocking: call via asyncio.to_thread."""
        return lib.extract_file(os.path.join(self.path, b["path"], f"{b['file']}.{b['format'].lower()}"),
                                b["format"], section, offset, max_chars)
