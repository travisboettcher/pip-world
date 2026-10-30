import asyncio
import time
from datetime import datetime

import pytest

from app import memory as mem
from app import sleep as sl
from app.config import Settings
from tests.test_projects import FixedRng, call, make, report


def at(hour, day=2):
    return datetime(2026, 11, day, hour, 30).timestamp()


def night_now(s):
    """Make the real clock fall inside the night window, so tools that read the time see night."""
    h = datetime.now().hour
    s.bedtime_hour, s.wake_hour = h, (h + 8) % 24


def test_night_period_and_next_wake():
    s = Settings(bedtime_hour=22, wake_hour=6)
    assert [sl.is_night(s, at(h)) for h in (5, 6, 12, 21, 22, 23, 0)] == [True, False, False, False, True, True, True]
    assert [sl.period(s, at(h)) for h in (7, 13, 18, 23)] == ["morning", "afternoon", "evening", "night"]
    assert sl.next_wake(s, at(23)) == datetime(2026, 11, 3, 6).timestamp()   # tonight -> tomorrow morning
    assert sl.next_wake(s, at(2)) == datetime(2026, 11, 2, 6).timestamp()    # after midnight -> this morning


@pytest.mark.asyncio
async def test_sleep_tool_only_at_night_and_at_home(tmp_path):
    s, st, gm, agent = make(tmp_path, sleep=True)
    s.bedtime_hour, s.wake_hour = (datetime.now().hour + 3) % 24, (datetime.now().hour + 8) % 24  # it's daytime
    r = await call(agent, "sleep")
    assert "not time for bed" in r.text and st.agent()["activity"] != "sleeping"
    night_now(s)
    st.update_agent(location="library")
    assert "go_to home first" in (await call(agent, "sleep")).text
    st.update_agent(location="workshop")
    r = await call(agent, "sleep")
    assert "fall asleep" in r.text
    a = st.agent()
    assert a["activity"] == "sleeping" and float(st.meta("sleep_until")) > time.time()
    assert "already asleep" in (await call(agent, "sleep")).text


@pytest.mark.asyncio
async def test_going_to_bed_stops_work(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(craft="clockmaking", difficulty=2)], sleep=True)
    night_now(s)
    st.add_item("brass wire", 2, "material")
    await call(agent, "start_project", name="gear clock")
    await call(agent, "work_on", project="gear clock", minutes=60)
    r = await call(agent, "sleep")
    assert "stopped working on gear clock early" in r.text and not st.session()


def test_sleeping_recovers_faster_and_slows_hunger(tmp_path):
    s, st, *_ = make(tmp_path, sleep=True)
    now = time.time()
    st.update_agent(energy=0.2, hunger=0.2, activity="sleeping", updated_at=now - 3600)
    st.apply_decay(now)
    a = st.agent()
    assert a["energy"] == pytest.approx(0.2 + s.sleep_recover_per_hour) and a["hunger"] == pytest.approx(0.2 + s.hunger_per_hour / 2)


@pytest.mark.asyncio
async def test_waking_on_time_and_early(tmp_path):
    s, st, gm, agent = make(tmp_path, sleep=True)
    night_now(s)
    await call(agent, "sleep")
    st.set_meta(sleep_started=time.time() - 7 * 3600, sleep_until=time.time() - 10)
    await agent.tick("timer")
    e = [x for x in st.events(20) if x["kind"] == "woke"][0]["data"]
    assert e["hours"] == pytest.approx(7, abs=0.1) and not e["early"]
    assert st.agent()["activity"] != "sleeping"
    assert "the first time you woke from sleep" in agent._perception("timer", [])
    # a second night, woken early by a visitor
    await call(agent, "sleep")
    await agent.tick("event")
    e = [x for x in st.events(20) if x["kind"] == "woke"][0]["data"]
    assert e["early"] and "woken early" in agent._perception("event", [])


@pytest.mark.asyncio
async def test_only_visitors_wake_a_sleeper(tmp_path):
    s, st, gm, agent = make(tmp_path, sleep=True)
    night_now(s)
    await call(agent, "sleep")
    agent.pacing.next_delay = lambda now, last: 0.05
    agent.request_wake()  # a ripe crop, a letter, a hunger alert...
    with pytest.raises(asyncio.TimeoutError):  # ...and the heartbeat is stretched to the morning
        await asyncio.wait_for(agent._sleep(), timeout=0.3)
    agent.request_wake(urgent=True)  # a visitor
    assert await asyncio.wait_for(agent._sleep(), timeout=2) == "event"


def test_reflection_runs_once_per_sleep_with_a_fallback(tmp_path):
    s, st, gm, agent = make(tmp_path, sleep=True, reflect_hour=3)
    now = at(14)  # a time when the old fixed-hour rule would fire
    st.update_agent(activity="idle")
    assert mem.due(st, s, now)                       # never reflected, not sleeping: the fallback
    st.set_meta(last_reflection_ts=now - 3600, last_reflection_day="2026-11-01")
    assert not mem.due(st, s, now)                   # reflected recently: wait for sleep
    st.update_agent(activity="sleeping")
    st.set_meta(sleep_started="123.0")
    assert mem.due(st, s, now)                       # asleep and this sleep hasn't reflected
    st.set_meta(reflected_sleep="123.0")
    assert not mem.due(st, s, now)                   # once per sleep


def test_perception_gives_period_day_and_a_bed_hint(tmp_path):
    s, st, gm, agent = make(tmp_path, sleep=True)
    night_now(s)
    p = agent._perception("timer", [])
    assert "It is night; day 1 of your life here. You can go to bed (sleep)" in p
    s.bedtime_hour, s.wake_hour = (datetime.now().hour + 3) % 24, (datetime.now().hour + 8) % 24
    p = agent._perception("timer", [])
    assert "It is " in p and "go to bed" not in p
