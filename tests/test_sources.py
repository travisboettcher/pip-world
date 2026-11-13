"""Sources (docs/DESIGN-world-packs.md, phase 5d): the engine's adapters a module may ask (sources.py), the `sources` manifest field, the
`source` proposal and the `on_source` hook that hands the answer back within the same call."""
import pytest

from app import modules as M
from app import sources
from tests.test_library import calibre
from tests.test_modules import NOW, live, rule
from tests.test_projects import make, report

ASKS = ("def on_action(ctx):\n    return {'source': {'name': 'books', 'op': ctx['args'].get('op', 'search'), 'args': {'query': 'bees'}}, 'log': 'asked'}\n"
        "def on_source(ctx):\n    s = ctx['source']\n"
        "    return {'reply': s['name'] + ' ' + s['op'] + ' ' + repr(sorted(s['answer'])), 'state': {'via': ctx.get('tool')}}\n")
TOOL = [{"name": "look_up", "help": "look it up", "params": {"type": "object", "properties": {"op": {"type": "string"}}, "required": []}}]


def asker(st, **kw):
    return live(st, rule(name="asker", hooks=["on_action", "on_source"], proposes=["source", "log", "state"], sources=["books"], tools=TOOL, **kw), ASKS)


@pytest.fixture
def shelf(tmp_path):
    return calibre(tmp_path / "calibre")


def test_a_manifest_names_its_sources_with_the_proposal_and_the_hook():
    ok = rule(hooks=["on_source"], proposes=["source"], sources=["books"])
    assert M.check_manifest(ok, "world")["sources"] == ["books"] and "sources" not in M.check_manifest(rule(), "world")
    why = "`sources`, the `source` proposal and the `on_source` hook go together: say which sources it asks"
    for bad in (rule(hooks=["on_source"], proposes=["source"]), rule(hooks=["on_tick"], proposes=["source"], sources=["books"]),
                rule(hooks=["on_source"], proposes=["state"], sources=["books"])):
        with pytest.raises(M.Refused) as e:
            M.check_manifest(bad, "world")
        assert str(e.value) == why
    for bad in (["weather"], "books", ["books", "books"]):
        with pytest.raises(M.Refused) as e:
            M.check_manifest(rule(hooks=["on_source"], proposes=["source"], sources=bad), "world")
        assert str(e.value) == "`sources` lists the engine's sources it asks: books"


def test_what_a_source_question_may_be():
    man = {"sources": ["books"]}
    assert M._source(man, {"name": "books", "op": "search", "args": {"query": "x"}}) == {"name": "books", "op": "search", "args": {"query": "x"}}
    assert M._source(man, {"name": "books", "op": "wander"}) == {"name": "books", "op": "wander", "args": {}}
    for bad in ({"name": "weather", "op": "now"}, {"name": "books"}, {"name": "books", "op": "Search"}, {"name": "books", "op": "x", "args": []},
                {"name": "books", "op": "x", "y": 1}, {"name": "books", "op": "x", "args": {"q": "x" * 3000}}, "books"):
        with pytest.raises(M.Refused) as e:
            M._source(man, bad)
        assert str(e.value) == "`source` is {name, op, args?}: name is one of its sources (books)", bad
    with pytest.raises(M.Refused) as e:
        M._source({}, {"name": "books", "op": "x"})
    assert str(e.value).endswith("(none)")


async def test_the_answer_comes_back_within_the_same_call(tmp_path, shelf):
    s, st, gm, agent = make(tmp_path, library_path=shelf, modules="on", module_runner="local")
    m = asker(st)
    t = m["manifest"]["tools"][0]
    text, changed = await M.use_tool(st, s, M.LocalRunner(), m, t, {}, NOW)
    assert text == "books search ['books']" and changed and st.module(m["id"])["state"] == {"via": "look_up"}
    assert [c["hook"] for c in st.module_calls(m["id"], 5)] == ["on_source:on_action", "on_action"]
    assert M._budget(st.module(m["id"]), NOW)["source"] == 1 and M._budget(st.module(m["id"]), NOW)["calls"] == 2
    assert (await M.use_tool(st, s, M.LocalRunner(), m, t, {"op": "fly"}, NOW))[0] == "books fly ['error']"
    assert await sources.ask("books", "fly", {}, s, 1) == {"error": "`books` does: search, wander, find, read"}


async def test_on_source_has_the_asking_hooks_rights_and_cant_ask_again(tmp_path, shelf):
    s, st, gm, agent = make(tmp_path, library_path=shelf, modules="on", module_runner="local")
    again = ("def on_action(ctx):\n    return {'source': {'name': 'books', 'op': 'wander'}}\n"
             "def on_source(ctx):\n    return {'source': {'name': 'books', 'op': 'wander'}, 'reply': 'twice'}\n")
    m = live(st, rule(name="again", hooks=["on_action", "on_source"], proposes=["source"], sources=["books"], tools=TOOL), again)
    text, _ = await M.use_tool(st, s, M.LocalRunner(), m, m["manifest"]["tools"][0], {}, NOW)
    assert text == "error: on_source can't ask another source"
    r = await M.call(st, s, M.LocalRunner(), m, "on_source:on_tick", NOW, source={"name": "books", "op": "x", "args": {}, "answer": {}})
    assert r["refused"] in ("only on_action can reply", "on_source can't ask another source")


