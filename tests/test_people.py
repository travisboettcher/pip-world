"""People, part one (docs/DESIGN-engine-audit.md, B3, B4, C1): a character of any role a module names, living at a place their record
points to; talk with whoever is present, greeted by a few at a time; place kinds and tool scopes from the world pack."""
import json
import shutil
import time
from pathlib import Path

import pytest

from app import layouts, modules as M, neighbors as nb, places, talk, tools as T, world_pack as W, worldmap
from app.config import Settings
from tests.test_projects import FixedRng, call, make, report

ROOT = Path(__file__).resolve().parent.parent


def bring(st, s, **v):
    """Someone a module brings into the world (its `character` proposal), as the engine takes them in."""
    return nb.arrive(st, s, M._character(st, {"persona": "a quiet sort", "about": "keeps to themself", **v}))


def test_someone_without_a_home_named_gets_one_of_their_own_worded_by_the_world(tmp_path):
    s, st, *_ = make(tmp_path)
    ch = bring(st, s, name="Marigold", kind="neighbor")
    assert ch["place"] == "Marigold's home" and places.home_of(ch) == "Marigold's home"
    reg = places.registry(st, s, None)
    assert reg["Marigold's home"].blurb == "where Marigold lives (keeps to themself)" and reg["Marigold's home"].offers == ("talk",)
    assert places.kind_of(st, "Marigold's home") == "neighbor" and places.label("Marigold's home") == "Marigold's home"
    assert places.resident_of(st, "Marigold's home")["name"] == "Marigold" and places.place_of(st, ch) == "Marigold's home"
    assert places.find(st, None, "visit marigold") == "Marigold's home" and places.resident_of(st, "woods") is None
    ev = st.events(5)[0]
    assert ev["kind"] == "character" and ev["data"] == {"name": "Marigold", "role": "neighbor", "about": "keeps to themself", "place": "Marigold's home"}


def test_someone_of_any_role_lives_where_their_module_says(tmp_path):
    s, st, *_ = make(tmp_path)
    ezra = bring(st, s, name="Ezra", kind="villager", home="woods")
    assert (ezra["kind"], ezra["place"]) == ("villager", "woods") and places.place_of(st, ezra) == "woods"
    assert [c["name"] for c in places.company_at(st, "woods")] == ["Ezra"] and "Ezra's home" not in places.registry(st, s, None)
    assert places.resident_of(st, "woods") is None                                     # the woods aren't anyone's home of their own
    assert places.kind_of(st, "woods") == "wild"


@pytest.mark.parametrize("v,why", [
    ({"kind": "creation"}, "`character.kind` is a word for their role (villager, neighbor...), not creation"),
    ({"kind": "Two Words"}, "`character.kind` is a word for their role (villager, neighbor...), not creation"),
    ({"kind": "villager", "home": "Atlantis"}, "`character.home` is a place in the world, not 'Atlantis'"),
    ({"kind": "villager", "home": 3}, "`character.home` is a place in the world, not 3"),
    ({"kind": "villager", "colour": "red"}, "`character` is {name, kind (a word for their role), persona, about, home?, writes?, letter?, mentions_place?}"),
])
def test_a_character_is_checked(tmp_path, v, why):
    s, st, *_ = make(tmp_path)
    with pytest.raises(M.Refused) as e:
        M._character(st, {"name": "Ezra", "persona": "p", "about": "a", **v})
    assert str(e.value) == why


def test_a_home_may_be_a_place_someone_told_the_agent_of(tmp_path):
    s, st, *_ = make(tmp_path)
    st.add_place("Brygdon", "brygdon", kind="market", status="real", created_at=time.time(), heard_at=time.time(), hours=[0, 24], daylight_only=0,
                 walk_minutes=10.0, loot=[], verbs={}, blurb="the square")
    assert bring(st, s, name="Ada", kind="baker", home="Brygdon")["place"] == "Brygdon"
    assert bring(st, s, name="Bo", kind="keeper", home="home")["place"] == places.home_key()   # the agent's own home: a lodger


