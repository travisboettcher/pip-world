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
from tests.test_outreach import daytime


def neighbor(st, s):
    return st.add_character("Marigold", "neighbor", "a beekeeper", "persona", 60, "", 0)


def test_the_registry_lists_home_the_library_and_neighbors_as_records(tmp_path):
    s, st, *_ = make(tmp_path, wild_places=[])
    assert list(P.registry(st, s, None)) == [P.HOME]                         # no library mounted, no neighbor
    neighbor(st, s)
    reg = P.registry(st, s, FakeLibrary())
    assert list(reg) == ["workshop", "library", "Marigold's home"]
    assert reg["library"].offers == ("browse", "read") and set(reg["library"].verbs) == {"browse", "read"}
    assert reg["Marigold's home"].offers == ("talk",) and reg["Marigold's home"].scope == "neighbor"
    assert reg["library"].label == "the library" and reg["workshop"].scope == "home"
    assert P.available(st, FakeLibrary())["library"].startswith("a library a short walk away")


def test_the_directory_says_where_to_go_and_what_each_place_is_for(tmp_path):
    s, st, *_ = make(tmp_path, wild_places=[])
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
    spec_tools = {n: T.REGISTRY[n] for n in ("browse", "say")}
    plain = {sp.name: sp.description for sp in T.specs_for(spec_tools, "junkyard")}
    assert plain["browse"].startswith("Look over what is lying about where you are")
    place = P.Place("junkyard", "x", 10, verbs={"browse": ("short", "Pick over the heaps.")})
    over = {sp.name: sp.description for sp in T.specs_for(spec_tools, "junkyard", place)}
    assert over["browse"] == "Pick over the heaps." and over["say"] == plain["say"]
    assert T.REGISTRY["browse"][0].description == plain["browse"]             # the registered spec is not mutated


@pytest.mark.asyncio
async def test_the_old_tool_name_still_works_and_history_carries_over(tmp_path):
    s = Settings(tools=["say", "browse_library", "browse", "read"], library_path="/nonexistent")
    assert list(T.enabled_tools(s)) == ["say", "browse"]                     # the old name is the new one; reading is a module's
    s, st, gm, agent = make(tmp_path)
    from tests.test_gather import daytime
    daytime(s)
    agent.tools["browse"] = T.REGISTRY["browse"]
    st.update_agent(location="junkyard")
    out = await agent._run_tool(ToolCall("1", "browse_library", {}), 0)       # an old-name call from before the rename
    assert out["content"].startswith("Looking over the junkyard")
    st.log("tool", tool="browse_library", args={}, result="Wandering along a shelf, you see:\n- x")
    st.log("tool", tool="browse", args={}, result="Wandering along a shelf, you see:\n- y")
    assert {r["key"] for r in st.db.execute("SELECT key FROM facets")} >= {"tool:browse"} and \
        "tool:browse_library" not in {r["key"] for r in st.db.execute("SELECT key FROM facets")}
    got = C.collect([e for e in st.events(10)])["tool"]
    assert got["browse"]["tries"] >= 2 and "browse_library" not in got


class ShelvedLibrary(FakeLibrary):
    def overview(self):
        return "shelves of old books"


def _walk_to(st, place):
    st.start_session(0, 0, 10, time.time() - 1, kind="walk", target=place)


@pytest.mark.asyncio
async def test_arriving_somewhere_new_describes_it_from_what_is_there(tmp_path):
    from tests.test_projects import report
    s, st, gm, agent = make(tmp_path, [report(text="Tall trees."), report(text="Dusty stacks."),
                                       report(text="Odd corner.")])
    _walk_to(st, "woods")
    st.update_agent(activity="walking")
    data = await P.arrive(st, s, agent.gm, ShelvedLibrary())  # a library is around, but this is the woods
    assert gm.calls[0]["messages"][0]["content"].startswith(
        "Pip has just arrived at the woods for the first time. What's actually there: a patch of woods past the garden")
    assert data == {"place": "woods", "label": "the woods", "first_time": True, "description": "Tall trees."}
    a = st.agent()
    assert a["location"] == "woods" and a["activity"] == "idle" and a["description"] == "just arrived at the woods"
    assert abs(float(st.meta("arrived_at")) - time.time()) < 5
    _walk_to(st, "library")
    await P.arrive(st, s, agent.gm, ShelvedLibrary())
    assert "What's actually there: shelves of old books." in gm.calls[1]["messages"][0]["content"]
    s.wild_places = []
    _walk_to(st, "quarry")  # nowhere the registry knows (any more): nothing to go on
    await P.arrive(st, s, agent.gm, None)
    assert gm.calls[2]["messages"][0]["content"].startswith(
        "Pip has just arrived at the quarry for the first time. Describe the place as Pip finds it")


