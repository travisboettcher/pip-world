"""Sources (docs/DESIGN-world-packs.md, "Real-world links are sources"): the engine's adapters to the world outside, which modules may
ask but never reach themselves (they have no I/O). A module names the sources it uses in its manifest (`sources`), a hook asks one with
`{"source": {"name", "op", "args"}}`, and the engine runs it and hands the answer straight back to the module's `on_source`.

A source is trusted engine code the owner configures, like a channel. `books` is the owner's library (library.py: Calibre or a folder of
books): finding books, and reading a stretch of one, condensed by the GM so raw text never reaches a module or the agent's prompt.
`weather` is the real sky outside (weather.py: Home Assistant), the last reading, fetched at most every ten minutes. `narrator` is the
world's narrator, asked for a judgement as data within the call (a plan reviewed, a try judged).
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


class Sky:
    """The real weather outside (weather.py's provider: Home Assistant), as the last reading, fetched at most every ten minutes:
    {condition, temp, unit, daylight, next_rising, next_setting}, or None when there is no fresh reading."""
    ops = ("now",)

    def __init__(self, library, gm, settings):
        self.s = settings

    def available(self) -> bool:
        from . import weather
        src = weather.provider(self.s) if self.s and self.s.weather else None
        return bool(src and src.ready)

    async def now(self, args: dict, seed: int) -> dict:
        import time
        from . import weather
        state = _wired["agent"].state
        now = time.time()
        await weather.refresh(state, self.s, now)
        w = weather.current(state, now)
        return {"reading": None if not w else {"condition": w.condition, "temp": w.temp, "unit": w.unit, "daylight": w.above_horizon,
                                               "next_rising": w.next_rising, "next_setting": w.next_setting}}


class Narrator:
    """The world's narrator (the GM), asked for a judgement as data within the call: {prompt, schema} -> {data}, checked against the
    schema as a structured ask's answer is (none if what came back didn't fit, or the day's tokens are spent). The engine adds the world's
    voice (the narrator's system prompt); the module writes the task."""
    ops = ("ask",)
    PROMPT_MAX = 12_000

    def __init__(self, library, gm, settings):
        self.gm, self.s = gm, settings

    def available(self) -> bool:
        return self.gm is not None

    async def ask(self, args: dict, seed: int) -> dict:
        from . import modules
        prompt = args.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > self.PROMPT_MAX:
            return {"error": f"`prompt` is the task, at most {self.PROMPT_MAX} characters"}
        if args.get("schema") is None:
            return {"error": "`schema` is what the answer holds: {properties, required?}"}
        try:
            a = modules._ask({"prompt": "the task", "schema": args["schema"]})
        except modules.Refused as e:
            return {"error": str(e)}
        got = await modules._answered(_wired["agent"].state, self.s, self.gm, {**a, "prompt": prompt.strip()})
        return {"data": got["data"]}


KINDS = {"books": Books, "weather": Sky, "narrator": Narrator}
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