def test_the_old_neighbours_live_where_their_homes_always_were(tmp_path):
    s, st, *_ = make(tmp_path)
    with st.lock:
        st.db.execute("INSERT INTO characters (name, kind, creation_id, persona, chatter_minutes, next_chatter_at, ts, about, place) "
                      "VALUES ('Oriel', 'neighbor', NULL, 'p', 60, 1e18, 0, 'a', '')")
        st.db.execute("INSERT INTO characters (name, kind, creation_id, persona, chatter_minutes, next_chatter_at, ts, about, place) "
                      "VALUES ('Clock', 'creation', 1, 'p', 60, 1e18, 0, 'a', '')")
        st.db.commit()
    st.set_meta(homes_named="")
    st._homes_named()
    assert {c["name"]: c["place"] for c in st.characters()} == {"Oriel": "Oriel's home", "Clock": ""} and st.meta("homes_named") == "1"


def test_a_talking_thing_lives_nowhere(tmp_path):
    s, st, *_ = make(tmp_path)
    ch = st.add_character("Tick", "creation", 1, "a clock", 60, 1e18)
    assert ch["place"] == "" and places.place_of(st, ch) is None and "Tick's home" not in places.registry(st, s, None)


@pytest.mark.asyncio
async def test_whoever_is_there_talks_and_only_a_few_greet_at_once(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Ada: Morning."), report(text="Bo: You again."), report(text="Ada: The well's low."),
                                       report(text="Cy: Hm.")])
    for n in ("Ada", "Bo", "Cy"):
        bring(st, s, name=n, kind="villager", home="woods")
    st.update_agent(location="woods")
    st.set_meta(arrived_at=str(time.time()))
    assert talk.partner(st)["name"] == "Ada"
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is True
    assert [e["data"]["name"] for e in st.events(10) if e["kind"] == "companion"] == ["Bo", "Ada"]     # two greet; Cy waits to be spoken to
    assert await nb.step(st, s, agent.gm, FixedRng(), time.time()) is False
    assert "said it to Cy" in (await call(agent, "say", text="Hello, Cy.", to="Cy")).text
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    assert [e["data"]["name"] for e in st.events(10) if e["kind"] == "companion"][0] == "Cy"
    lines = agent._perception("timer", [])
    assert "Ada is here (keeps to themself); talk with them in person using say with to: Ada." in lines
    talk_lines = agent._talk([])
    assert "Talking with Ada (this visit, oldest first):" in talk_lines and "Talking with Cy (this visit, oldest first):" in talk_lines


@pytest.mark.asyncio
async def test_someone_away_from_home_is_out_of_reach_there(tmp_path):
    s, st, gm, agent = make(tmp_path)
    bring(st, s, name="Ezra", kind="villager", home="woods")
    r = await call(agent, "say", text="Hello?", to="Ezra")
    assert r.text == "Ezra can't hear you from here; go_to woods to talk with them"


def test_place_kinds_are_the_worlds(tmp_path):
    assert set(layouts.kinds()) == {"home", "neighbor", "library", "wild", "yard", "shop", "market", "sight"}
    W.set_active(W.load(Settings(world_pack=str(ROOT / "worlds" / "ashfall"))))
    try:
        assert set(layouts.kinds()) == {"home", "dwelling", "wild", "yard", "sight"}               # no library, no market: none in that world
        with pytest.raises(M.Refused) as e:
            M.check_manifest({"name": "stalls", "kind": "place", "api": 1, "hooks": ["on_build"], "kinds": ["market"]}, "world")
        assert str(e.value).startswith("`kinds` is a list drawn from: ")
    finally:
        W.set_active(W.load(Settings()))


def test_the_map_names_each_place_by_the_worlds_kinds(tmp_path):
    s, st, *_ = make(tmp_path)
    assert places.kind_of(st, "library") == "library"
    lodger = bring(st, s, name="Wim", kind="lodger", home="home")
    assert places.place_of(st, lodger) == places.home_key() and places.resident_of(st, places.home_key()) is None   # home is the agent's
    bring(st, s, name="Marigold", kind="neighbor")
    lib = type("L", (), {"available": lambda self: True})()
    kinds = {p["key"]: p["kind"] for p in worldmap.snapshot(st, s, lib)["places"]}
    assert kinds["Marigold's home"] == "neighbor" and kinds["library"] == "library" and kinds["woods"] == "wild" and kinds[places.home_key()] == "home"