async def test_a_day_of_questions_is_limited(tmp_path, shelf):
    s, st, gm, agent = make(tmp_path, library_path=shelf, modules="on", module_runner="local")
    m = asker(st)
    st.update_module(m["id"], budget={"day": M._day(NOW), "source": M.PER_DAY["source"]})
    m = st.module(m["id"])
    text, _ = await M.use_tool(st, s, M.LocalRunner(), m, m["manifest"]["tools"][0], {}, NOW)
    assert text == "error: it has asked its sources 60 times today" and M.PER_DAY["source"] == 60 and M.SHIPPED_PER_DAY["source"] == 600


async def test_without_the_source_a_modules_tools_are_not_offered_and_a_question_says_so(tmp_path):
    s, st, gm, agent = make(tmp_path, library_path=str(tmp_path / "none"), modules="on", module_runner="local")
    m = asker(st)
    assert M.tools_offered(st) == [] and not sources.available("books")
    text, _ = await M.use_tool(st, s, M.LocalRunner(), m, m["manifest"]["tools"][0], {}, NOW)
    assert text == "books search ['error']" and await sources.ask("books", "search", {}, s, 1) == {"error": "there is no books source here"}
    assert sources.get("weather") is None and not sources.available("weather")


async def test_the_books(tmp_path, shelf, monkeypatch):
    from app import library as lib
    monkeypatch.setattr(lib, "EMPTY_RUN_LIMIT", 4)
    s, st, gm, agent = make(tmp_path, [report(summary="  Bees  wake. ", quotes=["one", 2, "three", "four"])], library_path=shelf,
                            read_chars_per_minute=10)
    ask = lambda op, **a: sources.ask("books", op, a, s, 7)  # noqa: E731
    got = await ask("search", query="bees")
    assert got == {"books": [{"id": 1, "title": "The Beekeeper's Year", "authors": "Ada Comb", "tags": "Nature", "series": "",
                              "description": "All about bees.", "formats": ["EPUB"], "readable": True}]}
    assert (await ask("search", query=""))["books"] == [] and (await ask("search"))["books"] == []
    w = await ask("wander")
    assert w["shelf"] and w["books"] and w == await ask("wander")                     # the same seed, the same wander
    assert (await ask("find", book="#4"))["book"]["readable"] is False and (await ask("find", book="#9")) == {"book": None, "error": "there's no book #9 here"}
    assert (await ask("find"))["book"] is None
    r = await ask("read", id=1, section=0, offset=0, minutes=30)
    assert (r["summary"], r["quotes"], r["section"], r["offset"], r["done"], r["pictures"], r["failed"]) == ("Bees wake.", ["one"], 0, 300, False, False, False)   # the first two, text only
    assert "The bees wake at dawn." in gm.calls[0]["messages"][0]["content"]
    blank = {"summary": "", "quotes": [], "percent": 0, "done": False, "pictures": False, "failed": False, "section": 0, "offset": 0}
    for bad in ({"id": 4, "minutes": 30}, {"id": 99, "minutes": 30}, {"id": "1", "minutes": 30}, {"id": True, "minutes": 30}, {"id": 1, "minutes": 0}, {"id": 1}):
        assert await ask("read", **bad) == blank, bad
    pics = await ask("read", id=3, minutes=600)
    assert pics["pictures"] and pics["summary"] == "" and len(gm.calls) == 1
    agent.gm = None
    plain = await ask("read", id=1, section=0, offset=300, minutes=30)
    assert 0 < len(plain["summary"]) <= 300 and "bees wake" in plain["summary"] and len(gm.calls) == 1        # no narrator: the text itself, clipped


async def test_a_book_that_wont_open_says_so(tmp_path, shelf, monkeypatch):
    s, st, gm, agent = make(tmp_path, library_path=shelf)

    def broken(*a):
        raise ValueError("torn")
    monkeypatch.setattr(agent.library, "extract", broken)
    got = await sources.ask("books", "read", {"id": 1, "section": 2, "offset": 5, "minutes": 10}, s, 1)
    assert got["failed"] is True and (got["section"], got["offset"], got["summary"]) == (2, 5, "")


class StubLibrary:
    """Records what it is asked."""
    def __init__(self, text="word " * 100, pictures=False):
        self.calls, self.text, self.pictures = [], text, pictures

    def search(self, query, limit):
        self.calls.append(("search", query, limit))
        return []

    def find(self, query):
        self.calls.append(("find", query))
        return (BOOK, "") if query == "#1" else (None, "nope")

    def book(self, book_id):
        return BOOK if book_id == 1 else None

    def extract(self, b, section, offset, chars):
        self.calls.append(("extract", section, offset, chars))
        return {"text": self.text, "section": section + 1, "offset": 0, "percent": 50, "done": False, "pictures": self.pictures}


