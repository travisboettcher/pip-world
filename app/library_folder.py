"""The folder library provider: a plain folder of books, no catalogue software needed.

Every EPUB, PDF, text and Markdown file under the folder is a book; other book formats are listed but cannot be read. The title and
author come from an EPUB's own metadata, else from the file name; the shelf is the top-level sub-folder the book sits in. Book numbers are
derived from the file's path, so they stay the same from one run to the next (a reading position is kept against them).
"""
import hashlib
import os
import random
import re

from . import library as lib

ID_SPACE = 1_000_000
READABLE_EXT = {".epub": "EPUB", ".pdf": "PDF", ".txt": "TXT", ".md": "TXT"}
LISTED_EXT = {".mobi": "MOBI", ".azw3": "AZW3", ".fb2": "FB2", ".djvu": "DJVU", ".cbz": "CBZ"}   # books we can list but not read


def humanize(name: str) -> str:
    return " ".join(w.capitalize() for w in re.sub(r"[_\-]+", " ", name).split()) or name


@lib.register("folder")
class Folder(lib.Library):
    def __init__(self, path: str):
        self.path = path
        self._meta: dict = {}      # relative path -> (mtime, metadata): an EPUB is only opened again if it changed

    def _files(self) -> list[tuple[str, str]]:
        """(relative path, format) of every book file, sorted by path."""
        found = []
        for root, dirs, names in os.walk(self.path):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for n in sorted(names):
                ext = os.path.splitext(n)[1].lower()
                if not n.startswith(".") and (ext in READABLE_EXT or ext in LISTED_EXT):
                    found.append((os.path.relpath(os.path.join(root, n), self.path), ext))
        return sorted(found)

    def available(self) -> bool:
        return os.path.isdir(self.path) and bool(self._files())

    def _epub_meta(self, rel: str) -> dict:
        full = os.path.join(self.path, rel)
        mtime = os.path.getmtime(full)
        if rel not in self._meta or self._meta[rel][0] != mtime:
            self._meta[rel] = (mtime, lib.epub_metadata(full))
        return self._meta[rel][1]

    def all(self) -> list[dict]:
        books, taken = [], set()
        for rel, ext in self._files():
            n = int(hashlib.sha1(rel.encode()).hexdigest(), 16) % ID_SPACE + 1
            while n in taken:                      # a collision: take the next free number
                n += 1
            taken.add(n)
            meta = self._epub_meta(rel) if ext == ".epub" else {}
            fmt = READABLE_EXT.get(ext)
            shelf = rel.split(os.sep)[0] if os.sep in rel else ""
            books.append({"id": n, "title": meta.get("title") or humanize(os.path.splitext(os.path.basename(rel))[0]),
                          "authors": meta.get("authors") or "Unknown", "tags": shelf, "series": "",
                          "description": meta.get("description", ""), "formats": [fmt or LISTED_EXT[ext]], "format": fmt,
                          "path": rel})
        return books

    def book(self, book_id: int) -> dict | None:
        return next((b for b in self.all() if b["id"] == book_id), None)

    def search(self, query: str, limit: int = 8) -> list[dict]:
        return lib.rank(self.all(), query, limit)

    def wander(self, rng: random.Random, limit: int = 8) -> tuple[str, list[dict]]:
        """A few books from one or two shelves (folders), or anywhere if nothing is shelved."""
        books = self.all()
        tags = sorted({b["tags"] for b in books if b["tags"]})
        if tags and rng.random() < 0.7:
            tag = rng.choice(tags)
            shelf = [b for b in books if b["tags"] == tag]
            return f"the {tag} shelf", rng.sample(shelf, min(limit, len(shelf)))
        return "the shelves", rng.sample(books, min(limit, len(books)))

    def overview(self) -> str:
        books = self.all()
        counts: dict[str, int] = {}
        for b in books:
            if b["tags"]:
                counts[b["tags"]] = counts.get(b["tags"], 0) + 1
        tags = [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:6]]
        titles = [b["title"] for b in random.sample(books, min(8, len(books)))]
        return (f"about {len(books)} books" + (f"; shelves include {', '.join(tags)}" if tags else "")
                + f"; some titles: {'; '.join(titles)}")

    def extract(self, b: dict, section: int, offset: int, max_chars: int) -> dict:
        return lib.extract_file(os.path.join(self.path, b["path"]), b["format"], section, offset, max_chars)