def test_a_pack_says_what_its_dwellings_are_called_and_what_kind_they_are(tmp_path):
    d = tmp_path / "ashfall"
    shutil.copytree(ROOT / "worlds" / "ashfall", d)
    p = json.loads((d / "places.json").read_text())
    p["dwellings"] = {"kind": "sight", "called": "the {name} place"}
    (d / "places.json").write_text(json.dumps(p))
    W.set_active(W.load(Settings(world_pack=str(d))))
    try:
        (tmp_path / "w").mkdir()
        s, st, *_ = make(tmp_path / "w", world_pack=str(d))
        ch = bring(st, s, name="Jun", kind="trader")
        assert ch["place"] == "the Jun place" and places.kind_of(st, "the Jun place") == "sight"
    finally:
        W.set_active(W.load(Settings()))


@pytest.mark.asyncio
async def test_a_tool_offered_where_a_place_lists_it_says_where_it_can_be_used(tmp_path):
    s, st, gm, agent = make(tmp_path)
    assert T.SCOPES["browse"] == ("offered",)
    r = await call(agent, "browse")
    assert r.text == "you can't browse here; junkyard has it"


def test_a_bare_world_has_only_the_kinds_it_names(tmp_path):
    from tests.test_world_pack import pack_dir
    d = pack_dir(tmp_path)                                                            # no places.json at all
    (d / "places.json").write_text(json.dumps({"start": [{"key": "ridge", "description": "a bare ridge", "kind": "heights"}],
                                               "library": {"key": "archive", "description": "an archive"}}))
    W.set_active(W.load(Settings(world_pack=str(d))))
    try:
        assert layouts.kinds() == ("home", "dwelling", "sight", "heights") and places.library_kind() == "sight"
        (tmp_path / "v").mkdir()
        s0, st0, *_ = make(tmp_path / "v", world_pack=str(d))
        lib = type("L", (), {"available": lambda self: True})()
        assert places.registry(st0, s0, lib)["archive"].kind == "sight" and places.kind_of(st0, "archive") == "sight"
        assert places.kind_of(st0, "ridge") == "heights"
        assert places._start_keys() == {"ridge", "archive"}
        (d / "places.json").write_text(json.dumps({"fallback_kind": "ruins", "library": {"key": "archive", "description": "x"}}))
        W._data.cache_clear()
        assert places.library_kind() == "ruins" and layouts.kinds() == ("home", "dwelling", "ruins") and places._start_keys() == {"archive"}
        (d / "places.json").write_text(json.dumps({}))
        W._data.cache_clear()
        assert layouts.kinds() == ("home", "dwelling") and places._start_keys() == set()
        (tmp_path / "w").mkdir()
        s, st, *_ = make(tmp_path / "w", world_pack=str(d))
        assert places.kind_of(st, "nowhere") == "" and places.dwelling_kind() == "dwelling"
        bring(st, s, name="Ox", kind="drifter")
        snap = {p["key"]: p["kind"] for p in worldmap.snapshot(st, s, None)["places"]}
        assert snap["Ox's home"] == "dwelling" and places.kind_of(st, "Ox's home") == "dwelling"
    finally:
        W._data.cache_clear()
        W.set_active(W.load(Settings()))


def test_a_kindless_starting_place_is_drawn_wild_on_the_map(tmp_path):
    from tests.test_world_pack import pack_dir
    d = pack_dir(tmp_path)
    (d / "places.json").write_text(json.dumps({"start": [{"key": "ridge", "description": "a bare ridge"}]}))
    W.set_active(W.load(Settings(world_pack=str(d))))
    try:
        (tmp_path / "w").mkdir()
        s, st, *_ = make(tmp_path / "w", world_pack=str(d))
        assert {p["key"]: p["kind"] for p in worldmap.snapshot(st, s, None)["places"]}["ridge"] == "wild"
        assert places.kind_of(st, "ridge") == "" and "" not in layouts.kinds()
    finally:
        W._data.cache_clear()
        W.set_active(W.load(Settings()))


