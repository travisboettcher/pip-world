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
async def test_sleep_tool_works_any_time_but_only_at_home(tmp_path):
    s, st, gm, agent = make(tmp_path, sleep=True)
    s.bedtime_hour, s.wake_hour = (datetime.now().hour + 3) % 24, (datetime.now().hour + 8) % 24  # it's daytime
    st.update_agent(location="library")
    assert "go_to home first" in (await call(agent, "sleep")).text and st.agent()["activity"] != "sleeping"
    st.update_agent(location="workshop")
    r = await call(agent, "sleep")                    # no "not time for bed": Pip may go whenever it likes
    assert "fall asleep" in r.text and "not time for bed" not in r.text
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
    assert a["energy"] == pytest.approx(0.2 + 0.25) and a["hunger"] == pytest.approx(0.2 + 0.08 / 2)        # Pip's world, asleep


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
    usual = datetime(2000, 1, 1, s.bedtime_hour).strftime("%-I %p").lower()
    assert "It is " in p and f"You usually go to bed around {usual}" in p
    assert "sleep" in p and "whenever" in p           # sleeping isn't forbidden by day, just not the habit


# --- boundaries of the pure rules ------------------------------------------------
def test_night_window_edges_and_degenerate_settings():
    same = Settings(bedtime_hour=6, wake_hour=6)
    assert not any(sl.is_night(same, at(h)) for h in range(24))               # no night at all
    early = Settings(bedtime_hour=1, wake_hour=5)                              # a window that doesn't wrap midnight
    assert [sl.is_night(early, at(h)) for h in (0, 1, 4, 5)] == [False, True, True, False]


def test_period_edges():
    s = Settings(bedtime_hour=22, wake_hour=6)
    assert [sl.period(s, at(h)) for h in (11, 12, 16, 17)] == ["morning", "afternoon", "afternoon", "evening"]


def test_next_wake_is_on_the_hour_and_strictly_in_the_future():
    s = Settings(bedtime_hour=22, wake_hour=6)
    mid = datetime(2026, 11, 2, 23, 15, 42, 500).timestamp()
    assert sl.next_wake(s, mid) == datetime(2026, 11, 3, 6).timestamp()        # no stray seconds
    exactly = datetime(2026, 11, 2, 6).timestamp()
    assert sl.next_wake(s, exactly) == datetime(2026, 11, 3, 6).timestamp()    # at the wake hour: tomorrow's


def test_day_number_counts_from_birth(tmp_path):
    s, st, *_ = make(tmp_path, sleep=True)
    st.set_meta(born_at=1000.0)
    assert [sl.day_number(st, 1000.0 + x) for x in (-500, 0, 86399, 86400, 86400 * 3 + 5)] == [1, 1, 1, 2, 4]


def test_fall_asleep_records_the_night(tmp_path):
    s, st, *_ = make(tmp_path, sleep=True)
    now = at(23)
    r = sl.fall_asleep(st, s, now)
    a = st.agent()
    assert r == {"until": sl.next_wake(s, now)}
    assert (a["activity"], a["description"]) == ("sleeping", "asleep")
    assert float(st.meta("sleep_started")) == now and float(st.meta("sleep_until")) == r["until"]
    t0 = time.time()
    sl.fall_asleep(st, s)                                                      # no time given: now
    assert float(st.meta("sleep_started")) >= t0


def test_wake_up_reports_hours_and_clears_the_bed(tmp_path):
    s, st, *_ = make(tmp_path, sleep=True)
    assert sl.wake_up(st, at(6)) is None                                       # not asleep: nothing happens
    st.update_agent(activity="sleeping", description="asleep")
    st.set_meta(sleep_started=1000.0, sleep_until=1000.0 + 8 * 3600)
    assert sl.wake_up(st, 1000.0 + 7.74 * 3600) == {"hours": 7.7, "early": True}
    a = st.agent()
    assert (a["activity"], a["description"]) == ("idle", "") and st.meta("sleep_until") == "0"
    logged = [e["data"] for e in st.events(5) if e["kind"] == "woke"]
    assert [(d["hours"], d["early"]) for d in logged] == [(7.7, True)]
    for now, early in ((1000.0 + 8 * 3600 - 61, True), (1000.0 + 8 * 3600 - 60, False), (1000.0 + 8 * 3600, False)):
        st.update_agent(activity="sleeping")
        st.set_meta(sleep_started=1000.0, sleep_until=1000.0 + 8 * 3600)
        assert sl.wake_up(st, now)["early"] is early                           # a minute's grace
    st.update_agent(activity="sleeping")
    st.set_meta(sleep_started=1000.0, sleep_until=1000.0 + 8 * 3600)
    assert sl.wake_up(st, 1000.0 + 7 * 3600)["hours"] == 7.0


def test_woke_text_wording():
    assert sl.woke_text({"hours": 7.0, "early": False}) == "you woke after about 7 hours of sleep"
    assert sl.woke_text({"hours": 2.5, "early": True}) == ("you woke after about 2.5 hours of sleep; "
                                                           "you were woken early; you can go back to sleep")


def test_usual_bedtime_wording(tmp_path):
    s, st, *_ = make(tmp_path, sleep=True)
    st.set_meta(born_at=at(0))
    for bed, words in ((22, "10 pm"), (9, "9 am"), (0, "12 am"), (13, "1 pm")):
        s.bedtime_hour, s.wake_hour = bed, (bed + 8) % 24
        day = next(h for h in range(24) if not sl.is_night(s, at(h)))
        assert sl.perception(st, s, at(day)) == [
            f"It is {sl.period(s, at(day))}; day 1 of your life here. You usually go to bed around {words}, "
            "but you can sleep whenever you like (you'd wake in the morning)."]


def test_perception_is_empty_when_sleep_is_off(tmp_path):
    s, st, *_ = make(tmp_path, sleep=False)
    assert sl.perception(st, s, at(12)) == []
