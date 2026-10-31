"""Projects: the edges the first two files leave open (float dust, kinds of item, which outcomes teach)."""
import pytest

from app import projects as proj
from test_mut_projects_flow import OneRoll, StubGM, add, begin, steps_, world  # noqa: F401  (world is a fixture)
from test_mut_projects_pure import mk, stage


def test_progress_exactly_one_millionth_short_still_counts_as_not_done():
    assert proj.current_stage({"stages": [stage(progress=60 - 1e-6)]}) is None
    assert proj.current_stage({"stages": [stage(progress=60 - 2e-6)]}) == 0


def test_missing_tool_quantities_are_reported_like_materials(tmp_path):
    st = mk(tmp_path)
    st.add_item("file", 1, "tool")
    take, problems = proj.missing_materials(st, {"materials": {"file": 2}})
    assert take == [] and problems == ["2 file (you have 1)"]


async def test_a_step_is_finished_only_when_its_minutes_are_done(world):  # noqa: F811
    s, st = world
    p = add(st, [{"name": "cut", "minutes": 60}])
    stages = st.project(p["id"])["stages"]
    stages[0]["progress"] = 59.0
    st.update_project(p["id"], stages=stages)
    begin(st, st.project(p["id"]), minutes=30, started_at=100.0)
    data = await proj.resolve_session(st, s, None, OneRoll(), now=100.0, interrupted=True)      # no time passed at all
    assert data["minutes"] == 0 and data["finished_stage"] is False
    stages = st.project(p["id"])["stages"]
    stages[0]["progress"] = 60 - 1e-6
    st.update_project(p["id"], stages=stages)
    begin(st, st.project(p["id"]), minutes=30, started_at=100.0)
    data = await proj.resolve_session(st, s, None, OneRoll(), now=100.0, interrupted=True)
    assert data["finished_stage"] is True


async def test_an_experiment_stopped_at_once_earns_no_practice(world):  # noqa: F811
    s, st = world
    p = add(st)
    begin(st, p, kind="experiment", target="x", minutes=30, started_at=100.0)
    await proj.resolve_experiment(st, s, None, OneRoll(), now=100.0, interrupted=True)
    assert st.skills() == {"clockmaking": 0}


async def test_experiments_draw_on_ingenuity_and_knowledge(world):  # noqa: F811
    s, st = world
    st.add_ability_xp({"ingenuity": 240, "knowledge": 240})              # level 2 each: +0.10
    p = add(st, questions=["q?"], hidden=["f"])
    begin(st, p, kind="experiment", target="x")
    data = await proj.resolve_experiment(st, s, None, OneRoll(0.20))      # 0.30 is a clue; without the skill it is nothing
    assert data["outcome"] == "clue"


async def test_a_dry_streak_turns_even_a_blank_result_into_an_insight(world):  # noqa: F811
    s, st = world
    p = add(st, questions=["q?"], hidden=["f"])
    st.update_project(p["id"], dry=2)
    begin(st, st.project(p["id"]), kind="experiment", target="x")
    assert (await proj.resolve_experiment(st, s, None, OneRoll(0.1)))["outcome"] == "insight"


async def test_a_surprise_teaches_like_an_insight_and_clears_the_dry_streak(world):  # noqa: F811
    s, st = world
    p = add(st, questions=["q?"], hidden=["f1"])
    st.update_project(p["id"], dry=1)
    begin(st, st.project(p["id"]), kind="experiment", target="x")
    data = await proj.resolve_experiment(st, s, None, OneRoll(0.95))
    after = st.project(p["id"])
    assert data["outcome"] == "surprise" and data["finding"] == "f1" and data["answered"] == "q?"
    assert after["dry"] == 0 and after["hidden"][0]["found"] is True


async def test_an_experiment_leaves_pip_idle_and_ties_its_prediction_to_the_project(world):  # noqa: F811
    s, st = world
    p = add(st)
    begin(st, p, kind="experiment", target="x", expect="works")
    await proj.resolve_experiment(st, s, None, OneRoll(0.5))
    assert st.agent()["activity"] == "idle"
    assert st.expectations()[0]["project_id"] == p["id"]


async def test_the_gm_hears_the_reason_only_when_it_counts(world):  # noqa: F811
    s, st = world
    hist = [{"ts": 1, "stage": "cut", "result": "good", "minutes": 5, "text": "t", "interrupted": False}]
    p = add(st)                                                         # nothing unknown
    st.update_project(p["id"], history=hist)
    gm = StubGM(revision={"text": "ok"})
    await proj.revise(st, gm, st.project(p["id"]), steps_("x"), [], "because")
    assert gm.asked("revise")[0][2] == ""
    q = add(st, questions=["q?"], name="Other")                          # something unknown, but no new experience yet
    gm = StubGM(revision={"text": "ok"})
    await proj.revise(st, gm, q, steps_("x"), [], "because")
    assert gm.asked("revise")[0][2] == ""
