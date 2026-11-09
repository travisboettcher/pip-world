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
    assert WV.COASTAL.search("a cottage on the salt marsh") and WV.COASTAL.search("the Harbour road") and WV.COASTAL.search("walks the mudflats")
    assert WV.COASTAL.search("a shop of drawers and wire") is None and WV.COASTAL.search("a seaside town") is None


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
    assert [bool(WV.COASTAL.search(WV._words(st, k, rows))) for k in "ABCD"] == [True, True, True, False]
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
