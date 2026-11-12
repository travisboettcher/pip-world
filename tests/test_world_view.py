"""The world view's map data (docs/DESIGN-world-view.md): a stable seed, the places with how they are known, the walk, and the moment."""
import time

import pytest
from fastapi.testclient import TestClient

from app import world_view as WV
from app.config import Settings
from app.llm.fake import FakeBackend
from app.main import create_app
from tests.test_neighbor import neighbor
from tests.test_projects import call, make, report
from app import tools as T


def test_the_world_seed_is_made_once_and_kept(tmp_path):
    s, st, gm, agent = make(tmp_path)
    first = WV.seed(st)
    assert 1 <= first <= 999_999 and WV.seed(st) == first and st.meta("world_seed") == str(first)


def test_places_carry_visits_and_whether_they_lie_by_water(tmp_path):
    s, st, gm, agent = make(tmp_path, neighbor=True)
    ch = st.add_character("Oriel", "neighbor", None, "A tide-reader on the salt marsh.", 60, 0, about="Lives by the shore.")
    st.add_place("Saltholm", "saltholm", kind="shop", status="real", created_at=0, heard_at=0, hours=[9, 17], daylight_only=0, walk_minutes=30.0,
                 loot=[], verbs={}, description="An ironmonger by the harbour road.")
    st.add_place("Hollin", "hollin", kind="wild", status="heard", created_at=time.time(), heard_at=time.time(), hours=None, daylight_only=0, walk_minutes=20.0, loot=[], verbs={})
    st.log("arrived", place="woods", label="the woods")
    st.log("arrived", place="woods", label="the woods")
    m = WV.map_view(st, s, None)
    by = {p["key"]: p for p in m["places"]}
    assert by["woods"]["visits"] == 2 and by["woods"]["first_visited"] and by["junkyard"]["visits"] == 0 and by["junkyard"]["first_visited"] is None
    assert by["Saltholm"]["coastal"] and by["Oriel's home"]["coastal"] and not by["woods"]["coastal"] and not by["workshop"]["coastal"]
    assert by["Hollin"]["heard_only"] and not by["Hollin"]["coastal"]
    assert m["seed"] == WV.seed(st) and m["home"] == "workshop" and m["pip"]["at"] == "workshop"
    assert set(m["now"]) == {"ts", "minutes", "season", "weather"} and m["now"]["weather"] is None


@pytest.mark.asyncio
async def test_a_walk_in_progress_has_its_times(tmp_path):
    s, st, gm, agent = make(tmp_path)
    agent.tools["go_to"] = T.REGISTRY["go_to"]
    await call(agent, "go_to", place="woods")
    w = WV.map_view(st, s, None)["pip"]["walking"]
    sess = st.session()
    assert w["to"] == "woods" and w["started_at"] == sess["started_at"] and w["ends_at"] == sess["ends_at"]


def test_coastal_words():
    assert WV.coastal().search("a cottage on the salt marsh") and WV.coastal().search("the Harbour road") and WV.coastal().search("walks the mudflats")
    assert WV.coastal().search("a shop of drawers and wire") is None and WV.coastal().search("a seaside town") is None


