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
    for bad in (["moon"], "books", ["books", "books"]):
        with pytest.raises(M.Refused) as e:
            M.check_manifest(rule(hooks=["on_source"], proposes=["source"], sources=bad), "world")
        assert str(e.value) == "`sources` lists the engine's sources it asks: books, weather, narrator"


def test_what_a_source_question_may_be():
    man = {"sources": ["books"]}
    assert M._source(man, {"name": "books", "op": "search", "args": {"query": "x"}}) == {"name": "books", "op": "search", "args": {"query": "x"}}
    assert M._source(man, {"name": "books", "op": "wander"}) == {"name": "books", "op": "wander", "args": {}}
    for bad in ({"name": "weather", "op": "now"}, {"name": "books"}, {"name": "books", "op": "Search"}, {"name": "books", "op": "x", "args": []},
                {"name": "books", "op": "x", "y": 1}, {"name": "books", "op": "x", "args": {"q": "x" * 16_001}}, "books"):
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
    assert [c["hook"] for c in st.module_calls(m["id"], 5)] == ["on_source:1:on_action", "on_action"]
    assert M._budget(st.module(m["id"]), NOW)["source"] == 1 and M._budget(st.module(m["id"]), NOW)["calls"] == 2
    assert (await M.use_tool(st, s, M.LocalRunner(), m, t, {"op": "fly"}, NOW))[0] == "books fly ['error']"
    assert await sources.ask("books", "fly", {}, s, 1) == {"error": "`books` does: search, wander, find, read"}


async def test_on_source_has_the_asking_hooks_rights_and_may_ask_again_three_deep(tmp_path, shelf):
    s, st, gm, agent = make(tmp_path, library_path=shelf, modules="on", module_runner="local")
    again = ("def on_action(ctx):\n    return {'source': {'name': 'books', 'op': 'wander'}, 'state': {'n': 0}}\n"
             "def on_source(ctx):\n    n = ctx['state'].get('n', 0) + 1\n"
             "    return {'source': {'name': 'books', 'op': 'wander'}, 'state': {'n': n}, 'reply': 'asked ' + str(n)}\n")
    m = live(st, rule(name="again", hooks=["on_action", "on_source"], proposes=["source", "state"], sources=["books"], tools=TOOL), again)
    text, _ = await M.use_tool(st, s, M.LocalRunner(), st.module(m["id"]), m["manifest"]["tools"][0], {}, NOW)
    assert text == "error: it may ask its sources 3 times in one go" and M.SOURCE_DEPTH == 3
    assert [c["hook"] for c in st.module_calls(m["id"], 5)] == ["on_source:3:on_action", "on_source:2:on_action", "on_source:1:on_action", "on_action"]
    assert st.module(m["id"])["state"] == {"n": 2} and M._budget(st.module(m["id"]), NOW)["source"] == 3
    r = await M.call(st, s, M.LocalRunner(), st.module(m["id"]), "on_source:1:on_tick", NOW, source={"name": "books", "op": "x", "args": {}, "answer": {}})
    assert r["refused"] == "only on_action can reply"                                  # from on_tick, no reply


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
    assert sources.get("moon") is None and not sources.available("moon")


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
    fits = {"q": "x" * (M.SOURCE_ARGS_MAX - len('{"q": ""}'))}
    assert M._size(fits) == M.SOURCE_ARGS_MAX and M._source(man, {"name": "books", "op": "x", "args": fits})["args"] == fits


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


# --- the narrator --------------------------------------------------------------------------------------------------------------------
JUDGE = {"properties": {"verdict": {"type": "string", "enum": ["good", "bad"]}, "steps": {"type": "array", "items": {
    "type": "object", "properties": {"name": {"type": "string"}, "minutes": {"type": "integer"}}, "required": ["name"]}}}, "required": ["verdict"]}


async def test_the_narrator_judges_within_the_call(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(verdict="good", steps=[{"name": "cut", "minutes": "30"}, {"minutes": 5}], extra="x"),
                                       report(verdict="maybe")])
    assert sources.available("narrator") and sources.get("narrator").ops == ("ask",)
    got = await sources.ask("narrator", "ask", {"prompt": "  Judge the kite. ", "schema": JUDGE}, s, 1)
    assert got == {"data": {"verdict": "good", "steps": [{"name": "cut", "minutes": 30}]}}
    task = gm.calls[0]["messages"][0]["content"]
    assert task.startswith("Judge the kite.") and "report" in str(gm.calls[0]["tools"])
    assert await sources.ask("narrator", "ask", {"prompt": "again", "schema": JUDGE}, s, 1) == {"data": None}      # didn't fit: none
    agent.gm = None                                                   # no narrator: no answer, and the module's plain words stand
    assert sources.available("narrator") and await sources.ask("narrator", "ask", {"prompt": "p", "schema": JUDGE}, s, 1) == {"data": None}


