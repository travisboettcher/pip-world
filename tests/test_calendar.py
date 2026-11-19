"""The calendar (the owner, 2026-11-19): a section of the journal for commitments with a time. Pip had carried "Thursday at half past
four" at Oriel's as a to-do for weeks, restating it every wake and keeping it on the wrong day; Sela promised to be at Wren's in the
morning with nothing to bring it back. A commitment has a time (the engine reads "Thursday 16:30"), maybe a place and a weekly repeat;
the agent sees what's coming with when to set off, is woken when it's time to go, and the engine says whether it was kept."""
import time
from datetime import datetime

import pytest

from app import calendar as cal, places
from app import tools as T
from tests.test_projects import call, make

THU = datetime(2026, 11, 19, 10, 0).timestamp()        # a Thursday morning


def at(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute).timestamp()


def test_the_engine_reads_when():
    assert cal.parse("Thursday 16:30", THU) == at(19, 16, 30)                     # later today
    assert cal.parse("thursday 9:00", THU) == at(26, 9)                            # already past today: next week
    assert cal.parse("Friday 4:30 pm", THU) == at(20, 16, 30)
    assert cal.parse("tomorrow morning", THU) == at(20, 8)
    assert cal.parse("tomorrow 7am", THU) == at(20, 7)
    assert cal.parse("today noon", THU) == at(19, 12)
    assert cal.parse("today evening", THU) == at(19, 18)
    assert cal.parse("2026-11-24 09:15", THU) == at(24, 9, 15)
    assert cal.parse("Saturday afternoon", THU) == at(21, 14)
    assert cal.parse("Sunday", THU) == at(22, 8)                                   # a day alone: the morning
    for bad in ("", "sometime", "Thursday 25:00", "the 31st", "yesterday 9:00", "2026-11-18 09:00", "today 8:00"):
        assert cal.parse(bad, THU) is None, bad                                    # unreadable, or already past


def test_the_calendar_is_a_section_of_the_journal(tmp_path):
    s, st, gm, agent = make(tmp_path)
    agent.tools.update({n: T.REGISTRY[n] for n in ("note_to_self", "resolve_note")})
    r = T.REGISTRY["note_to_self"][1]
    ctx = agent.ctx
    import asyncio
    run = lambda **a: asyncio.run(r(ctx, a))
    out = run(section="calendar", text="Visit Oriel with a carrot", when="Thursday 16:30", where="workshop", repeat="weekly")
    assert out.text.startswith("in your calendar: Thursday ") and out.text.endswith(", at home, every week")
    (item,) = st.memories("calendar")
    assert item["text"] == "Visit Oriel with a carrot" and item["place"] == places.home_key() and item["every"] == 7 * 86400
    assert item["due_at"] > time.time() - 7 * 86400
    assert run(section="calendar", text="x").text == "error: a calendar entry needs `when` (like 'Thursday 16:30' or 'tomorrow morning')"
    assert run(section="calendar", text="x", when="someday").text.startswith("error: I can't read 'someday' as a time")
    assert run(section="calendar", text="x", when="tomorrow 9:00", where="Atlantis").text.startswith("error: you don't know a place called 'Atlantis'")
    assert run(section="calendar", text="x", when="tomorrow 9:00", repeat="monthly").text == "error: repeat is weekly, or leave it out"
    assert run(section="todo", text="On Thursday go and visit Oriel with a carrot at half past four").text.startswith(
        f"not written: that's in your calendar (#{item['id']}), which will remind you")
    assert run(section="todo", text="Sweep the workshop floor").text == "wrote in todo"
    assert asyncio.run(T.REGISTRY["resolve_note"][1](ctx, {"id": item["id"], "outcome": "called off"})).text == f"crossed off #{item['id']}"
    assert st.memories("calendar", status="open") == []


