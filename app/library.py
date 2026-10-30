"""The library: a read-only window onto the homelab's Calibre library (the folder calibre-web serves).

The catalogue comes from Calibre's metadata.db (opened read-only); book text from EPUB (zipfile + HTML-to-text over
the spine) or PDF (pypdf, page by page). A reading position is (section, offset): a section is a PDF page or an
EPUB chapter. Raw text never reaches Pip's prompt - a reading session's stretch of text is condensed by the GM.
See DESIGN-library.md.
"""
import asyncio
import logging
import os
import posixpath
import random
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser

from .text import clip

log = logging.getLogger("library")
READABLE = ("EPUB", "PDF")  # in order of preference
MAX_READ_CHARS = 24000
READ_MINUTES = (15, 90)
EMPTY_RUN_LIMIT = 40  # this many textless sections in a row: treat the rest as pictures
BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote", "section"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html or "")
    text = "".join(p.parts)
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t\r\f\v]+", " ", text)).strip()


class Library:
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
        fmt = next((f for f in READABLE if f in files), None)
        return {"id": r["id"], "title": r["title"], "authors": r["authors"] or "Unknown", "tags": r["tags"] or "",
                "series": r["series"] or "", "description": clip(html_to_text(r["description"] or ""), 300),
                "formats": sorted(files), "format": fmt, "path": r["path"], "file": files.get(fmt) if fmt else None}

    def book(self, book_id: int) -> dict | None:
        with self._db() as db:
            r = db.execute(self.BOOK_SQL + " WHERE b.id = ?", (book_id,)).fetchone()
        return self._book(r) if r else None

    def search(self, query: str, limit: int = 8) -> list[dict]:
        words = [w for w in re.findall(r"\w+", str(query).lower()) if len(w) > 1][:6]
        if not words:
            return []
        with self._db() as db:
            rows = db.execute(self.BOOK_SQL).fetchall()
        scored = []
        for r in rows:
            b = self._book(r)
            title, rest = b["title"].lower(), f"{b['authors']} {b['tags']} {b['series']} {b['description']}".lower()
            score = sum(3 * (w in title) + (w in rest) for w in words)
            if score:
                scored.append((score, b["id"], b))
        return [b for _, _, b in sorted(scored, key=lambda x: (-x[0], x[1]))[:limit]]

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

    def find(self, query) -> tuple[dict | None, str]:
        q = str(query).strip().lstrip("#")
        if q.isdigit():
            b = self.book(int(q))
            return (b, "") if b else (None, f"there's no book #{q} here")
        hits = self.search(q, limit=3)
        exact = [b for b in hits if b["title"].lower() == q.lower()]
        if exact or len(hits) == 1:
            return (exact or hits)[0], ""
        if not hits:
            return None, f"you can't find a book like {query!r} (try browse_library)"
        return None, "which one? " + "; ".join(f"#{b['id']} {b['title']}" for b in hits)

    def overview(self) -> str:
        """A line about what's on the shelves (for describing the place)."""
        with self._db() as db:
            n = db.execute("SELECT COUNT(*) FROM books").fetchone()[0]
            tags = [r[0] for r in db.execute(
                "SELECT t.name FROM tags t JOIN books_tags_link l ON l.tag = t.id GROUP BY t.id ORDER BY COUNT(*) DESC LIMIT 6")]
            titles = [r[0] for r in db.execute("SELECT title FROM books ORDER BY random() LIMIT 8")]
        return (f"about {n} books" + (f"; shelves include {', '.join(tags)}" if tags else "")
                + f"; some titles: {'; '.join(titles)}")

    # --- text -----------------------------------------------------------------------
    def _file(self, b: dict) -> str:
        return os.path.join(self.path, b["path"], f"{b['file']}.{b['format'].lower()}")

    def _epub_chapters(self, z: zipfile.ZipFile) -> list[str]:
        ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container", "o": "http://www.idpf.org/2007/opf"}
        opf_path = ET.fromstring(z.read("META-INF/container.xml")).find(".//c:rootfile", ns).get("full-path")
        opf = ET.fromstring(z.read(opf_path))
        base = posixpath.dirname(opf_path)
        items = {i.get("id"): i.get("href") for i in opf.iter("{http://www.idpf.org/2007/opf}item")}
        return [posixpath.normpath(posixpath.join(base, items[r.get("idref")]))
                for r in opf.iter("{http://www.idpf.org/2007/opf}itemref") if r.get("idref") in items]

    def extract(self, b: dict, section: int, offset: int, max_chars: int) -> dict:
        """The next stretch of text from (section, offset). Blocking: call via asyncio.to_thread."""
        if b["format"] == "EPUB":
            z = zipfile.ZipFile(self._file(b))
            chapters = self._epub_chapters(z)
            total = len(chapters)
            get = lambda i: html_to_text(z.read(chapters[i]).decode("utf-8", "replace"))  # noqa: E731
        else:
            from pypdf import PdfReader  # imported lazily: only reading needs it
            logging.getLogger("pypdf").setLevel(logging.ERROR)
            reader = PdfReader(self._file(b))
            total = len(reader.pages)
            get = lambda i: reader.pages[i].extract_text() or ""  # noqa: E731
        parts, got, empty_run = [], 0, 0
        while section < total and got < max_chars:
            text = re.sub(r"[ \t]+", " ", get(section)).strip()
            chunk = text[offset:offset + (max_chars - got)]
            if chunk.strip():
                parts.append(chunk)
                got += len(chunk)
                empty_run = 0
            else:
                empty_run += 1
                if empty_run >= EMPTY_RUN_LIMIT and not parts:
                    break
            if offset + len(chunk) < len(text):
                offset += len(chunk)
            else:
                section, offset = section + 1, 0
        done = section >= total
        return {"text": "\n".join(parts), "section": section, "offset": offset, "total": total,
                "percent": 100 if done else int(100 * section / max(1, total)), "done": done,
                "pictures": not parts and empty_run >= EMPTY_RUN_LIMIT}


