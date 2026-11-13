"""Sources (docs/DESIGN-world-packs.md, "Real-world links are sources"): the engine's adapters to the world outside, which modules may
ask but never reach themselves (they have no I/O). A module names the sources it uses in its manifest (`sources`), a hook asks one with
`{"source": {"name", "op", "args"}}`, and the engine runs it and hands the answer straight back to the module's `on_source`.

A source is trusted engine code the owner configures, like a channel. `books` is the owner's library (library.py: Calibre or a folder of
books): finding books, and reading a stretch of one, condensed by the GM so raw text never reaches a module or the agent's prompt.
"""
import asyncio
import logging
import random

from .text import clip

log = logging.getLogger("sources")
SEARCH_MOST = 8


class Books:
    """The owner's books. Each op takes plain arguments and gives plain data; a book is {id, title, authors, tags, series, description,
    formats, readable}."""
    ops = ("search", "wander", "find", "read")

    def __init__(self, library, gm, settings):
        self.library, self.gm, self.s = library, gm, settings

    def available(self) -> bool:
        return self.library is not None

    @staticmethod
    def plain(b: dict) -> dict:
        return {"id": b["id"], "title": b["title"], "authors": b["authors"], "tags": b["tags"], "series": b["series"],
                "description": clip(b["description"], 300), "formats": list(b["formats"]), "readable": bool(b["format"])}

    async def search(self, args: dict, seed: int) -> dict:
        return {"books": [self.plain(b) for b in self.library.search(str(args.get("query") or ""), SEARCH_MOST)]}

    async def wander(self, args: dict, seed: int) -> dict:
        shelf, books = self.library.wander(random.Random(seed))
        return {"shelf": shelf, "books": [self.plain(b) for b in books]}

    async def find(self, args: dict, seed: int) -> dict:
        b, err = self.library.find(args.get("book", ""))
        return {"book": self.plain(b), "error": ""} if b else {"book": None, "error": err}

    async def read(self, args: dict, seed: int) -> dict:
        """The next stretch of a book from where the module's bookmark says (`section`, `offset`), as much as `minutes` of reading
        covers, condensed: {summary, quotes, percent, done, pictures, section, offset, failed}."""
        from . import library as lib
        book_id = args.get("id")
        b = self.library.book(book_id) if isinstance(book_id, int) and not isinstance(book_id, bool) else None
        out = {"summary": "", "quotes": [], "percent": 0, "done": False, "pictures": False, "failed": False,
               "section": int(args.get("section") or 0), "offset": int(args.get("offset") or 0)}
        chars = min(lib.MAX_READ_CHARS, int(max(0.0, float(args.get("minutes") or 0)) * self.s.read_chars_per_minute))
        if not b or not b["format"] or chars <= 0:
            return out
        try:
            got = await asyncio.to_thread(self.library.extract, b, out["section"], out["offset"], chars)
        except Exception as e:                                      # a damaged file shouldn't break the world
            log.warning("reading %s failed: %s", b["title"], e)
            return {**out, "failed": True}
        out.update(section=got["section"], offset=got["offset"], percent=got["percent"], done=got["done"], pictures=got["pictures"])
        if got["text"] and not got["pictures"]:
            said = await self.gm.read_summary(b["title"], b["authors"], got["text"], got["percent"]) if self.gm else None
            out.update(summary=clip(said.get("summary"), 700) if said else clip(got["text"], 300),
                       quotes=[clip(q, 200) for q in (said.get("quotes") or [])[:2] if isinstance(q, str)] if said else [])
        return out


KINDS = {"books": Books}
_wired: dict = {"agent": None}


def wire(agent) -> None:
    """Who the sources serve: the agent, whose library and GM they use (read when asked, so a swapped GM is the one used)."""
    _wired["agent"] = agent


def get(name: str, settings=None):
    cls, agent = KINDS.get(name), _wired["agent"]
    return cls(getattr(agent, "library", None), getattr(agent, "gm", None), settings or getattr(agent, "s", None)) if cls else None


def available(name: str, settings=None) -> bool:
    src = get(name, settings)
    return bool(src and src.available())


async def ask(name: str, op: str, args: dict, settings, seed: int) -> dict:
    """Run one op of a source: its answer, or {"error": ...} if it can't be done."""
    src = get(name, settings)
    if not src or not src.available():
        return {"error": f"there is no {name} source here"}
    if op not in src.ops:
        return {"error": f"`{name}` does: {', '.join(src.ops)}"}
    return await getattr(src, op)(args, seed)
