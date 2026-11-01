import math
import time

import pytest
from fastapi.testclient import TestClient

from app import worldmap as M
from app.config import Settings
from app.llm.fake import FakeBackend
from app.main import create_app
from tests.test_projects import make
from tests.test_scoping import FakeLibrary


def dist(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def neighbor(st, name="Marigold"):
    return st.add_character(name, "neighbor", "a beekeeper", "persona", 60, "", 0)


def saltholm(st, status="heard", **kw):
    return st.add_place("Saltholm", "saltholm", walk_minutes=33.0, status=status, kind=kw.pop("kind", "shop"),
                        created_at=time.time(), heard_at=time.time(), **kw)


# --- placement ------------------------------------------------------------------------------------------------------
def test_a_new_place_is_a_walk_away_from_home_by_its_walking_minutes():
    for minutes in (8, 15, 33.5):
        x, y = M.place_new([], "woods", minutes)
        assert math.hypot(x, y) == pytest.approx(minutes, abs=0.01)
    assert math.hypot(*M.place_new([], "woods", 0)) == pytest.approx(M.MIN_RADIUS, abs=0.01)   # never on top of home
    assert math.hypot(*M.place_new([], "woods", 2)) == pytest.approx(M.MIN_RADIUS, abs=0.01)


def test_placement_is_reproducible_and_depends_on_the_name():
    assert M.place_new([], "woods", 8) == M.place_new([], "woods", 8) == M.place_new([], "WOODS", 8)
    assert M.place_new([], "woods", 8) != M.place_new([], "junkyard", 8)
    start = M.start_index("woods")
    assert 0 <= start < M.CANDIDATES
    assert M.place_new([], "woods", 8) == M.candidate(start, 8)                # all angles equally roomy: the first one wins


def test_a_new_place_goes_where_there_is_most_room():
    r = 12
    others = [M.candidate(i, r) for i in range(M.CANDIDATES) if i != 7]        # every spot at that radius taken but one
    assert M.place_new(others, "anything", r) == M.candidate(7, r)
    assert M.place_new([(0.0, 0.0)] + others, "anything", r) == M.candidate(7, r)
    crowd = [M.candidate(i, r) for i in range(5)]                              # five taken: it never lands on one of them
    for key in ("a", "b", "c", "d"):
        assert M.place_new(crowd, key, r) not in crowd
    two_gaps = [M.candidate(i, r) for i in range(M.CANDIDATES) if i not in (3, 14)]        # the nearest neighbour decides:
    assert M.place_new(two_gaps + [M.candidate(3, r * 0.9)], "x", r) == M.candidate(14, r)   # gap 3 has a place almost on it
    assert M.place_new(two_gaps + [M.candidate(14, r * 0.9)], "x", r) == M.candidate(3, r)


def test_candidates_are_evenly_spread_round_a_circle():
    pts = [M.candidate(i, 10) for i in range(M.CANDIDATES)]
    assert len(set(pts)) == M.CANDIDATES and all(math.hypot(*p) == pytest.approx(10, abs=0.01) for p in pts)
    assert dist(pts[0], pts[1]) == pytest.approx(2 * 10 * math.sin(math.pi / M.CANDIDATES), abs=0.02)
    assert pts[0] == (10.0, 0.0) and M.candidate(M.CANDIDATES // 4, 10) == (0.0, 10.0)


# --- keeping the layout ----------------------------------------------------------------------------------------------
def test_sync_places_everything_the_registry_lists_and_home_is_the_origin(tmp_path):
    s, st, *_ = make(tmp_path)
    got = M.sync(st, s, None)
    assert set(got) == {"workshop", "woods", "junkyard"} and got["workshop"] == (0.0, 0.0)
    assert math.hypot(*got["woods"]) == pytest.approx(8, abs=0.01) and math.hypot(*got["junkyard"]) == pytest.approx(15, abs=0.01)
    assert st.map_positions() == got


def test_a_place_keeps_its_spot_when_others_arrive_or_its_walk_changes(tmp_path):
    s, st, *_ = make(tmp_path)
    first = M.sync(st, s, None)
    neighbor(st)
    saltholm(st, "real")
    second = M.sync(st, s, None)
    assert {k: second[k] for k in first} == first and set(second) - set(first) == {"Marigold's home", "Saltholm"}
    assert math.hypot(*second["Saltholm"]) == pytest.approx(33, abs=0.01)
    st.update_place("Saltholm", walk_minutes=5.0)
    assert M.sync(st, s, None) == second                                       # nothing is ever moved


def test_a_removed_place_leaves_the_map_but_returns_to_the_same_spot(tmp_path):
    s, st, *_ = make(tmp_path)
    spots = M.sync(st, s, None)
    s.wild_places = ["junkyard"]
    assert "woods" not in M.sync(st, s, None) and "woods" in st.map_positions()
    s.wild_places = ["woods", "junkyard"]
    assert M.sync(st, s, None) == spots


def test_positions_survive_a_restart(tmp_path):
    s, st, *_ = make(tmp_path)
    spots = M.sync(st, s, None)
    from app.state import State
    assert State(s).map_positions() == spots


# --- the picture ----------------------------------------------------------------------------------------------------
def test_the_snapshot_describes_each_place_by_kind_and_what_pip_knows_of_it(tmp_path):
    s, st, *_ = make(tmp_path)
    neighbor(st)
    saltholm(st)                                               # heard of, never visited
    st.log("arrived", place="woods", label="the woods", first_time=True, description="trees")
    snap = M.snapshot(st, s, None, time.time())
    by = {p["key"]: p for p in snap["places"]}
    assert snap["home"] == "workshop" and set(by) == {"workshop", "woods", "junkyard", "Marigold's home", "Saltholm"}
    kinds = {k: p["kind"] for k, p in by.items()}
    assert kinds == {"workshop": "home", "woods": "wild", "junkyard": "wild", "Marigold's home": "neighbor", "Saltholm": "shop"}
    assert by["woods"]["visited"] is True and by["junkyard"]["visited"] is False and by["Saltholm"]["visited"] is False
    assert by["Saltholm"]["heard_only"] is True and by["woods"]["heard_only"] is False
    assert by["Saltholm"]["distance_minutes"] == 33.0 and by["woods"]["distance_minutes"] == 8
    assert by["woods"]["label"] == "the woods" and by["Marigold's home"]["label"] == "Marigold's home" and by["Saltholm"]["label"] == "Saltholm"
    assert (by["woods"]["x"], by["woods"]["y"]) == st.map_positions()["woods"]
    st.update_place("Saltholm", status="real")
    assert {p["key"]: p for p in M.snapshot(st, s, None, time.time())["places"]}["Saltholm"]["heard_only"] is False


def test_pip_is_marked_where_it_is(tmp_path):
    s, st, *_ = make(tmp_path)
    here = M.snapshot(st, s, None, time.time())["pip"]
    assert here == {"x": 0.0, "y": 0.0, "at": "workshop", "walking": None}
    st.update_agent(location="woods")
    pip = M.snapshot(st, s, None, time.time())["pip"]
    assert (pip["x"], pip["y"]) == st.map_positions()["woods"] and pip["at"] == "woods" and pip["walking"] is None
    st.update_agent(location="nowhere-we-know")
    assert M.snapshot(st, s, None, time.time())["pip"] == {"x": 0.0, "y": 0.0, "at": "nowhere-we-know", "walking": None}


def _walk(st, origin, target, started, ends):
    st.update_agent(location=origin)
    st.start_session(0, 0, 10, ends, kind="walk", target=target)
    st.db.execute("UPDATE work_session SET started_at = ?", (started,))
    st.db.commit()


def test_pip_is_drawn_part_of_the_way_along_a_walk(tmp_path):
    s, st, *_ = make(tmp_path)
    spots = M.sync(st, s, None)
    t = 1000.0
    _walk(st, "workshop", "woods", t, t + 600)
    pip = M.snapshot(st, s, None, t + 150)["pip"]
    assert pip["at"] is None and pip["walking"] == {"from": "workshop", "to": "woods", "progress": 0.25}
    assert (pip["x"], pip["y"]) == pytest.approx((spots["woods"][0] * 0.25, spots["woods"][1] * 0.25), abs=0.01)
    _walk(st, "junkyard", "woods", t, t + 100)
    pip = M.snapshot(st, s, None, t + 50)["pip"]
    mid = ((spots["junkyard"][0] + spots["woods"][0]) / 2, (spots["junkyard"][1] + spots["woods"][1]) / 2)
    assert (pip["x"], pip["y"]) == pytest.approx(mid, abs=0.01) and pip["walking"]["progress"] == 0.5


def test_walk_progress_is_clamped_and_a_zero_length_walk_has_arrived(tmp_path):
    s, st, *_ = make(tmp_path)
    spots = M.sync(st, s, None)
    _walk(st, "workshop", "woods", 1000.0, 1100.0)
    assert M.snapshot(st, s, None, 900.0)["pip"]["walking"]["progress"] == 0.0
    late = M.snapshot(st, s, None, 5000.0)["pip"]
    assert late["walking"]["progress"] == 1.0 and (late["x"], late["y"]) == pytest.approx(spots["woods"], abs=0.01)
    _walk(st, "workshop", "woods", 1000.0, 1000.0)
    assert M.snapshot(st, s, None, 1000.0)["pip"]["walking"]["progress"] == 1.0
    _walk(st, "workshop", "unknown-place", 1000.0, 1100.0)
    assert M.snapshot(st, s, None, 1050.0)["pip"]["walking"] == {"from": "workshop", "to": "unknown-place", "progress": 0.5}
    st.end_session()
    st.start_session(1, 0, 30, 2000.0, kind="work")                          # work is not a trip
    assert M.snapshot(st, s, None, 1500.0)["pip"]["walking"] is None


# --- the endpoint ---------------------------------------------------------------------------------------------------
def test_the_map_endpoint_returns_the_snapshot_and_grows_the_map(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", persona_default_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        body = c.get("/map").json()
        assert body["home"] == "workshop" and {p["key"] for p in body["places"]} >= {"workshop", "woods", "junkyard"}
        assert body["pip"]["at"] == "workshop" and set(body["pip"]) == {"x", "y", "at", "walking"}
        before = {p["key"]: (p["x"], p["y"]) for p in body["places"]}
        c.app.state.agent.state.add_character("Marigold", "neighbor", "a beekeeper", "persona", 60, "", 0)
        after = {p["key"]: (p["x"], p["y"]) for p in c.get("/map").json()["places"]}
        assert "Marigold's home" in after and {k: after[k] for k in before} == before


def test_the_dashboard_has_a_map_section_wired_to_the_endpoint(tmp_path):
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/x", persona_default_path="/x", pacing="manual")
    with TestClient(create_app(s, FakeBackend())) as c:
        page, js, css = (c.get(f"/ui/{f}").text for f in ("index.html", "app.js", "style.css"))
    assert 'id="map"' in page and 'id="map-where"' in page and page.index('id="map"') < page.index('id="garden"')
    assert "api('/map')" in js and "refreshMap" in js and "renderMap" in js
    assert "e.kind === 'arrived'" in js and "name === 'world'" in js                      # refreshed on arrival and when the tab opens
    assert ".map svg" in css and "map-pip" in css and "prefers-reduced-motion" in css


# --- the details that decide the picture -----------------------------------------------------------------------------
def test_the_first_angle_a_name_tries_is_pinned():
    assert [M.start_index(k) for k in ("woods", "junkyard", "Saltholm", "SALTHOLM", "workshop")] == [16, 21, 6, 6, 20]


def test_candidate_spots_are_rounded_to_hundredths():
    assert M.candidate(1, 10) == (9.66, 2.59) and M.candidate(5, 7) == (1.81, 6.76)


def test_every_spot_taken_still_places_the_new_one_at_its_first_angle():
    r = 12
    full = [M.candidate(i, r) for i in range(M.CANDIDATES)]
    assert M.place_new(full, "woods", r) == M.candidate(M.start_index("woods"), r)


def test_equally_roomy_gaps_go_to_the_first_one_tried_and_clearly_roomier_ones_win(monkeypatch):
    r, name = 12, "woods"
    monkeypatch.setattr(M, "start_index", lambda key: 0)
    twin_gaps = [M.candidate(i, r) for i in range(M.CANDIDATES) if i not in (5, 19)]   # mirror images across the x axis: exactly as roomy
    assert M.place_new(twin_gaps, name, r) == M.candidate(5, r)                  # a tie: the first in the order it tries them
    monkeypatch.setattr(M, "start_index", lambda key: 12)
    assert M.place_new(twin_gaps, name, r) == M.candidate(19, r)                 # ...which depends on where it starts, going forward


@pytest.mark.parametrize("name", ["a", "b", "c", "d", "e", "f"])
def test_the_roomier_gap_wins_whichever_angle_a_name_starts_from(name):
    far = 40
    gaps = [M.candidate(i, far) for i in range(M.CANDIDATES) if i not in (3, 14)]
    assert M.place_new(gaps + [M.candidate(3, far - 6.0), M.candidate(14, far - 6.5)], name, far) == M.candidate(14, far)


def test_a_mounted_library_is_on_the_map_with_its_own_kind_and_the_settings_walk(tmp_path):
    s, st, *_ = make(tmp_path, walk_minutes=25)
    neighbor(st)
    snap = M.snapshot(st, s, FakeLibrary(), time.time())                      # the very first look lays the map out
    by = {p["key"]: p for p in snap["places"]}
    assert by["library"]["kind"] == "library" and by["library"]["label"] == "the library"
    assert by["library"]["distance_minutes"] == 25 and by["Marigold's home"]["distance_minutes"] == 25
    assert math.hypot(by["library"]["x"], by["library"]["y"]) == pytest.approx(25, abs=0.01)
    assert math.hypot(by["Marigold's home"]["x"], by["Marigold's home"]["y"]) == pytest.approx(25, abs=0.01)
    assert "library" in M.sync(st, s, FakeLibrary()) and "library" not in M.sync(st, s, None)


def test_walking_between_places_off_both_axes_and_rounding_to_hundredths(tmp_path):
    s, st, *_ = make(tmp_path)
    neighbor(st)
    saltholm(st, "real")
    spots = M.sync(st, s, None)
    (sx, sy), (ex, ey) = spots["Saltholm"], spots["Marigold's home"]
    assert sx != sy and ex != ey and sx != ex and sy != ey                      # no accidental symmetry to hide a swapped axis
    _walk(st, "Saltholm", "Marigold's home", 1000.0, 1003.0)
    pip = M.snapshot(st, s, None, 1001.0)["pip"]
    assert pip["x"] == round(sx + (ex - sx) / 3, 2) and pip["y"] == round(sy + (ey - sy) / 3, 2)
    assert pip["walking"]["progress"] == 0.33                                    # hundredths, like the coordinates
    _walk(st, "Saltholm", "Marigold's home", 1000.0, 1000.5)
    assert M.snapshot(st, s, None, 1000.25)["pip"]["walking"]["progress"] == 0.5   # a short walk is not "already there"


@pytest.mark.asyncio
async def test_the_offered_tools_are_described_for_the_place_and_a_closed_place_offers_nothing(tmp_path):
    from datetime import datetime
    from app import places as P
    from app import tools as T
    s, st, gm, agent = make(tmp_path, sleep=True)
    agent.tools = T.enabled_tools(Settings(tools=["gather", "say", "harvest"]))
    hour = datetime.now().hour
    s.bedtime_hour, s.wake_hour = (hour + 3) % 24, (hour + 8) % 24               # daytime
    st.update_agent(location="woods")
    offered = {sp.name: sp.description for sp in agent._specs()}
    own = P.registry(st, s, None)["woods"].verbs["gather"][1]
    assert set(offered) == {"gather", "say"} and offered["gather"] == own != T.REGISTRY["gather"][0].description  # worded for the woods
    s.bedtime_hour, s.wake_hour = hour, (hour + 8) % 24                           # night: the woods are closed
    assert {sp.name for sp in agent._specs()} == {"say"}
    st.update_agent(location="workshop")
    assert {sp.name for sp in agent._specs()} == {"say", "harvest"}
