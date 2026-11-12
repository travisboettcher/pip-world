import time

import pytest

from app import turning as T
from app.memory import STAT_LABELS
from tests.test_memory import eid, visit
from tests.test_projects import call, make, report

TODAY = "2026-11-02"


def work(st, **kw):
    d = dict(project="clock", stage="s", text="t", result="good", project_done=False, interrupted=False, minutes=60,
             approach="", finished_stage=False, percent=10)
    return st.log("work", **{**d, **kw})


def detect(st, since=0.0, stats=None):
    return T.detect(st, since, time.time() + 1, stats or {}, TODAY, STAT_LABELS)


def kinds(r):
    return [s["kind"] for s in r["signals"]]


def test_a_quiet_stretch_is_not_a_candidate(tmp_path):
    s, st, *_ = make(tmp_path)
    work(st)
    r = detect(st)
    assert not r["flagged"] and r["score"] < T.TURNING_MIN


def test_signals_are_facts_with_event_ids(tmp_path):
    s, st, *_ = make(tmp_path)
    visit(st, "hello")                         # a major first (the first visitor, the first message from Morgan)
    done = work(st, project_done=True, project="gear clock")
    st.add_expectation("session", 1, "clockmaking", "cut the wheels",
                       {"expected": "well", "actual": "badly - a setback", "error": -2, "surprise": "worse"}, done)
    r = detect(st)
    by = {}
    for sg in r["signals"]:
        by.setdefault(sg["kind"], []).append(sg)
    assert by["goal"][0] == {"kind": "goal", "events": [done], "text": "you finished gear clock"}
    assert by["surprise"][0]["text"] == "cut the wheels: you expected well; badly - a setback"
    assert {x["text"] for x in by["first"]} <= {"the first time someone came to talk to you", "your first message from Morgan"}
    assert r["flagged"] and r["score"] >= 3


def test_each_kind_is_capped_so_one_busy_thing_cant_swamp(tmp_path):
    s, st, *_ = make(tmp_path)
    for n in range(6):
        visit(st, f"hi {n}", sender=f"Person{n}")      # six new people: six major firsts
    assert kinds(detect(st)).count("first") == T.MAX_SIGNALS["first"]


def test_returning_after_a_long_gap_is_a_signal(tmp_path):
    s, st, *_ = make(tmp_path)
    st.log("tool", tool="plant", args={}, result="planted", first="planted something")
    st.db.execute("UPDATE facets SET last_ts = last_ts - ? WHERE key = 'tool:plant'", (4 * 86400,))
    st.db.commit()
    again = st.log("tool", tool="plant", args={}, result="planted", first="planted something")
    ev = [e for e in st.events(5) if e["id"] == again][0]
    assert ev["data"]["returns"] == [{"key": "tool:plant", "label": "the first time you planted something", "days": pytest.approx(4, abs=0.1)}]
    (sg,) = [x for x in detect(st)["signals"] if x["kind"] == "return"]
    assert sg["text"] == "the first time in 4 days you planted something" and sg["events"] == [again]
    st.log("tool", tool="plant", args={}, result="planted", first="planted something")      # an ordinary repeat is not a return
    assert [r for r in st.events(1)[0]["data"].get("returns", [])] == []


def test_counts_are_compared_with_pips_own_usual_and_need_a_baseline(tmp_path):
    s, st, *_ = make(tmp_path)
    today = {"work_sessions": 9, "setbacks": 0}
    st.save_day_stats("2026-10-30", {"work_sessions": 3})
    st.save_day_stats("2026-10-31", {"work_sessions": 4})
    assert "baseline" not in kinds(detect(st, stats=today))         # only two prior days: no "usual" yet
    st.save_day_stats("2026-11-01", {"work_sessions": 3})
    (sg,) = [x for x in detect(st, stats=today)["signals"] if x["kind"] == "baseline"]
    assert sg["text"] == "work sessions: 9 today, against your usual 3.3 (range 3-4)"
    assert "baseline" not in kinds(detect(st, stats={"work_sessions": 4}))      # within the usual range
    assert "baseline" not in kinds(detect(st, stats={"work_sessions": 5}))      # under the 2-count floor + 2 sd


def test_a_change_in_who_pip_talks_to_most(tmp_path):
    s, st, *_ = make(tmp_path)
    for _ in range(3):
        visit(st, "hi", sender="Morgan")
    cut = time.time()
    time.sleep(0.01)
    for _ in range(2):
        visit(st, "hello", sender="Jade")
    (sg,) = [x for x in T.detect(st, cut, time.time() + 1, {}, TODAY, STAT_LABELS)["signals"] if x["kind"] == "partner"]
    assert sg["text"] == "you talked with Jade most; before it was Morgan"


@pytest.mark.asyncio
async def test_a_flagged_stretch_goes_to_the_reflection_and_pips_claim_is_cited(tmp_path):
    s, st, gm, agent = make(tmp_path, verify_insights=False)
    visit(st, "hello")
    done = work(st, project_done=True, project="gear clock")
    st.add_expectation("session", 1, "clockmaking", "cut the wheels",
                       {"expected": "well", "actual": "badly - a setback", "error": -2, "surprise": "worse"}, done)
    gm.queue(report(summary="A big day.", people=[], insights=[], **{"self": "Pip."}, turning_points=[
        {"text": "Finishing the clock changed what I think I can do.", "importance": 9, "because": [f"e{done}"]}]))
    d = await agent.reflect()
    task = gm.calls[0]["messages"][0]["content"]
    assert "Things that changed more than usual (facts, not verdicts):" in task
    assert f"- [e{done}] you finished gear clock" in task and "`turning_points`: at most one" in task
    assert d["candidate"]["flagged"] and st.turning_points(5)[0]["score"] == d["candidate"]["score"]
    (t,) = st.reflections("turning")
    assert t["grounded"] == 1 and st.reflection_cites(t["id"]) == [("event", done)]
    p = agent._perception("timer", [])
    assert "Days that mattered to you:" in p and "Finishing the clock changed what I think I can do." in p
    r = await call(agent, "recall", query="clock changed")
    assert "a day that mattered" in r.text


@pytest.mark.asyncio
async def test_a_quiet_day_asks_nothing_forced(tmp_path):
    s, st, gm, agent = make(tmp_path, verify_insights=False)
    st.log("tool", tool="note_to_self", args={"section": "todo", "text": "tidy"}, result="wrote in todo")
    gm.queue(report(summary="Quiet.", people=[], insights=[], **{"self": "Pip."}))
    d = await agent.reflect()
    assert "Things that changed more than usual" not in gm.calls[0]["messages"][0]["content"]
    assert d["candidate"] is None and st.turning_points(5) == [] and st.reflections("turning") == []