def test_the_map_endpoint_is_public(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual", public_hosts=["pip.example.org"])
    with TestClient(create_app(s, FakeBackend())) as c:
        for headers in ({}, {"Host": "pip.example.org"}):
            got = c.get("/world/map", headers=headers)
            assert got.status_code == 200 and got.json()["seed"] and any(p["key"] == "workshop" for p in got.json()["places"])


def test_water_is_spotted_in_any_part_of_a_place_record(tmp_path):
    s, st, gm, agent = make(tmp_path)
    rows = {"A": {"description": "by the harbour", "blurb": "", "mentions": []}, "B": {"description": None, "blurb": "a quay town", "mentions": None},
            "C": {"description": "", "blurb": None, "mentions": [{"there": "near the beach"}, {"by": "Jo"}]}, "D": {"description": "", "blurb": "", "mentions": [{}]}}
    assert [bool(WV.coastal().search(WV._words(st, k, rows))) for k in "ABCD"] == [True, True, True, False]
    assert WV._words(st, "Nowhere", rows) == "" and WV._words(st, "B", rows).split() == ["a", "quay", "town"]


def test_the_moment_the_map_is_drawn_for(tmp_path, monkeypatch):
    import json
    from datetime import datetime
    s, st, gm, agent = make(tmp_path, weather=True, hemisphere="south")
    at = datetime(2026, 7, 9, 14, 25).timestamp()
    st.set_meta(weather=json.dumps({"condition": "rainy", "temp": 9.0, "unit": "°C", "above_horizon": True, "next_rising": None, "next_setting": None}), weather_at=at)
    now = WV.map_view(st, s, None, now=at)["now"]
    assert now == {"ts": at, "minutes": 14 * 60 + 25, "season": "winter", "weather": "rainy"}
    s.weather = False
    assert WV.map_view(st, s, None, now=at)["now"]["weather"] is None


@pytest.mark.asyncio
async def test_the_walk_is_where_it_is_at_the_moment_asked(tmp_path):
    s, st, gm, agent = make(tmp_path)
    agent.tools["go_to"] = T.REGISTRY["go_to"]
    await call(agent, "go_to", place="woods")
    sess = st.session()
    half = (sess["started_at"] + sess["ends_at"]) / 2
    assert WV.map_view(st, s, None, now=half)["pip"]["walking"]["progress"] == 0.5
    st.end_session()
    assert WV.map_view(st, s, None)["pip"]["walking"] is None


def test_a_new_seed_comes_from_the_whole_range(tmp_path, monkeypatch):
    s, st, gm, agent = make(tmp_path)
    seen = []
    monkeypatch.setattr(WV.random, "randint", lambda a, b: seen.append((a, b)) or 42)
    assert WV.seed(st) == 42 and seen == [(1, 999_999)]


# --- scenes (step 2) --------------------------------------------------------------------------------------------------------------
TIMEKEEPER = {"capabilities": {"timekeeper": {"drift_per_day": 5}, "upkeep": {"verb": "wound", "hours": 12}}, "quirks": []}


def clock(st, now=None):
    from app import creations as cr
    return st.add_creation("Gear Clock", "a clock", None, "sound", TIMEKEEPER, cr.initial_runtime(TIMEKEEPER, now or time.time()))
def test_the_home_scene_has_pip_the_garden_the_creations_and_the_belongings(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.update_agent(activity="waiting on garden", description="Waiting for the peas.", mood="content")
    st.plant(1, "pea seeds", "peas", 600, 3, 0.25)
    c = clock(st)
    st.add_coins("pip", 5)
    d = WV.scene_view(st, s, None)
    assert d["place"]["key"] == "workshop" and d["place"]["kind"] == "home" and d["place"]["open"] is True and not d["place"]["coastal"]
    assert d["pip"]["here"] and not d["pip"]["walking"] and d["pip"]["description"] == "Waiting for the peas." and d["pip"]["session"] is None
    assert d["garden"][0]["crop"] == "peas" and d["coins"] == st.coins() and {i["name"] for i in d["items"]} == {i["name"] for i in st.items()}
    gc = next(x for x in d["creations"] if x["name"] == c["name"])
    assert gc["capabilities"] == sorted(c["spec"]["capabilities"]) and gc["running"] and 0 <= gc["clock"]["minutes"] < 1440 and gc["tended_until"]
    assert d["present"] == [] and d["booths"] == [] and d["stall"] == []


def test_a_clock_face_is_in_minutes_past_midnight(tmp_path):
    from datetime import datetime
    s, st, gm, agent = make(tmp_path)
    c = clock(st)
    st.set_runtime(c["id"], {**c["runtime"], "clock_offset": 0, "clock_set_at": datetime(2026, 7, 9, 0, 0).timestamp()})
    at = datetime(2026, 7, 9, 14, 25).timestamp()
    c = st.creation(c["id"])
    assert WV._clock({**c, "runtime": {**c["runtime"], "tended_until": at + 3600}}, at)["minutes"] == 14 * 60 + 28     # 14:25, plus 5 minutes a day of drift for 14.4 hours


@pytest.mark.asyncio
async def test_a_scene_elsewhere_knows_who_is_there_and_where_pip_is(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="A low cottage.")], work_speed=1e6)
    agent.tools["go_to"] = T.REGISTRY["go_to"]
    ch = neighbor(st, s)
    d = WV.scene_view(st, s, None, "Marigold's home")
    assert d["place"]["kind"] == "neighbor" and not d["pip"]["here"] and d["pip"]["where"] == "workshop" and "garden" not in d
    assert [{k: c[k] for k in ("name", "kind", "about")} for c in d["present"]] == [{"name": "Marigold", "kind": "neighbor", "about": ch["about"]}]
    await call(agent, "go_to", place="Marigold")
    d = WV.scene_view(st, s, None)                                                     # on the way: the scene is where Pip is going
    assert d["place"]["key"] == "Marigold's home" and d["pip"]["walking"] and not d["pip"]["here"] and d["pip"]["session"]["kind"] == "walk"
    time.sleep(0.01)
    await agent.finish_work()
    assert WV.scene_view(st, s, None)["pip"]["here"]
    assert WV.scene_view(st, s, None, "Nowhere") is None


