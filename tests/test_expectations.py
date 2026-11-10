import time

import pytest

from app import expectations as E
from app import memory as mem
from tests.test_projects import PIP_STEPS, FixedRng, PLAN, call, make, report


def test_session_comparison_is_ordinal_signed_and_flags_only_big_misses():
    c = E.compare_session("well", "good")
    assert c["error"] == 0 and c["surprise"] is None and c["phrase"] == "you expected it to go well; it went well"
    assert E.compare_session("well", "setback")["surprise"] == "worse"        # 3 -> 1
    assert E.compare_session("well", "blowup")["error"] == -3
    assert E.compare_session("badly", "breakthrough")["surprise"] == "better"
    assert E.compare_session("slowly", "good")["surprise"] is None            # one step off is not a surprise
    assert E.compare_session("", "good") is None and E.compare_session("maybe", "good") is None


def test_experiment_comparison():
    assert E.compare_experiment("works", "nothing")["surprise"] == "worse"
    assert E.compare_experiment("fails", "insight")["surprise"] == "better"
    assert E.compare_experiment("works", "clue")["surprise"] is None
    assert E.compare_experiment("works", "surprise")["error"] == 0 and E.compare_experiment("", "clue") is None
    assert E.compare_experiment("partly", "nothing")["phrase"] == "you expected it to partly work; it failed"


def test_step_duration_compares_pips_guess_with_the_time_spent():
    assert E.compare_step(60, 70)["surprise"] is None
    assert E.compare_step(60, 120)["surprise"] == "longer" and E.compare_step(60, 25)["surprise"] == "shorter"
    assert E.compare_step(0, 30) is None and E.compare_step(60, 0) is None


def row(kind="session", craft="clockmaking", error=0, surprising=False):
    return {"kind": kind, "craft": craft, "error": error, "surprising": surprising}


def test_calibration_is_plain_counts_and_waits_for_enough_predictions():
    assert E.calibration([row()] * 4) == []
    rows = [row(error=-2, surprising=True)] * 4 + [row(error=0)] * 2 + [row(kind="step", error=2.5, surprising=True)]
    lines = E.calibration(rows)
    assert lines[0] == "Your predictions lately: 2 of 6 were close."          # steps aren't predictions
    assert "In 4 of your last 5 clockmaking predictions it went worse than you expected." in lines
    assert not any("better" in l for l in lines)


def test_learning_progress_needs_two_windows():
    assert E.learning_progress({"clockmaking": [1.0, 1.0, 1.0, 2.0, 2.0]}) == []
    got = E.learning_progress({"clockmaking": [0, 1, 0, 1, 0, 2, 2, 2, 2, 2]})
    assert got == [("clockmaking", 2.0, 0.4)]


async def session(agent, st, die, expect="well", approach="measure first", project="gear clock", minutes=60):
    agent.rng = FixedRng(die)
    r = await call(agent, "work_on", project=project, minutes=minutes, approach=approach, expect=expect)
    time.sleep(0.05)
    await agent.resolve_world()
    return r


async def begun(tmp_path, script=None, **kw):
    s, st, gm, agent = make(tmp_path, [report(**PLAN)] + (script or []), work_speed=10**6, **kw)
    st.add_item("brass wire", 4, "material")
    await call(agent, "start_project", name="gear clock", steps=PIP_STEPS)
    return s, st, gm, agent


@pytest.mark.asyncio
async def test_a_session_records_the_gap_between_expectation_and_outcome(tmp_path):
    s, st, gm, agent = await begun(tmp_path)
    await session(agent, st, 0.1, expect="well")                   # die: setback
    w = [e for e in st.events(20) if e["kind"] == "work"][0]
    assert w["data"]["expected"] == "well" and w["data"]["error"] == -2 and w["data"]["surprise"] == "worse"
    assert w["data"]["expectation"] == "you expected it to go well; it went badly - a setback"
    (x,) = st.expectations(5)
    assert (x["kind"], x["expected"], x["error"], x["surprising"], x["direction"], x["craft"], x["event_id"]) == (
        "session", "well", -2.0, 1, "worse", "clockmaking", w["id"])
    assert "surprise:worse" in {r["key"] for r in st.db.execute("SELECT key FROM facets")}
    p = agent._perception("timer", [])
    assert "(you expected it to go well; it went badly - a setback)" in p
    assert "the first time something went much worse than you expected" in p


