"""The library: a read-only window onto a collection of books (see DESIGN-library.md, DESIGN-extract.md).

Where the catalogue comes from is a *provider*, registered by name: `library_calibre.py` reads a Calibre library's metadata.db,
`library_folder.py` reads a plain folder of books. This module is everything that does not care which: the `Library` base (finding a
book), ranking a search, and the format readers (EPUB: zipfile + HTML-to-text over the spine; PDF: pypdf, page by page; plain text in
sections). The `books` source (sources.py) is how the world reaches it; reading itself is the `reading` module's. A reading position is (section, offset): a section is a PDF page, an EPUB chapter or a
stretch of a text file. Raw text never reaches Pip's prompt - a reading session's stretch of text is condensed by the GM.
Pick the provider with `LIBRARY_PROVIDER` (`auto` tries Calibre, then a folder). To add one, write a module that registers a
`Library` subclass and import it at the bottom.
"""
import logging
import math
import os
import posixpath
import random
import re
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser

from .text import clip

log = logging.getLogger("library")
READABLE = ("EPUB", "PDF", "TXT")  # in order of preference
TEXT_SECTION_CHARS = 3000  # a plain text file is read in sections of about this size, so progress moves
MAX_READ_CHARS = 24000
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


# --- providers --------------------------------------------------------------------------------------------------------
PROVIDERS: dict = {}     # name -> Library subclass, built from the library's path


def register(name: str):
    def add(cls):
        PROVIDERS[name] = cls
        return cls
    return add


def open_library(settings):
    """The configured library, or None if there isn't one (`auto`: a Calibre library if the path holds one, else a folder of books)."""
    name = settings.library_provider
    for cls in ([PROVIDERS[n] for n in ("calibre", "folder") if n in PROVIDERS] if name == "auto" else [PROVIDERS[name]] if name in PROVIDERS else []):
        found = cls(settings.library_path)
        if found.available():
            return found
    return None


def rank(books: list[dict], query, limit: int = 8) -> list[dict]:
    """The books that match a query: a hit in the title counts three, anywhere else (author, shelf, series, blurb) one; ties by id."""
    words = [w for w in re.findall(r"\w+", str(query).lower()) if len(w) > 1][:6]
    if not words:
        return []
    scored = []
    for b in books:
        title, rest = b["title"].lower(), f"{b['authors']} {b['tags']} {b['series']} {b['description']}".lower()
        score = sum(3 * (w in title) + (w in rest) for w in words)
        if score:
            scored.append((score, b["id"], b))
    return [b for _, _, b in sorted(scored, key=lambda x: (-x[0], x[1]))[:limit]]


class Library:
    """What a provider offers. Books are dicts: id, title, authors, tags (comma-separated shelves), series, description, formats,
    and format (the one that can be read, or None). Subclasses give `available`, `book`, `search`, `wander`, `overview`, `extract`."""

    def available(self) -> bool:
        raise NotImplementedError

    def book(self, book_id: int) -> dict | None:
        raise NotImplementedError

    def search(self, query: str, limit: int = 8) -> list[dict]:
        raise NotImplementedError

    def wander(self, rng: random.Random, limit: int = 8) -> tuple[str, list[dict]]:
        raise NotImplementedError

    def overview(self) -> str:
        raise NotImplementedError

    def extract(self, b: dict, section: int, offset: int, max_chars: int) -> dict:
        raise NotImplementedError

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
            return None, f"you can't find a book like {query!r} (try browse)"
        return None, "which one? " + "; ".join(f"#{b['id']} {b['title']}" for b in hits)


# --- reading the files ------------------------------------------------------------------------------------------------
def epub_chapters(z: zipfile.ZipFile) -> list[str]:
    ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
    opf_path = ET.fromstring(z.read("META-INF/container.xml")).find(".//c:rootfile", ns).get("full-path")
    opf = ET.fromstring(z.read(opf_path))
    base = posixpath.dirname(opf_path)
    items = {i.get("id"): i.get("href") for i in opf.iter("{http://www.idpf.org/2007/opf}item")}
    return [posixpath.normpath(posixpath.join(base, items[r.get("idref")]))
            for r in opf.iter("{http://www.idpf.org/2007/opf}itemref") if r.get("idref") in items]


def epub_metadata(path: str) -> dict:
    """The title, authors and blurb an EPUB's package file carries (only what it has); {} for anything that is not a readable EPUB."""
    try:
        with zipfile.ZipFile(path) as z:
            ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container", "dc": "http://purl.org/dc/elements/1.1/"}
            opf_path = ET.fromstring(z.read("META-INF/container.xml")).find(".//c:rootfile", ns).get("full-path")
            opf = ET.fromstring(z.read(opf_path))
    except Exception:
        return {}
    text = lambda tag: [e.text.strip() for e in opf.iter(f"{{{ns['dc']}}}{tag}") if e.text and e.text.strip()]  # noqa: E731
    out = {}
    if text("title"):
        out["title"] = clip(text("title")[0], 300)
    if text("creator"):
        out["authors"] = clip(" & ".join(text("creator")), 300)
    if text("description"):
        out["description"] = clip(html_to_text(text("description")[0]), 300)  # strip the markup first, then clip
    return out


def extract_file(path: str, fmt: str, section: int, offset: int, max_chars: int) -> dict:
    """The next stretch of text from (section, offset) of a book file. Blocking: call via asyncio.to_thread."""
    if fmt == "EPUB":
        z = zipfile.ZipFile(path)
        chapters = epub_chapters(z)
        total = len(chapters)
        get = lambda i: html_to_text(z.read(chapters[i]).decode("utf-8", "replace"))  # noqa: E731
    elif fmt == "TXT":
        with open(path, encoding="utf-8", errors="replace") as f:
            whole = f.read()
        total = max(1, math.ceil(len(whole) / TEXT_SECTION_CHARS))
        get = lambda i: whole[i * TEXT_SECTION_CHARS:(i + 1) * TEXT_SECTION_CHARS]  # noqa: E731
    else:
        from pypdf import PdfReader  # imported lazily: only reading needs it
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        reader = PdfReader(path)
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




from . import library_calibre, library_folder  # noqa: E402,F401  (register the "calibre" and "folder" providers)