@pytest.mark.asyncio
async def test_a_work_session_names_its_project_and_stage(tmp_path):
    from tests.test_projects import PLAN
    s, st, gm, agent = make(tmp_path, [report(**PLAN)])
    st.add_item("brass wire", 9, "material")
    await call(agent, "start_project", name="Gear clock", description="a clock", craft="clockmaking")
    await call(agent, "work_on", project=1)
    sess = WV.scene_view(st, s, None)["pip"]["session"]
    p = st.project(1)
    assert sess["kind"] == "work" and sess["project"] == p["name"] and sess["stage"] == p["stages"][0]["name"] and sess["ends_at"] > sess["started_at"]


def test_a_market_scene_lists_its_booths_and_pips_stall(tmp_path):
    from tests.test_stall import LOOT
    s, st, gm, agent = make(tmp_path)
    st.add_place("Brygdon", "brygdon", kind="market", status="real", created_at=time.time(), heard_at=time.time(), hours=[0, 24], daylight_only=0,
                 walk_minutes=10.0, loot=LOOT, verbs={"browse": ["see", None]}, description="A market by the quay.")
    st.set_stall("Brygdon", "carrots", name="carrots", kind="food", description="", attrs={}, qty=6, ask=4)
    d = WV.scene_view(st, s, None, "Brygdon")
    assert d["place"]["kind"] == "market" and d["place"]["hours"] == [0, 24] and d["place"]["open"] and d["place"]["coastal"]
    assert d["place"]["description"] == "A market by the quay."
    assert d["booths"][0]["booth"] == "Brygdon" and d["booths"][0]["whose"] == "" and {i["name"] for i in d["booths"][0]["items"]} == {"brass wire", "tomatoes", "awl"}
    assert all(i["price"] >= 1 and i["left"] >= 1 for i in d["booths"][0]["items"]) and d["stall"] == [{"item": "carrots", "qty": 6, "ask": 4, "kind": "food"}]


