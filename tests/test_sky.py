"""The sky (docs/DESIGN-world-packs.md, phase 5e): the shipped `sky` module asks the engine's `weather` source and publishes the world's
weather and season, which the scene, happenings, layouts and modules read; the agent sees it as "Outside"."""
import json
import time
from datetime import datetime

import pytest

from app import modules as M
from app import sources
from app import world_view as WV
from tests.test_modules import live, rule
from tests.test_projects import make

RAIN = {"condition": "rainy", "temp": 9.4, "unit": "C", "daylight": True, "next_rising": None, "next_setting": None}


def sky_says(st, weather=None, season=None):
    """A live module publishing the world's weather (and season), as the sky does."""
    m = M.live_named(st, "says") or live(st, rule(name="says"), "x")
    st.update_module(m["id"], facts={"weather": weather, **({"season": season} if season else {})})
    return m


def module(st, **params):
    man, src = M.library("sky")
    man.pop("reason", None)
    return live(st, {**man, "params": {**man["params"], **params}}, src, author=M.SHIPPED)


def reading(st, condition="rainy", temp=9.4, unit="°C", up=True, rising=None, setting=None, at=None):
    """A stored reading from the provider (weather.py), fresh."""
    now = at or time.time()
    st.set_meta(weather=json.dumps({"condition": condition, "temp": temp, "unit": unit, "above_horizon": up, "next_rising": rising,
                                    "next_setting": setting}), weather_at=now, weather_try_at=now)


def code():
    out = {}
    exec(M.library("sky")[1], out)
    return out


G = code()


async def test_the_sky_publishes_the_weather_and_the_season_and_says_whats_outside(tmp_path):
    s, st, gm, agent = make(tmp_path, modules="on", module_runner="local", weather=True, hass_token="t")
    now = time.time()
    reading(st, setting=now + 3600)
    m = module(st)
    r = await M.call(st, s, M.LocalRunner(), m, "on_install", now)
    assert r["ok"] and not r["refused"]
    m = M.live_named(st, "sky")
    assert m["facts"]["weather"] == {"condition": "rainy", "temp": 9.4, "unit": "°C", "daylight": True, "next_rising": None, "next_setting": now + 3600}
    assert m["facts"]["season"] == G["season"]({"now": now, "time": {"utc_offset": round(datetime.fromtimestamp(now).astimezone().utcoffset().total_seconds())},
                                               "params": {"hemisphere": "north"}})
    sets = datetime.fromtimestamp(now + 3600).strftime("%-I:%M %p")
    assert m["standing"]["lines"] == [f"rain, 9 °C; the sun sets at {sets}."] and m["due"] == pytest.approx(now + 600)
    assert f"Outside:\n- rain, 9 °C; the sun sets at {sets}." in agent._perception("x", [])
    assert WV.moment(st, s, now)["weather"] == "rainy" and M.context(st, s, live(st, rule(name="eye", reads=["weather"]), "x"), now)["weather"] == \
        {"condition": "rainy", "temp": 9.4, "unit": "°C", "daylight": True}


async def test_without_the_weather_the_sky_still_keeps_the_season(tmp_path):
    s, st, gm, agent = make(tmp_path, modules="on", module_runner="local", weather=False)
    m = module(st, hemisphere="south")
    assert not sources.available("weather")
    await M.call(st, s, M.LocalRunner(), m, "on_install", time.time())
    m = M.live_named(st, "sky")
    assert m["facts"]["weather"] is None and m["facts"]["season"] in ("winter", "spring", "summer", "autumn") and m["standing"] == {}
    assert WV.moment(st, s, time.time())["weather"] is None and "Outside" not in agent._perception("x", [])


def test_seasons_go_round_the_right_way_for_the_hemisphere():
    for month, north, south in ((1, "winter", "summer"), (4, "spring", "autumn"), (7, "summer", "winter"), (10, "autumn", "spring"), (12, "winter", "summer")):
        ts = time.mktime((2026, month, 15, 12, 0, 0, 0, 0, -1))
        off = round(datetime.fromtimestamp(ts).astimezone().utcoffset().total_seconds())
        for hemi, want in (("north", north), ("south", south)):
            assert G["season"]({"now": ts, "time": {"utc_offset": off}, "params": {"hemisphere": hemi}}) == want, (month, hemi)


def test_how_the_sky_is_worded():
    assert G["clock"](0, 0) == "12:00 AM" and G["clock"](13 * 3600 + 5 * 60, 0) == "1:05 PM" and G["clock"](12 * 3600, 0) == "12:00 PM"
    assert G["clock"](3600, -7200) == "11:00 PM" and G["clock"](11 * 3600 + 59 * 60, 0) == "11:59 AM"
    assert G["line"]({**RAIN, "temp": None}, 0) == "rain." and G["line"]({**RAIN, "condition": "odd-thing_here"}, 0) == "odd thing here, 9 C."
    assert G["line"]({**RAIN, "daylight": False, "next_rising": 6 * 3600, "next_setting": 18 * 3600}, 0) == "rain, 9 C; the sun rises at 6:00 AM."
    assert G["line"]({**RAIN, "next_setting": 18 * 3600 + 30 * 60}, 0) == "rain, 9 C; the sun sets at 6:30 PM."