def test_a_talking_thing_never_gets_a_home_even_without_a_creation(tmp_path):
    s, st, *_ = make(tmp_path)
    assert st.add_character("Clocky", "creation", None, "a chatty clock", 60, 0)["place"] == ""


def test_the_old_homes_are_named_once_and_in_the_worlds_own_words(tmp_path):
    d = tmp_path / "ashfall"
    shutil.copytree(ROOT / "worlds" / "ashfall", d)
    p = json.loads((d / "places.json").read_text())
    p["dwellings"] = {"called": "the {name} place"}
    (d / "places.json").write_text(json.dumps(p))
    (tmp_path / "w").mkdir()
    s, st, *_ = make(tmp_path / "w", world_pack=str(d))
    W.set_active(W.load(Settings()))                                                   # another world active: the state's own words count
    with st.lock:
        for name, kind in (("Oriel", "neighbor"), ("Tock", "creation")):
            st.db.execute("INSERT INTO characters (name, kind, creation_id, persona, chatter_minutes, next_chatter_at, ts, about, place) "
                          "VALUES (?, ?, NULL, 'p', 60, 1e18, 0, 'a', '')", (name, kind))
        st.db.commit()
    st.set_meta(homes_named="")
    st._homes_named()
    assert {c["name"]: c["place"] for c in st.characters()} == {"Oriel": "the Oriel place", "Tock": ""}
    assert st.add_character("Ann", "neighbor", None, "p", 60, 0)["place"] == "the Ann place"
    with st.lock:
        st.db.execute("UPDATE characters SET place = '' WHERE name = 'Oriel'")
        st.db.commit()
    st._homes_named()                                                                  # once
    assert next(c for c in st.characters() if c["name"] == "Oriel")["place"] == ""


@pytest.mark.asyncio
async def test_someone_answering_doesnt_count_as_a_greeting(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Ada: Yes?"), report(text="Bo: Hello.")])
    for n in ("Ada", "Bo", "Cy"):
        bring(st, s, name=n, kind="villager", home="woods")
    st.update_agent(location="woods")
    visit = str(time.time())
    st.set_meta(arrived_at=visit)
    ada = st.find_character("Ada")
    st.set_meta(**{f"greeted:{ada['id']}": visit})
    st.update_character(ada["id"], heard=[{"ts": time.time(), "text": "Ada?"}])
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    assert [e["data"]["name"] for e in st.events(10) if e["kind"] == "companion"] == ["Bo", "Ada"]   # Ada answers; Bo greets; Cy waits


@pytest.mark.asyncio
async def test_the_talk_shown_is_this_visits_only(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="Ada: Morning.")])
    bring(st, s, name="Ada", kind="villager", home="woods")
    st.log("companion", name="Ada", text="Words from last week.", reply=True, visit=True)
    time.sleep(0.01)
    st.update_agent(location="woods")
    st.set_meta(arrived_at=str(time.time()))
    await nb.step(st, s, agent.gm, FixedRng(), time.time())
    talk_lines = "\n".join(agent._talk([]))
    assert "Ada: Morning." in talk_lines and "Words from last week." not in talk_lines


@pytest.mark.asyncio
async def test_where_a_tool_can_be_used_is_every_place_that_lists_it(tmp_path):
    s, st, gm, agent = make(tmp_path)
    for key in ("Scrap Hill", "Rag Yard", "Tin Row"):
        st.add_place(key, key.lower(), kind="yard", status="real", created_at=time.time(), heard_at=time.time(), hours=None, daylight_only=0,
                     walk_minutes=10.0, loot=[], verbs={"browse": ["look over the heaps", None]}, blurb="heaps")
    assert (await call(agent, "browse")).text == "you can't browse here; junkyard, Scrap Hill, Rag Yard have it"
    s.wild_places = []
    for key in ("Scrap Hill", "Rag Yard", "Tin Row"):
        invented = __import__("app.invented_places", fromlist=["x"])
        invented.remove(st, key)
    assert (await call(agent, "browse")).text == "you can't browse here"