@pytest.mark.asyncio
async def test_arriving_without_a_gm_and_getting_home(tmp_path):
    s, st, gm, agent = make(tmp_path)
    daytime(s)  # the woods are daylight-only
    _walk_to(st, "woods")
    data = await P.arrive(st, s, None, None)
    assert data["description"] == "" and st.meta("place:woods") == ""
    assert P.perception(st, s, None)[0] == "You are at: the woods"
    _walk_to(st, P.HOME)
    assert (await P.arrive(st, s, None, None))["first_time"] is False
    a = st.agent()
    assert a["description"] == "just got home" and a["activity"] == "idle"
    assert P.perception(st, s, None)[0] == "You are at: home (workshop)"


@pytest.mark.asyncio
async def test_arrive_only_ends_a_walk(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.start_session(1, 0, 10, time.time() - 1, kind="work")
    assert await P.arrive(st, s, None, None) is None
    assert st.session()["kind"] == "work" and st.agent()["location"] == P.HOME


def test_perception_needs_somewhere_else_to_go(tmp_path):
    s, st, *_ = make(tmp_path, wild_places=[])
    assert P.perception(st, s, None) == []  # home is all there is
    neighbor(st, s)
    lines = P.perception(st, s, None)  # home and one neighbor
    assert lines[0] == "You are at: home (workshop)" and lines[1] == "Places you can go (go_to):"
    assert any(line.startswith("- library, 10 min") for line in P.perception(st, s, FakeLibrary()))


@pytest.mark.asyncio
async def test_a_place_no_longer_offered_is_described_without_hints(tmp_path):
    s, st, gm, agent = make(tmp_path, wild_places=[])
    _walk_to(st, "woods")  # the woods were taken off the map while Pip was on the way
    await P.arrive(st, s, agent.gm, None)
    assert gm.calls[0]["messages"][0]["content"].startswith(
        "Pip has just arrived at the woods for the first time. Describe the place as Pip finds it")


# --- exact records, lookups and lines (pinned by mutation testing) -----------------------------------------
import random

from app import invented_places as IP
from tests.test_invented_places import DESIGN, DesignGM, heard, real_shop


def test_the_built_in_places_are_exactly_these_records(tmp_path):
    s, st, *_ = make(tmp_path, walk_minutes=7)
    reg = P.registry(st, s, None)
    assert reg["workshop"].walk_minutes == 7 and P.registry(st, None, None)["workshop"].walk_minutes == 10.0
    assert reg["woods"] == P.Place("woods", "a patch of woods past the garden: sticks, bark, resin, berries and nuts, "
                                   "birdsong", 8, offers=("gather",), daylight_only=True,
                                   verbs={"gather": ("forage for sticks, bark, berries and nuts", P._data()["start"][0]["verbs"]["gather"][1])})
    assert reg["junkyard"] == P.Place(
        "junkyard", "a scrapyard over the hill: heaps of scrap metal, wire, springs and old machine parts", 15,
        offers=("gather", "browse"), daylight_only=True,
        verbs={"gather": ("scavenge through the heaps", P._data()["start"][1]["verbs"]["gather"][1]),
               "browse": ("look over the heaps to see what's worth digging for", None)})
    st.add_character("Marigold", "neighbor", None, "persona", 60, 0, about="a beekeeper")
    st.add_character("Briar", "neighbor", None, "persona", 60, 0)
    reg = P.registry(st, s, None)
    assert reg["Marigold's home"].blurb == "where your neighbor Marigold lives (a beekeeper)"
    assert reg["Briar's home"].blurb == "where your neighbor Briar lives"


def test_said_about_gives_the_last_two_things_said_or_who_mentioned_it():
    ms = [{"by": b, "there": t} for b, t in (("Briar", "a meadow"), ("Morgan", "larks"), ("Marigold", "a stile"))]
    assert P.said_about(ms) == "Morgan says: larks; Marigold says: a stile"
    assert P.said_about([{"by": "Briar", "there": ""}, {"by": "Morgan", "there": ""}]) == "Morgan mentioned it"
    assert P.said_about([]) == ""


def test_the_gather_help_at_an_invented_place_exactly(tmp_path):
    shop = {"key": "Saltholm", "kind": "shop"}
    assert P._verb_help(shop, "gather", "ask to pick through the drawers") == (
        "Ask to pick through the drawers at Saltholm for 15-30 minutes. What you find is down to luck and what's in "
        "stock (it restocks slowly); it goes on account, to settle up later. You'll see what you found when the time "
        "is up; resting stops early.")
    assert P._verb_help({"key": "old mill", "kind": "wild"}, "gather", "forage here") == (
        "Forage here at the old mill for 15-60 minutes. What you find is down to luck and how picked-over the place "
        "is. You'll see what you found when the time is up; resting stops early.")
    assert P._verb_help(shop, "browse", "see what's in") is None


def test_an_invented_place_record_as_a_place(tmp_path):
    s, st = IP_fresh(tmp_path)
    rec = real_shop(st, now=1000.0)
    st.update_place("Saltholm", real_at=2000.0)
    IP.add_to(st, "Saltholm", "Briar", "", {"place": "Saltholm", "there": "said at once"}, now=2000.0)   # not since
    assert P.invented_place(st.place_row("Saltholm")).blurb == DESIGN["blurb"]
    IP.add_to(st, "Saltholm", "Morgan", "", {"place": "Saltholm", "there": "boats"}, now=3000.0)
    IP.add_to(st, "Saltholm", "Marigold", "", {"place": "Saltholm", "there": "gulls"}, now=3001.0)
    p = P.invented_place(st.place_row("Saltholm"))
    assert p.blurb == DESIGN["blurb"] + " (Marigold says: gulls)" and p.daylight_only is False
    assert p.mentions == st.place_row("Saltholm")["mentions"] and p.invented and not p.heard
    st.update_place("Saltholm", walk_minutes=None, daylight_only=1)
    p = P.invented_place(st.place_row("Saltholm"))
    assert p.walk_minutes == 0 and p.daylight_only is True
    assert rec["key"] == "Saltholm"


def IP_fresh(tmp_path):
    from tests.test_invented_places import fresh
    return fresh(tmp_path)


def test_find_understands_home_aliases_parts_of_names_and_neighbors(tmp_path):
    s, st, *_ = make(tmp_path)
    s.invented_places_per_day = 5
    for q in ("my garden", "the house", "house", "garden"):
        assert P.find(st, None, q) == P.HOME, q
    IP.accept(st, "Briar", "Ask the ironmonger in Saltholm.", {"place": "the ironmonger in Saltholm", "distance": "far"})
    IP.accept(st, "Briar", "Fen is near Fen Hollow.", {"place": "Fen", "distance": "near"})
    IP.accept(st, "Briar", "Fen is near Fen Hollow.", {"place": "Fen Hollow", "distance": "near"})
    assert P.find(st, None, "ironmonger in saltholm") == "Saltholm" and P.find(st, None, "salt") == "Saltholm"
    assert P.find(st, None, "fen") == "Fen" and P.find(st, None, "hollow") == "Fen Hollow"
    st.add_character("Marigold Thistlewick", "neighbor", None, "x", 60, 0)
    st.add_character("Ann March", "neighbor", None, "x", 60, 0)
    st.add_character("Jo Pell", "neighbor", None, "x", 60, 0)
    st.add_character("Tock", "creation", None, "x", 60, 0)
    assert P.find(st, None, "visit marigold thistlewick") == "Marigold Thistlewick's home"
    assert P.find(st, None, "marigold's") == "Marigold Thistlewick's home"
    assert P.find(st, None, "visit ann") == "Ann March's home"
    assert P.find(st, None, "visit jo") is None and P.find(st, None, "tock") is None


async def test_arriving_at_a_heard_of_place_designs_it_with_its_label_and_the_rng(tmp_path):
    s, st, *_ = make(tmp_path)
    IP.accept(st, "Briar", "Go and see the old mill.", {"place": "the old mill", "there": "a mill", "distance": "near"},
              now=time.time())
    gm = DesignGM({"kind": "sight", "description": "A mill."})
    _walk_to(st, "old mill")
    await P.arrive(st, s, gm, None, rng=random.Random(1))
    assert gm.calls[0][0] == "the old mill"
    IP.accept(st, "Briar", "Go and see Skerry.", {"place": "Skerry", "there": "a beach", "distance": "near"},
              now=time.time())
    st.update_place("old mill", real_at=time.time() - 2 * IP.DAY)
    raw = {"kind": "wild", "description": "A beach.",
           "loot": [{"name": f"thing {c}", "kind": "material", "tier": "common"} for c in "abc"]}
    _walk_to(st, "Skerry")
    await P.arrive(st, s, DesignGM(raw), None, rng=random.Random(5))
    r = random.Random(5)
    assert [e[2] for e in st.place_row("Skerry")["loot"]] == [r.randint(15, 30) for _ in range(3)]


async def test_a_bare_arrival_keeps_an_empty_description_and_a_long_one_is_clipped(tmp_path):
    s, st, *_ = make(tmp_path)
    heard(st, now=time.time())
    _walk_to(st, "Saltholm")
    await P.arrive(st, s, DesignGM(None), None)
    assert st.meta("place:Saltholm") == ""

    class Describer:
        async def describe_place(self, label, hints):
            return "z" * 501
    _walk_to(st, "woods")
    await P.arrive(st, s, Describer(), None)
    assert st.meta("place:woods") == "z" * 500 + "..."


def test_the_directory_lists_every_block_exactly(tmp_path):
    s, st, *_ = make(tmp_path, wild_places=[])
    s.invented_places_per_day = 5
    assert not any("heard of" in l for l in P.directory(st, s, None))
    heard(st, "Fallow", "near", "a meadow", now=time.time())
    st.update_place("Fallow", walk_minutes=1, daylight_only=0)
    rec = IP.accept(st, "Briar", "Lake Ennis has a view.", {"place": "Lake Ennis", "there": "a view"}, now=time.time())
    IP.design(st, rec, {"description": "A still lake.", "blurb": "a still lake"}, random.Random(1))
    st.update_place("Lake Ennis", walk_minutes=1, daylight_only=0)
    now = 1000.0 + IP.DAY
    IP.accept(st, "Briar", "My sister is in Brightwater.", {"place": "Brightwater", "there": "my sister",
                                                            "distance": "very far"}, now=1000.0)
    assert P.directory(st, s, None, now=now) == [
        "Places you can go (go_to):", "- Lake Ennis, 1 min - a still lake",
        "Places you've heard of but not been to (go_to works):", "- Fallow, about 1 min, a short walk - Briar says: a meadow",
        "Places you've heard of that are too far to walk to:", "- Brightwater - Briar says: my sister"]


def test_a_resident_with_nothing_known_about_them_is_just_here(tmp_path):
    s, st, *_ = make(tmp_path)
    real_shop(st)
    st.update_place("Saltholm", hours=None)
    st.add_character("Mr Teague", "resident", None, "persona", 0, 0, place="Saltholm")
    st.update_agent(location="Saltholm")
    assert "Mr Teague is here; talk with them in person using say with to: Mr Teague." in P.perception(st, s, None)


@pytest.mark.asyncio
async def test_nothing_that_belongs_to_a_place_works_while_walking_somewhere_else(tmp_path):
    from tests.test_garden import garden, use                                              # a module's tools: the same rules
    from tests.test_projects import call
    s, st, gm, agent = make(tmp_path, modules="on", module_runner="local")
    garden(st)
    st.update_agent(location="workshop")
    st.add_item("carrot seeds", 1, "seed")
    assert "nothing is planted" in await use(agent, "harvest")                              # at home, before leaving
    _walk_to(st, "Saltholm")                                                               # underway, still "at" the workshop
    for name, args in (("harvest", {}), ("plant", {"seed": "carrot seeds"})):
        r = await agent._run_tool(ToolCall(id="1", name=name, arguments=args), 0)
        assert r["content"] == "you're on the way to Saltholm; wait until you get there" and r["followup"] is True
    assert st.find_item("carrot seeds")[0]["qty"] == 4 and st.store("garden") == {}        # 3 to start with, +1
    assert "wrote" in (await call(agent, "note_to_self", section="todo", text="buy thin brass wire")).text   # anywhere tools still work
    st.end_session()
    assert "nothing is planted" in await use(agent, "harvest")                              # arrived or turned back: it works again
    _walk_to(st, "workshop")
    assert await use(agent, "harvest") == "you're on the way to home; wait until you get there"


@pytest.mark.asyncio
async def test_the_tools_offered_while_walking_are_only_the_ones_that_work_anywhere(tmp_path):
    from tests.test_garden import garden
    s, st, gm, agent = make(tmp_path)
    garden(st)
    agent.tools = T.enabled_tools(Settings(tools=["say", "go_to", "tend", "note_to_self"]))
    st.update_agent(location="workshop")
    offered = lambda: {sp.name for sp in agent._specs()}                                   # noqa: E731
    assert {"harvest", "plant", "say", "go_to"} <= offered()
    _walk_to(st, "Saltholm")
    walking = offered()
    assert {"say", "go_to", "note_to_self"} <= walking and not walking & {"harvest", "plant", "tend"}
    st.end_session()
    assert {"harvest", "plant"} <= offered()