class StubGM:
    def __init__(self, said):
        self.calls, self.said = [], said

    async def read_summary(self, title, authors, text, percent):
        self.calls.append((title, authors, text, percent))
        return self.said


BOOK = {"id": 1, "title": "Tides", "authors": "Ann Moor", "tags": "", "series": "", "description": "d" * 400, "formats": ["TXT"], "format": "TXT"}


async def test_the_books_source_asks_its_library_and_narrator_exactly(tmp_path):
    from app.config import Settings
    s = Settings(read_chars_per_minute=10)
    lib, gm = StubLibrary(), StubGM({"summary": "s" * 800, "quotes": ["q" * 300, "two", "three"]})
    books = sources.Books(lib, gm, s)
    assert books.plain(BOOK)["description"] == "d" * 300 + "..." and books.plain(BOOK)["readable"] is True
    await books.search({}, 1)
    await books.find({}, 1)
    assert lib.calls == [("search", "", sources.SEARCH_MOST), ("find", "")] and sources.SEARCH_MOST == 8
    assert await books.find({"book": "#1"}, 1) == {"book": books.plain(BOOK), "error": ""}
    got = await books.read({"id": 1, "section": 2, "offset": 7, "minutes": 3}, 1)
    assert lib.calls[-1] == ("extract", 2, 7, 30) and gm.calls == [("Tides", "Ann Moor", "word " * 100, 50)]
    assert got["summary"] == "s" * 700 + "..." and got["quotes"][0] == "q" * 200 + "..." and got["quotes"][1] == "two" and len(got["quotes"]) == 2
    assert (await books.read({"id": 1, "minutes": 0.1}, 1))["section"] == 1                  # one character is still something to read
    assert (await books.read({"id": 1, "minutes": 0.01}, 1))["section"] == 0                 # none is nothing
    empty = sources.Books(StubLibrary(text=""), StubGM({"summary": "x"}), s)
    assert (await empty.read({"id": 1, "minutes": 5}, 1))["summary"] == "" and empty.gm.calls == []


def test_a_source_serves_the_wired_agent():
    class Bare:
        pass
    sources.wire(Bare())
    b = sources.get("books")
    assert (b.library, b.gm, b.s) == (None, None, None) and not sources.available("books")

    class Agent:
        library, gm, s = "lib", "gm", "settings"
    sources.wire(Agent())
    b = sources.get("books")
    assert (b.library, b.gm, b.s) == ("lib", "gm", "settings") and sources.get("books", "mine").s == "mine" and sources.available("books")
    sources.wire(None)


def test_a_moment_may_be_longer_than_a_line_and_a_question_has_a_size():
    assert M._log({"text": "x" * 1200, "kind": "read"})["text"] == "x" * 1200
    with pytest.raises(M.Refused) as e:
        M._log({"text": "x" * 1201, "kind": "read"})
    assert str(e.value) == "`log.text` is at most 1200 characters"
    man = {"sources": ["books"]}
    fits = {"q": "x" * (M.ARGS_MAX - len('{"q": ""}'))}
    assert M._size(fits) == M.ARGS_MAX and M._source(man, {"name": "books", "op": "x", "args": fits})["args"] == fits


async def test_what_comes_of_a_question_and_its_answer_together(tmp_path, shelf):
    s, st, gm, agent = make(tmp_path, library_path=shelf, modules="on", module_runner="local")
    src = ("def on_action(ctx):\n    return {'source': {'name': 'books', 'op': 'wander'}}\n"
           "def on_source(ctx):\n    if ctx['args'].get('op') == 'boom':\n        return 1 / 0\n"
           "    return {'wake': True, 'state': {'shelf': ctx['source']['answer']['shelf'], 'books': [b['id'] for b in ctx['source']['answer']['books']]}}\n")
    m = live(st, rule(name="waker", hooks=["on_action", "on_source"], proposes=["source", "wake", "state"], sources=["books"], tools=TOOL), src)
    r = await M.call(st, s, M.LocalRunner(), m, "on_action", NOW, tool="look_up", args={})
    assert r["ok"] and r["wake"] and r["changed"] and r["error"] == "" and r["reply"] == ""
    w = await sources.ask("books", "wander", {}, s, int(NOW) * 7919 + m["id"])
    assert st.module(m["id"])["state"] == {"shelf": w["shelf"], "books": [b["id"] for b in w["books"]]}       # the seed: the call's own
    m = st.module(m["id"])
    r = await M.call(st, s, M.LocalRunner(), m, "on_action", NOW, tool="look_up", args={"op": "boom"})
    assert r["ok"] is False and "ZeroDivisionError" in r["error"] and not r["wake"]
    assert M._budget(st.module(m["id"]), NOW)["source"] == 2
