import time

import pytest

from app import capabilities as C
from tests.test_projects import PIP_STEPS, PLAN, FixedRng, call, make, report


def ev(kind, **d):
    return {"kind": kind, "data": d}


def test_tools_count_by_outcome_and_skip_routine_ones():
    got = C.collect([
        ev("tool", tool="plant", result="planted tomatoes"), ev("tool", tool="plant", result="error: every plot is in use"),
        ev("tool", tool="harvest", result="not ready"), ev("tool", tool="recall", result="You remember:\n- x"),
        ev("tool", tool="recall", result="nothing comes to mind"), ev("tool", tool="set_activity", result="now x"),
        ev("tool", tool="say", result="said"), ev("tool", tool="rest", result="no change", noop=True)])["tool"]
    assert got["plant"] == {"tries": 2, "good": 1, "neutral": 0, "bad": 1}
    assert got["harvest"]["bad"] == 1 and got["recall"] == {"tries": 2, "good": 1, "neutral": 0, "bad": 1}
    assert not {"set_activity", "say", "rest"} & set(got)


def test_work_and_experiments_count_per_craft_and_ability():
    got = C.collect([
        ev("work", result="good", craft="clockmaking", abilities=["precision", "patience"]),
        ev("work", result="slow", craft="clockmaking", abilities=["precision"]),
        ev("work", result="blowup", craft="clockmaking", abilities=["precision"]),
        ev("work", result="good", craft="clockmaking", abilities=["precision"], interrupted=True),   # ignored
        ev("experiment", outcome="insight", craft="clockmaking"), ev("experiment", outcome="nothing", craft="clockmaking")])
    assert got["craft"]["clockmaking"] == {"tries": 5, "good": 2, "neutral": 1, "bad": 2}
    assert got["ability"]["precision"] == {"tries": 3, "good": 1, "neutral": 1, "bad": 1}
    assert got["ability"]["ingenuity"] == {"tries": 2, "good": 1, "neutral": 0, "bad": 1}


def test_older_events_are_filled_in_from_the_project():
    got = C.collect([ev("work", result="good", project_id=7, stage="cut")], crafts={7: "clockmaking"},
                    stage_abilities={(7, "cut"): ["precision"]})
    assert got["craft"]["clockmaking"]["good"] == 1 and got["ability"]["precision"]["good"] == 1


def test_the_prompt_block_is_counts_with_the_change_since_last_time():
    now = {"tool": {"plant": {"tries": 12, "good": 11, "neutral": 0, "bad": 1}, "rare": {"tries": 2, "good": 2, "neutral": 0, "bad": 0},
                    "recall": {"tries": 9, "good": 4, "neutral": 0, "bad": 5}},
           "craft": {"clockmaking": {"tries": 9, "good": 5, "neutral": 2, "bad": 2}}, "ability": {}}
    before = {"tool": {"plant": {"tries": 10, "good": 10, "neutral": 0, "bad": 0}}, "craft": {}, "ability": {}}
    text = C.format_snapshot(now, before)
    assert "- plant: 12 tries, 11 worked, 1 didn't (since last time: +2 tries, +1 good, +1 bad)" in text
    assert "- recall: 9 tries, 4 found something, 5 didn't" in text
    assert "- clockmaking: 9 sessions: 5 went well, 2 slowly, 2 badly" in text
    assert "rare" not in text and text.index("plant") < text.index("recall")      # fewer than 3 tries hidden; busiest first


@pytest.mark.asyncio
async def test_work_events_record_craft_and_abilities_and_the_reflection_sees_the_counts(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**PLAN)], work_speed=10**6, verify_insights=False)
    st.add_item("brass wire", 4, "material")
    await call(agent, "start_project", name="gear clock", steps=PIP_STEPS)
    for _ in range(3):
        agent.rng = FixedRng(0.1)
        await call(agent, "work_on", project="gear clock", minutes=15)
        time.sleep(0.05)
        await agent.resolve_world()
    w = [e for e in st.events(30) if e["kind"] == "work"][0]["data"]
    assert w["craft"] == "clockmaking" and w["abilities"] == ["handiness"]
    gm.queue(report(summary="A hard stretch.", people=[], insights=[], **{"self": "Pip."}))
    await agent.reflect()
    task = gm.calls[-1]["messages"][0]["content"]
    assert "What you have actually been able to do, counted from outcomes (not judgments):" in task
    assert "- clockmaking: 3 sessions: 3 badly" in task or "clockmaking: 3 sessions" in task
    assert "Describe what you can do from the counts above" in task
    ((day, snap),) = st.capability_snapshots(2)
    assert snap["craft"]["clockmaking"]["tries"] == 3
    gm.queue(report(summary="Again.", people=[], insights=[], **{"self": "Pip."}))
    st.log("tool", tool="start_project", args={}, result="started project #2 x")
    await agent.reflect()                                      # same day: replaces today's snapshot, compares with none
    assert len(st.capability_snapshots(5)) == 1