def test_the_engine_reads_the_published_season_and_falls_back_to_its_own(tmp_path):
    from app.happenings import season_of
    s, st, gm, agent = make(tmp_path)
    now = time.time()
    assert M.world_season(st, s, now) == season_of(now, s.hemisphere) and M.published(st, "season") is None and M.published(st, "x", 3) == 3
    sky_says(st, RAIN, "midwinter")
    assert M.world_season(st, s, now) == "midwinter" and WV.moment(st, s, now)["season"] == "midwinter"
    from app import happenings as H, layouts as L
    s.happenings_seasons = True
    assert H.world(st, s, now)["season"] == "midwinter" and L.season(s, now, st) == "midwinter" and L.season(s, now) == season_of(now, s.hemisphere)
    sky_says(st, RAIN, "")
    assert M.world_season(st, s, now) == season_of(now, s.hemisphere)                       # nothing said: the engine's reckoning


async def test_the_weather_source_reads_the_sky_at_most_every_ten_minutes(tmp_path, monkeypatch):
    from app import weather as W
    s, st, gm, agent = make(tmp_path, weather=True, hass_token="t")
    got = []

    async def fetch(self, http=None):
        got.append(1)
        return W.Weather("snowy", -2.0, "C", False, 1000.0, None)
    monkeypatch.setattr(W.PROVIDERS["homeassistant"], "fetch", fetch)
    assert sources.available("weather") and sources.get("weather").ops == ("now",)
    r = await sources.ask("weather", "now", {}, s, 1)
    assert r == {"reading": {"condition": "snowy", "temp": -2.0, "unit": "C", "daylight": False, "next_rising": 1000.0, "next_setting": None}}
    await sources.ask("weather", "now", {}, s, 1)
    assert len(got) == 1
    s.weather = False
    assert not sources.available("weather")
    s.weather, s.hass_token = True, ""
    assert not sources.available("weather")


async def test_no_fresh_reading_no_weather_and_only_live_modules_speak_for_the_world(tmp_path, monkeypatch):
    from app import weather as W
    from app.happenings import season_of
    s, st, gm, agent = make(tmp_path, weather=True, hass_token="t")

    async def nothing(self, http=None):
        return None
    monkeypatch.setattr(W.PROVIDERS["homeassistant"], "fetch", nothing)
    assert await sources.ask("weather", "now", {}, s, 1) == {"reading": None}
    m = sky_says(st, RAIN, "midwinter")
    M.disable(st, m["id"])
    now = time.time()
    assert M.published(st, "weather") is None and M.world_season(st, s, now) == season_of(now, s.hemisphere)
    other = live(st, rule(name="odd"), "x")
    st.update_module(other["id"], facts={"season": 3})
    assert M.world_season(st, s, now) == season_of(now, s.hemisphere)                     # not a season's name: the engine's reckoning


async def test_places_are_built_for_the_published_season_and_rebuilt_when_it_turns(tmp_path):
    from app import layouts as L
    from tests.test_layouts import NOW, laid_out, part_man, place_man
    from tests.test_modules import modular
    s, st, agent = modular(tmp_path, modules_approval="")
    sky_says(st, None, "midwinter")
    echo = ('def on_build(ctx):\n    return {"shapes": [{"shape": "box", "size": [1, 1, 1], "at": [0, 0, 0], "material": {"color": "#000"},'
            ' "tip": {"title": ctx["season"], "text": "x"}}]}\n')
    part = await M.propose(st, s, agent.runner, "world", part_man("echo"), echo, now=NOW)
    assert part["status"] == "live" and part["report"]["clean"]
    plan = ('def on_build(ctx):\n    return {"parts": [{"part": "echo", "at": [0, 0, 0]}], "shapes": [{"shape": "box", "size": [1, 1, 1], "at": [0, 0, 0],'
            ' "material": {"color": "#000"}, "tip": {"title": ctx["season"], "text": "x"}}]}\n')
    p = await M.propose(st, s, agent.runner, "world", place_man(), plan, now=NOW)
    b = await L.build_place(st, s, agent.runner, st.module(p["id"]), NOW)
    assert b["season"] == "midwinter" and [x["tip"]["title"] for x in b["shapes"]] == ["midwinter", "midwinter"]
    (tmp_path / "two").mkdir()
    s2, st2, agent2, m = await laid_out(tmp_path / "two")
    sky_says(st2, None, "midwinter")
    await L.step(st2, s2, agent2.runner, NOW)
    assert st2.module(m["id"])["built"]["season"] == "midwinter" and not L.stale(st2, s2, st2.module(m["id"]), NOW)
    sky_says(st2, None, "thaw")
    assert L.stale(st2, s2, st2.module(m["id"]), NOW)                                             # the season the sky says turned


def test_without_seasons_happenings_know_none(tmp_path):
    from app import happenings as H
    s, st, gm, agent = make(tmp_path)
    sky_says(st, None, "midwinter")
    s.happenings_seasons = False
    assert H.world(st, s, time.time())["season"] is None