async def test_what_the_narrator_can_be_asked(tmp_path):
    s, st, gm, agent = make(tmp_path)
    ask = lambda **a: sources.ask("narrator", "ask", a, s, 1)  # noqa: E731
    long = "x" * (sources.Narrator.PROMPT_MAX + 1)
    for bad in ({"schema": JUDGE}, {"prompt": " ", "schema": JUDGE}, {"prompt": long, "schema": JUDGE}, {"prompt": 3, "schema": JUDGE}):
        assert await ask(**bad) == {"error": "`prompt` is the task, at most 12000 characters"}
    assert await ask(prompt="p") == {"error": "`schema` is what the answer holds: {properties, required?}"}
    assert (await ask(prompt="p", schema={"properties": {}}))["error"].startswith("`ask.schema` is {properties, required?}")
    assert (await ask(prompt="x" * sources.Narrator.PROMPT_MAX, schema=JUDGE)) == {"data": None} and gm.calls        # the longest prompt is asked


# --- tool arguments that are lists and maps ---------------------------------------------------------------------------------------
STEPS = {"type": "array", "description": "your steps, in order", "items": {"type": "object", "properties": {
    "name": {"type": "string"}, "minutes": {"type": "integer"},
    "materials": {"type": "object", "additionalProperties": {"type": "integer"}, "description": "what it uses up"}}, "required": ["name"]}}


def test_a_tool_may_take_a_list_of_steps_each_with_a_map_of_materials():
    t = M._tools([{"name": "start", "help": "start", "params": {"type": "object", "properties": {"name": {"type": "string"}, "steps": STEPS,
                                                                                              "extra": {"type": "object", "additionalProperties": {"type": "number"}}},
                                                                "required": ["steps"]}}], "world")[0]
    got, why = M.check_args(t["params"], {"steps": [{"name": "cut", "minutes": "30", "materials": {"brass wire": "2", " ": 1, "cog": "x", "n" * 41: 1}},
                                                    {"name": "join", "materials": "lots"}, {"minutes": 5}, {"name": "sand"}],
                                          "extra": {"a": 1.5, "b": "2.5"}})
    assert why == "" and got == {"steps": [{"name": "cut", "minutes": 30, "materials": {"brass wire": 2}}, {"name": "sand"}], "extra": {"a": 1.5, "b": 2.5}}
    assert M.check_args(t["params"], {"steps": [], "extra": [1]}) == ({}, "`extra` is a map of names to number values")
    many = {f"m{i}": 1 for i in range(13)}
    assert len(M.check_args(t["params"], {"steps": [{"name": "x", "materials": many}]})[0]["steps"][0]["materials"]) == M.MAP_MOST == 12
    words = {"type": "object", "additionalProperties": {"type": "string"}}
    assert M._map_ok("notes", words) and M._map_ok("notes", {**words, "description": "d" * 200})
    for bad in ({**words, "description": "d" * 201}, {**words, "x": 1}, {"type": "object", "additionalProperties": {"type": "boolean"}},
                {"type": "object", "additionalProperties": {"type": "integer", "x": 1}}, {"type": "object"}, {"type": "array", "additionalProperties": {"type": "integer"}},
                {**words, "description": 3}, "x"):
        assert not M._map_ok("notes", bad), bad
    assert not M._map_ok("Bad Name", words)
    with pytest.raises(M.Refused) as e:
        M._tools([{"name": "start", "help": "s", "params": {"type": "object", "properties": {"x": {"type": "object"}}}}], "world")
    assert str(e.value).endswith("a list of small objects or of strings, or a map of names to values")


def test_a_tool_may_take_a_list_of_short_strings():
    drop = {"type": "array", "items": {"type": "string"}, "description": "names of steps to drop"}
    t = M._tools([{"name": "revise", "help": "r", "params": {"type": "object", "properties": {"drop": drop}, "required": []}}], "world")[0]
    got, why = M.check_args(t["params"], {"drop": ["  cut   the  wheels ", "", "   ", 3, None, "x" * 300] + [f"s{i}" for i in range(12)]})
    assert why == "" and got["drop"] == ["cut the wheels", "x" * M.LIST_STRING_MAX] + [f"s{i}" for i in range(6)]       # twelve looked at
    assert M.check_args(t["params"], {"drop": "cut"}) == ({}, "`drop` is a list")
    assert M._strings_ok("drop", drop) and M._strings_ok("drop", {"type": "array", "items": {"type": "string"}})
    assert M._strings_ok("drop", {**drop, "description": "d" * M.TEXT_MAX})
    for bad in ({**drop, "description": "d" * (M.TEXT_MAX + 1)}, {**drop, "x": 1}, {**drop, "items": {"type": "integer"}},
                {**drop, "items": {"type": "string", "x": 1}}, {**drop, "type": "object"}, {**drop, "description": 3}, "x", {"type": "array"}):
        assert not M._strings_ok("drop", bad), bad
    assert not M._strings_ok("Bad Name", drop)


def test_a_question_whose_answer_has_an_answer_that_doesnt_fit_is_refused():
    assert M._ask({"prompt": "p", "schema": {"properties": {"ids": {"type": "array", "items": {"type": "string"}}}, "required": ["ids"]}})["schema"]
    with pytest.raises(M.Refused, match="`ask.schema` is"):
        M._ask({"prompt": "p", "schema": {"properties": {"ok": {"type": "string"}, "bad": {"type": "date"}}, "required": ["ok"]}})
