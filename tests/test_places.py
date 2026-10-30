import time
from datetime import datetime

import pytest

from app import capabilities as C
from app import places as P
from app import tools as T
from app.config import Settings
from app.llm.base import ToolCall
from tests.test_projects import make
from tests.test_scoping import FakeLibrary


def neighbor(st, s):
    return st.add_character("Marigold", "neighbor", "a beekeeper", "persona", 60, "", 0)


def test_the_registry_lists_home_the_library_and_neighbors_as_records(tmp_path):
    s, st, *_ = make(tmp_path)
    assert list(P.registry(st, s, None)) == [P.HOME]                         # no library mounted, no neighbor
    neighbor(st, s)
    reg = P.registry(st, s, FakeLibrary())
    assert list(reg) == ["workshop", "library", "Marigold's home"]
    assert reg["library"].offers == ("browse", "read") and set(reg["library"].verbs) == {"browse", "read"}
    assert reg["Marigold's home"].offers == ("talk",) and reg["Marigold's home"].scope == "neighbor"
    assert reg["library"].label == "the library" and reg["workshop"].scope == "home"
    assert P.available(st, FakeLibrary())["library"].startswith("a library a short walk away")


def test_the_directory_says_where_to_go_and_what_each_place_is_for(tmp_path):
    s, st, *_ = make(tmp_path)
    neighbor(st, s)
    lines = P.directory(st, s, FakeLibrary())
    assert lines[0] == "Places you can go (go_to):"
    assert lines[1].startswith("- library, 10 min - a library a short walk away") and lines[1].endswith("[browse, read]")
    assert lines[2].startswith("- Marigold's home, 10 min - where your neighbor Marigold lives") and lines[2].endswith("[talk]")
    st.update_agent(location="library")
    away = P.directory(st, s, FakeLibrary())
    assert away[1] == "- workshop, 10 min - your home: your workshop and garden [projects, garden, sleep]"   # the way home
    assert not any(l.startswith("- library") for l in away)                                                  # not where Pip is


def test_open_hours_and_daylight(tmp_path):
    s = Settings(bedtime_hour=22, wake_hour=6)
    at = lambda h: datetime(2026, 11, 2, h, 30).timestamp()  # noqa: E731
    always, woods, market = P.Place("a", "", 10), P.Place("woods", "", 8, daylight_only=True), P.Place("market", "", 20, hours=(8, 18))
    assert all(P.open_now(always, s, at(h)) for h in (3, 12, 23))
    assert [P.open_now(woods, s, at(h)) for h in (5, 6, 14, 22)] == [False, True, True, False]
    assert [P.open_now(market, s, at(h)) for h in (7, 8, 17, 18)] == [False, True, True, False]
    overnight = P.Place("pub", "", 5, hours=(20, 2))
    assert [P.open_now(overnight, s, at(h)) for h in (19, 21, 1, 3)] == [False, True, True, False]


def test_a_closed_place_is_marked_in_the_directory(tmp_path, monkeypatch):
    s, st, *_ = make(tmp_path)
    h = datetime.now().hour
    s.bedtime_hour, s.wake_hour = h, (h + 8) % 24                            # it is night right now
    woods = P.Place("woods", "a patch of woods", 8, offers=("gather",), daylight_only=True)
    monkeypatch.setattr(P, "registry", lambda *a: {P.HOME: P.Place(P.HOME, "home", 10), "woods": woods})
    assert P.directory(st, s, None)[1] == "- woods, 8 min, closed now - a patch of woods [gather]"
    s.bedtime_hour, s.wake_hour = (h + 3) % 24, (h + 8) % 24                 # and now it is daytime
    assert P.directory(st, s, None)[1] == "- woods, 8 min - a patch of woods [gather]"


def test_a_place_can_describe_a_verb_its_own_way(tmp_path):
    spec_tools = {n: T.REGISTRY[n] for n in ("browse", "read", "say")}
    plain = {sp.name: sp.description for sp in T.specs_for(spec_tools, "library")}
    assert plain["browse"].startswith("Look through what is on offer where you are.")
    place = P.Place("library", "x", 10, verbs={"browse": ("short", "At the library: search the catalogue.")})
    over = {sp.name: sp.description for sp in T.specs_for(spec_tools, "library", place)}
    assert over["browse"] == "At the library: search the catalogue." and over["read"] == plain["read"]
    assert T.REGISTRY["browse"][0].description == plain["browse"]             # the registered spec is not mutated


@pytest.mark.asyncio
async def test_the_old_tool_name_still_works_and_history_carries_over(tmp_path):
    s = Settings(tools=["say", "browse_library", "browse", "read"], library_path="/nonexistent")
    assert list(T.enabled_tools(s)) == ["say"]                               # no library: neither name is offered
    s, st, gm, agent = make(tmp_path)
    agent.tools["browse"] = T.REGISTRY["browse"]
    st.update_agent(location="library")
    class Lib:                                                              # an old-name call from before the rename
        def available(self): return True
        def search(self, q): return []
        def wander(self, rng): return "a shelf", []
    agent.ctx.library = Lib()
    out = await agent._run_tool(ToolCall("1", "browse_library", {"query": "bees"}), 0)
    assert "nothing on the shelves matches" in out["content"]
    st.log("tool", tool="browse_library", args={}, result="Wandering along a shelf, you see:\n- x")
    st.log("tool", tool="browse", args={}, result="Wandering along a shelf, you see:\n- y")
    assert {r["key"] for r in st.db.execute("SELECT key FROM facets")} >= {"tool:browse"} and \
        "tool:browse_library" not in {r["key"] for r in st.db.execute("SELECT key FROM facets")}
    got = C.collect([e for e in st.events(10)])["tool"]
    assert got["browse"]["tries"] >= 2 and "browse_library" not in got