@pytest.mark.asyncio
async def test_no_prediction_no_record_and_interruption_resolves_nothing(tmp_path):
    s, st, gm, agent = await begun(tmp_path)
    await session(agent, st, 0.6, expect="")
    assert [x["kind"] for x in st.expectations(5)] == ["step"]       # only the step-duration comparison (finished stage)
    w = [e for e in st.events(20) if e["kind"] == "work"][0]["data"]
    assert "expected" not in w and "expectation" not in w
    s.work_speed = 1                                                # a real hour, so it is surely still going when Pip rests
    await call(agent, "work_on", project="gear clock", minutes=60, expect="well")
    await call(agent, "rest")                                       # cut short: no verdict, no comparison
    assert [x["kind"] for x in st.expectations(5)] == ["step"] and st.session() is None


@pytest.mark.asyncio
async def test_experiment_expectations_and_the_gm_is_not_told(tmp_path):
    s, st, gm, agent = await begun(tmp_path, [report(relevant=False, text="Nothing to do with it.")])
    agent.rng = FixedRng(0.75)                                      # die: insight, but the GM says irrelevant
    await call(agent, "experiment", project="gear clock", hypothesis="what if I paint it blue and sing", minutes=30,
               expect="works")
    time.sleep(0.05)
    await agent.resolve_world()
    (x,) = st.expectations(5)
    assert (x["kind"], x["expected"], x["actual"], x["direction"]) == ("experiment", "works", "it failed", "worse")
    assert not any("expect" in c["messages"][0]["content"].lower() for c in gm.calls[1:])  # the GM never sees it


@pytest.mark.asyncio
async def test_finishing_a_step_compares_the_time_with_pips_own_guess(tmp_path):
    s, st, gm, agent = await begun(tmp_path)
    stages = st.project(1)["stages"]
    stages[0].update(guess=20, minutes=60)                           # Pip guessed 20 minutes; the step needs 60
    st.update_project(1, stages=stages)
    await session(agent, st, 0.6, expect="", minutes=60)              # a good 60-minute session finishes it
    w = [e for e in st.events(20) if e["kind"] == "work"][0]["data"]
    assert w["finished_stage"] and w["step_surprise"] == "longer" and w["step_note"] == "you guessed 20 minutes; it took 60"
    (x,) = st.expectations(5)
    assert x["kind"] == "step" and x["surprising"] == 1
    assert "(you guessed 20 minutes; it took 60)" in agent._perception("timer", [])


@pytest.mark.asyncio
async def test_calibration_block_reflection_list_and_day_counts(tmp_path):
    s, st, gm, agent = await begun(tmp_path)
    for n in range(5):
        st.update_agent(energy=1.0)
        await session(agent, st, 0.1, expect="well", minutes=15)     # five setbacks, all expected to go well
        st.update_project(1, stages=[{**x, "progress": 0.0, "started": True} for x in st.project(1)["stages"]])
    p = agent._perception("timer", [])
    assert "Your predictions lately: 0 of 5 were close." in p
    assert "In 5 of your last 5 clockmaking predictions it went worse than you expected." in p
    gm.queue(report(summary="Bad day.", people=[], insights=[], **{"self": "Pip."}))
    d = await agent.reflect()
    task = gm.calls[-1]["messages"][0]["content"]
    assert "Things that did not go as you expected (cite their ids):" in task and "you expected well; badly - a setback" in task
    assert d["stats"]["predictions"] == 5 and d["stats"]["surprises"] == 5
    assert "5 predictions made, 5 surprises" in task or "5 predictions made" in mem.format_stats(st.day_stats(3))