def test_what_is_coming_with_when_to_set_off(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.add_memory("Visit Oriel", "calendar", due_at=at(19, 16, 30), place="woods")
    st.add_memory("Market day", "calendar", due_at=at(21, 9))
    st.add_memory("Far off", "calendar", due_at=at(28, 9))
    lines = cal.lines(st, s, None, THU)
    walk = round(places.registry(st, s, None)["woods"].walk_minutes)
    assert lines[0] == "Your calendar (what's coming; it will remind you):"
    assert lines[1].startswith(f"- Thursday 19 November, 4:30 pm (today, in about 6 hours) at the woods: Visit Oriel (#")
    assert lines[1].endswith(f"; a {walk}-minute walk: set off by 4:{30 - walk:02d} pm)") if walk < 30 else True
    assert lines[2].startswith("- Saturday 21 November, 9:00 am (in 2 days): Market day")
    assert len(lines) == 3                                                           # only the next few days
    soon = cal.lines(st, s, None, at(19, 16, 30) - walk * 60 + 30)
    assert soon[1].startswith("- It's time to set off: Visit Oriel at the woods, at 4:30 pm")
    assert cal.lines(st, s, None, at(19, 16, 30) - walk * 60 + 30, here="woods")[1].startswith("- Now, here: Visit Oriel")


def test_it_wakes_the_agent_once_when_its_time_to_go(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.add_memory("Visit Oriel", "calendar", due_at=at(19, 16, 30), place="woods")
    walk = places.registry(st, s, None)["woods"].walk_minutes
    assert cal.step(st, s, None, at(19, 15)) is False
    assert cal.step(st, s, None, at(19, 16, 30) - walk * 60 - 1) is False           # not a second early
    assert cal.step(st, s, None, at(19, 16, 30) - walk * 60) is True                # time to set off
    assert cal.walk_minutes(st, s, None, "nowhere-known") == 0.0
    assert cal.step(st, s, None, at(19, 16, 30) - walk * 60 + 60) is False          # once
    st.add_memory("Nap", "calendar", due_at=at(19, 17))                               # no place: woken at its time
    assert cal.step(st, s, None, at(19, 17)) is True


def test_kept_missed_and_weekly(tmp_path):
    s, st, gm, agent = make(tmp_path)
    kept = st.add_memory("Visit Oriel", "calendar", due_at=at(19, 16, 30), place="woods", every=7 * 86400)
    missed = st.add_memory("Help Wren with the vent", "calendar", due_at=at(19, 9), place="junkyard")
    plain = st.add_memory("Think of Marta", "calendar", due_at=at(19, 12))
    st.update_agent(location="woods")
    cal.step(st, s, None, at(19, 16, 40))                                            # there in time
    st.update_agent(location=places.home_key())
    cal.step(st, s, None, at(19, 17, 31))                                            # an hour after: settled
    rows = {m["id"]: m for m in st.memories("calendar", status=None, limit=20)}
    assert rows[kept]["status"] == "open" and rows[kept]["due_at"] == at(26, 16, 30)  # weekly: on to next week
    assert (rows[missed]["status"], rows[missed]["outcome"]) == ("done", "missed")
    assert (rows[plain]["status"], rows[plain]["outcome"]) == ("done", "its time came")
    told = [(e["data"]["text"], e["data"]["outcome"]) for e in reversed(st.events(20)) if e["kind"] == "calendar"]
    assert sorted(told) == [("Help Wren with the vent", "missed"), ("Think of Marta", "its time came"), ("Visit Oriel", "kept")]
    lines = cal.lines(st, s, None, at(19, 17, 32))
    assert "- You missed: Help Wren with the vent (Thursday 19 November, 9:00 am, at the junkyard)" in lines
    assert "- You missed: Help Wren with the vent (Thursday 19 November, 9:00 am, at the junkyard)" not in cal.lines(st, s, None, at(19, 17, 33))  # told once
    assert cal.lines(st, s, None, at(19, 17, 33)) == []                              # next week's is beyond the next few days
    assert cal.lines(st, s, None, at(24, 9))[1].startswith("- Thursday 26 November, 4:30 pm (in 2 days) at the woods: Visit Oriel")


@pytest.mark.asyncio
async def test_the_calendar_reaches_the_agents_turn_and_its_monitor(tmp_path):
    s, st, gm, agent = make(tmp_path)
    st.add_memory("Visit Oriel", "calendar", due_at=time.time() + 3600, place="woods")
    assert "Your calendar (what's coming; it will remind you):" in agent._perception("timer", [])
    st.add_memory("Feed the cat", "calendar", due_at=time.time() + 1)
    agent._wake.clear()
    time.sleep(1.05)
    agent.check()
    assert agent._wake.is_set()


def test_reading_and_saying_times_at_their_edges():
    assert [cal.parse(w, THU) for w in ("Friday 12 am", "Friday 12 pm", "Friday 1 am", "Friday 0:00", "Friday 23:59", "Friday at 9:00",
                                         "  FRIDAY   9:00 ", "Friday 9")] == \
        [at(20, 0), at(20, 12), at(20, 1), at(20, 0), at(20, 23, 59), at(20, 9), at(20, 9), at(20, 9)]
    for bad in ("Friday 13 pm", "Friday 0 am", "Friday 24:00", "Friday 9:60", "Friday at", "at Friday 9:00"):
        assert cal.parse(bad, THU) is None, bad
    assert cal.parse("Thursday 10:00", THU) == at(26, 10) and cal.parse("today 10:00", THU) is None   # its very moment is gone
    assert cal.parse("Thursday 10:01", THU) == at(19, 10, 1) and cal.parse("Wednesday 9:00", THU) == at(25, 9)
    assert datetime.fromtimestamp(cal.parse("Friday 9:30", THU + 17.5)).second == 0                  # on the minute
    assert (cal.say_when(at(20, 0)), cal.say_when(at(20, 12, 5)), cal.say_when(at(20, 23))) == \
        ("Friday 20 November, 12:00 am", "Friday 20 November, 12:05 pm", "Friday 20 November, 11:00 pm")
    assert (cal.clock(at(20, 0, 7)), cal.clock(at(20, 12)), cal.clock(at(20, 11, 59))) == ("12:07 am", "12:00 pm", "11:59 am")
    assert [cal._until(THU + h * 3600, THU) for h in (0.4, 0.6, 1, 2, 14.1)] == \
        ["today, within the hour", "today, in about 1 hour", "today, in about 1 hour", "today, in about 2 hours", "tomorrow"]
    assert cal._until(at(22, 9), THU) == "in 3 days"


def test_the_calendar_at_its_edges(tmp_path):
    import asyncio
    s, st, gm, agent = make(tmp_path)
    r = lambda **a: asyncio.run(T.REGISTRY["note_to_self"][1](agent.ctx, a))
    for args in ({"when": ""}, {"when": "someday"}, {"when": "tomorrow 9:00", "where": "Atlantis"}, {"when": "tomorrow 9:00", "repeat": "daily"}):
        assert r(section="calendar", text="x", **args).followup is True, args
    assert "(you know: " in r(section="calendar", text="x", when="tomorrow 9:00", where="Atlantis").text
    out = r(section="calendar", text="Gather at the woods", when="tomorrow 9:00", where="woods", repeat="")
    assert out.text.endswith(", at the woods") and not out.followup
    assert r(section="calendar", text="Think quietly", when="tomorrow 10:00").text == "in your calendar: Friday 20 November, 10:00 am"   # no place
    assert r(section="calendar", text="Sit by the fire", when="tomorrow 11:00").text.endswith("November, 11:00 am")
    assert r(section="calendar", text="Gather at the woods", when="tomorrow 9:00").text.startswith("not written: too close to your note")
    rows = {m["text"]: m for m in st.memories("calendar")}
    assert rows["Gather at the woods"]["every"] == 0 and rows["Think quietly"]["place"] == "" and set(rows) == {"Gather at the woods", "Think quietly", "Sit by the fire"}
    st.add_memory("an old note", "todo")
    assert [m["text"] for m in cal.open_items(st)] == ["Gather at the woods", "Think quietly", "Sit by the fire"]   # soonest first, the calendar only


def test_kept_and_settled_on_the_minute(tmp_path):
    s, st, gm, agent = make(tmp_path)
    due = at(19, 16)
    first = st.add_memory("Visit", "calendar", due_at=due, place="woods")
    st.update_agent(location="woods")
    cal.step(st, s, None, due - cal.EARLY)                                          # just in the window: kept
    st.update_agent(location=places.home_key())
    cal.step(st, s, None, due + cal.LATE)                                           # an hour after, to the second: not yet settled
    assert st.memories("calendar", status="open")[0]["id"] == first
    cal.step(st, s, None, due + cal.LATE + 1)
    (ev,) = [e["data"] for e in st.events(10) if e["kind"] == "calendar"]
    assert (ev["id"], ev["outcome"], ev["due_at"], ev["place"]) == (first, "kept", due, "woods")
    late = st.add_memory("Late", "calendar", due_at=due + 7200, place="woods")
    st.update_agent(location="woods")
    cal.step(st, s, None, due + 7200 + cal.LATE + 1)                                # there, but after the window: missed
    assert [e["data"]["outcome"] for e in st.events(10) if e["kind"] == "calendar"][0] == "missed"
    weekly = st.add_memory("Weekly", "calendar", due_at=due + 3 * 86400, place="woods", every=cal.WEEK)
    cal.step(st, s, None, due + 3 * 86400 + 2 * cal.WEEK + cal.LATE + 1)            # weeks went by: the next one to come
    assert [m["due_at"] for m in st.memories("calendar", status="open") if m["id"] == weekly] == [due + 3 * 86400 + 3 * cal.WEEK]
    assert late


def test_what_is_shown_at_its_edges(tmp_path):
    s, st, gm, agent = make(tmp_path)
    walk = places.registry(st, s, None)["woods"].walk_minutes
    due = at(19, 16)
    st.add_memory("Visit", "calendar", due_at=due, place="woods")
    st.add_memory("Edge", "calendar", due_at=THU + cal.AHEAD_DAYS * 86400)
    st.add_memory("Home", "calendar", due_at=at(19, 18), place=places.home_key())
    seen = cal.lines(st, s, None, THU, here=places.home_key())
    assert any(l.startswith("- Thursday 22 November") or "Edge" in l for l in seen)                 # three days to the second: shown
    assert any(l.endswith("at home: Home (#3)") for l in seen)                                      # at home already: no walk
    assert cal.lines(st, s, None, due - walk * 60 - 1, here=places.home_key())[1].startswith("- Thursday 19 November, 4:00 pm")
    assert cal.lines(st, s, None, due - walk * 60, here=places.home_key())[1].startswith("- It's time to set off")
    assert cal.lines(st, s, None, due - cal.EARLY, here="woods")[1] == "- Now, here: Visit (#1, 4:00 pm)"
    st.log("calendar", id=9, text="Gone", due_at=due, place="", outcome="missed")
    assert "- You missed: Gone (Thursday 19 November, 4:00 pm)" in cal.lines(st, s, None, THU)
    st.log("calendar", id=10, text="At home", due_at=due, place=places.home_key(), outcome="missed")
    assert "- You missed: At home (Thursday 19 November, 4:00 pm, at home)" in cal.lines(st, s, None, THU)
    cal.step(st, s, None, at(19, 17) - 2)                                           # the earlier ones have had their wake
    woke = st.add_memory("Wake", "calendar", due_at=at(19, 17))
    assert cal.step(st, s, None, at(19, 17) - 1) is False and cal.step(st, s, None, at(19, 17)) is True
    assert st.meta(f"cal_woke:{woke}:{at(19, 17)}") == "1"