def test_the_scene_endpoint_is_public_and_says_when_a_place_is_unknown(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", pacing="manual", public_hosts=["pip.example.org"])
    with TestClient(create_app(s, FakeBackend())) as c:
        for headers in ({}, {"Host": "pip.example.org"}):
            assert c.get("/world/scene", headers=headers).json()["place"]["key"] == "workshop"
        assert c.get("/world/scene?place=Nowhere").status_code == 404
        page, js, sc = (c.get(f"/ui/{f}").text for f in ("index.html", "app.js", "world/scene.js"))
        assert 'id="scene"' in page and 'id="wv-here"' in page and 'id="wv-map"' in page and "import { SceneView } from './world/scene.js'" in js
        assert "export class SceneView" in sc and c.get("/ui/world/kit.js").status_code == 200 and c.get("/ui/world/layout.js").status_code == 200 and c.get("/ui/world/parts.js").status_code == 200
        assert c.get("/ui/vendor/three/three.min.js").status_code == 200 and "MIT License" in c.get("/ui/vendor/three/LICENSE").text


def test_the_scene_carries_exactly_these_facts(tmp_path):
    import json
    from tests.test_stall import LOOT
    s, st, gm, agent = make(tmp_path, weather=True)
    st.set_meta(weather=json.dumps({"condition": "rainy", "temp": 9.0, "unit": "°C", "above_horizon": True, "next_rising": None, "next_setting": None}), weather_at=time.time())
    st.add_place("Brygdon", "brygdon", kind="market", status="real", created_at=time.time(), heard_at=time.time(), hours=[0, 24], daylight_only=0,
                 walk_minutes=10.0, loot=LOOT, verbs={}, blurb="the square")
    d = WV.scene_view(st, s, None, "Brygdon")
    assert set(d["place"]) == {"key", "label", "kind", "blurb", "description", "hours", "open", "heard_only", "coastal", "props", "scene", "finds"}
    assert d["place"]["label"] == "Brygdon" and d["place"]["blurb"] == "the square" and d["place"]["description"] == "" and d["place"]["heard_only"] is False
    assert set(d["pip"]) == {"here", "where", "walking", "activity", "description", "mood", "energy", "hunger", "asleep", "session"}
    item = next(i for i in d["booths"][0]["items"] if i["name"] == "brass wire")
    assert item == {"name": "brass wire", "kind": "material", "price": item["price"], "left": item["left"]} and item["left"] == 4
    assert d["now"]["weather"] == "rainy" and set(d) == {"place", "lives_here", "pip", "present", "booths", "stall", "now", "objects", "layout"}
    home = WV.scene_view(st, s, None)
    assert set(home) == {"place", "lives_here", "pip", "present", "booths", "stall", "now", "garden", "creations", "items", "coins", "objects", "layout"}
    st.update_agent(activity="sleeping")
    assert WV.scene_view(st, s, None)["pip"]["asleep"] is True
    st.add_place("Hollin", "hollin", kind="wild", status="heard", created_at=time.time(), heard_at=time.time(), hours=None, daylight_only=0, walk_minutes=20.0, loot=[], verbs={})
    h = WV.scene_view(st, s, None, "Hollin")
    assert h["place"]["heard_only"] is True and h["place"]["open"] is False and h["place"]["kind"] == "wild" and h["place"]["hours"] is None


def test_an_experiment_is_named_too_and_a_stage_past_the_plan_is_none(tmp_path):
    s, st, gm, agent = make(tmp_path)
    pid = st.db.execute("INSERT INTO projects (name, craft, difficulty, stages, ts) VALUES ('Kite', 'kites', 1, ?, 0)", ('[{"name": "cut the frame"}]',)).lastrowid
    st.start_session(pid, 0, 30, time.time() + 600, kind="experiment")
    assert WV.scene_view(st, s, None)["pip"]["session"]["stage"] == "cut the frame"
    st.start_session(pid, 1, 30, time.time() + 600, kind="experiment")
    sess = WV.scene_view(st, s, None)["pip"]["session"]
    assert sess["project"] == "Kite" and sess["stage"] is None


@pytest.mark.asyncio
async def test_who_is_at_a_place_does_not_depend_on_pip(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="A low cottage.")], work_speed=1e6)
    agent.tools["go_to"] = T.REGISTRY["go_to"]
    neighbor(st, s)
    await call(agent, "go_to", place="Marigold")
    time.sleep(0.01)
    await agent.finish_work()
    await call(agent, "go_to", place="workshop")                                        # Pip leaves; she is still at home
    assert [c["name"] for c in WV.scene_view(st, s, None, "Marigold's home")["present"]] == ["Marigold"]
    assert WV.scene_view(st, s, None)["place"]["key"] == "workshop"


def test_scene_numbers_and_creations_in_detail(tmp_path):
    from datetime import datetime
    s, st, gm, agent = make(tmp_path)
    st.update_agent(energy=0.12345, hunger=0.6789)
    c = clock(st)
    night = datetime(2026, 7, 9, 2, 0).timestamp()
    d = WV.scene_view(st, s, None, now=night)
    assert d["pip"]["energy"] == 0.12 and d["pip"]["hunger"] == 0.68 and d["now"]["ts"] == night and d["now"]["minutes"] == 120
    gc = d["creations"][0]
    assert set(gc) == {"name", "quality", "capabilities", "running", "description", "clock", "tended_until"} and gc["quality"] == "sound"
    assert all(set(i) == {"name", "qty", "kind"} for i in d["items"]) and d["items"]
    assert set(gc["clock"]) == {"minutes", "running"} and gc["clock"]["running"] is True
    assert WV.scene_view(st, s, None, "woods", now=night)["place"]["open"] is False                               # the woods are shut at night
    assert WV.scene_view(st, s, None, "woods", now=datetime(2026, 7, 9, 13, 0).timestamp())["place"]["open"] is True