def line(b: dict, state=None) -> str:
    mark = state.bookmark(b["id"]) if state else None
    status = ("can't be read" if not b["format"] else
              "finished" if mark and mark["finished"] else
              f"you're {mark['percent']}% in" if mark and mark["sessions"] else "")
    return (f"#{b['id']} {b['title']} - {b['authors']}" + (f" [{b['tags']}]" if b["tags"] else "")
            + (f" ({status})" if status else "") + (f": {clip(b['description'], 140)}" if b["description"] else ""))


def start_reading(state, settings, b: dict, minutes: int) -> str:
    mark = state.bookmark(b["id"])
    state.set_bookmark(b["id"], b["title"])
    state.start_session(b["id"], 0, minutes, time.time() + minutes * 60 / settings.work_speed, kind="read",
                        target=b["title"])
    state.update_agent(activity="reading", description=f"reading {b['title']}")
    where = f"picking up where you left off, {mark['percent']}% in" if mark and mark["sessions"] else "from the start"
    return f"you settle in with {b['title']} by {b['authors']} ({where}) for {minutes} min"


async def finish_reading(state, settings, gm, library, interrupted: bool = False, now: float | None = None) -> dict | None:
    """End a reading session: pull the next stretch of text from the bookmark and condense it."""
    sess = state.session()
    if not sess or sess["kind"] != "read":
        return None
    now = now or time.time()
    state.end_session()
    minutes = sess["minutes"]
    if interrupted:
        minutes = min(minutes, max(0.0, now - sess["started_at"]) * settings.work_speed / 60)
    b = library.book(sess["project_id"]) if library else None
    mark = state.bookmark(sess["project_id"]) or {"section": 0, "offset": 0, "sessions": 0}
    data = {"book_id": sess["project_id"], "title": sess["target"], "minutes": round(minutes),
            "interrupted": interrupted, "summary": "", "quotes": [], "percent": mark.get("percent", 0),
            "finished": False}
    chars = min(MAX_READ_CHARS, int(minutes * settings.read_chars_per_minute))
    got = None
    if b and b["format"] and chars > 0:
        try:
            got = await asyncio.to_thread(library.extract, b, mark["section"], mark["offset"], chars)
        except Exception as e:  # a damaged file shouldn't break the world
            log.warning("reading %s failed: %s", b["title"], e)
            data["summary"] = "The pages wouldn't come apart properly; you couldn't make sense of this one."
    if got and got["pictures"]:
        data["summary"] = "These pages are almost all pictures; there's hardly any text to read here."
        state.set_bookmark(b["id"], b["title"], unreadable=1, last_read=now, sessions=mark["sessions"] + 1)
    elif got:
        out = await gm.read_summary(b["title"], b["authors"], got["text"], got["percent"]) if gm and got["text"] else None
        data.update(summary=clip(out.get("summary"), 700) if out else clip(got["text"], 300),
                    quotes=[clip(q, 200) for q in (out.get("quotes") or [])[:2] if isinstance(q, str)] if out else [],
                    percent=got["percent"], finished=got["done"])
        state.set_bookmark(b["id"], b["title"], section=got["section"], offset=got["offset"], percent=got["percent"],
                           finished=int(got["done"]), sessions=mark["sessions"] + 1, last_read=now)
    if not data["summary"]:
        data["summary"] = "You'd barely started before you put it down."
    if state.agent()["activity"] == "reading":
        state.update_agent(activity="idle", description=f"just read some of {sess['target']}")
    state.log("reading", **data)
    return data


def perception(state, library) -> list[str]:
    if state.agent()["location"] != "library" or not library:
        return []
    lines = ["At the library you can browse_library (search, or wander the shelves) and read books."]
    reading = state.bookmarks(include_finished=False)[:5]
    if reading:
        lines.append("Books you're partway through:")
        lines += [f"- #{m['book_id']} {m['title']} ({m['percent']}% in)" for m in reading]
    return lines
