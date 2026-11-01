"""Projects: resolving work sessions and experiments, applying what the GM found, and editing a plan."""
import random

import pytest

from app import projects as proj
from app.config import Settings
from app.state import State


class OneRoll(random.Random):
    """random() always returns `value`; choice() picks deterministically from the seed."""

    def __init__(self, value=0.5):
        super().__init__(7)
        self.value = value

    def random(self):
        return self.value


class StubGM:
    """Records what the engine asks and answers with whatever the test set."""

    def __init__(self, ruling=None, narration=None, verdict=None, revision=None):
        self.ruling, self.narration, self.verdict, self.revision = ruling, narration, verdict, revision
        self.calls = []

    async def adjudicate(self, *args):
        self.calls.append(("adjudicate", args))
        return self.ruling

    async def narrate(self, *args):
        self.calls.append(("narrate", args))
        return self.narration

    async def experiment(self, *args):
        self.calls.append(("experiment", args))
        return self.verdict

    async def revise(self, *args):
        self.calls.append(("revise", args))
        return self.revision

    def asked(self, name):
        return [a for n, a in self.calls if n == name]


@pytest.fixture
def world(tmp_path):
    s = Settings(db_path=str(tmp_path / "w.db"), sleep=False, work_speed=2.0)
    return s, State(s)


def add(st, stages=None, questions=(), hidden=(), difficulty=1, tools=(), craft="clockmaking", name="Clock", goal="tell time"):
    stages = stages if stages is not None else [{"name": "cut", "minutes": 60}, {"name": "fit", "minutes": 30}]
    p = st.add_project(name, goal, craft, difficulty, proj.new_stages({"stages": proj.sanitize_stages(stages, 8)}), list(tools))
    st.update_project(p["id"], questions=list(questions), hidden=[{"fact": f, "found": False} for f in hidden])
    return st.project(p["id"])


def begin(st, p, stage=0, minutes=30, kind="work", target="", expect="", started_at=None, activity="working"):
    st.start_session(p["id"], stage, minutes, 0, kind=kind, target=target, expect=expect)
    if started_at is not None:
        st.db.execute("UPDATE work_session SET started_at = ?", (started_at,))
        st.db.commit()
    st.update_agent(activity=activity)


# --- resolve_session -----------------------------------------------------------------------------
async def test_no_session_or_another_kind_of_session_is_left_alone(world):
    s, st = world
    assert await proj.resolve_session(st, s, None, OneRoll()) is None
    p = add(st)
    begin(st, p, kind="walk")
    assert await proj.resolve_session(st, s, None, OneRoll()) is None
    assert st.session()["kind"] == "walk"


async def test_a_session_for_a_finished_or_missing_project_ends_with_nothing_logged(world):
    s, st = world
    p = add(st)
    begin(st, p)
    st.update_project(p["id"], status="done")
    assert await proj.resolve_session(st, s, None, OneRoll()) is None
    assert st.session() is None and st.events(limit=5) == []
    st.start_session(999, 0, 30, 0)
    assert await proj.resolve_session(st, s, None, OneRoll()) is None and st.session() is None


async def test_a_normal_session_reports_everything_and_records_it(world):
    s, st = world
    p = add(st)
    begin(st, p, minutes=30)
    data = await proj.resolve_session(st, s, None, OneRoll(0.5), now=5000.0)
    assert data == {
        "project": "Clock", "project_id": p["id"], "stage": "cut", "result": "good", "craft": "clockmaking",
        "abilities": ["handiness"], "minutes": 30, "text": "You made steady progress on cut.",
        "finished_stage": False, "project_done": False, "interrupted": False, "percent": 33, "approach": "",
        "lost": [], "learned": None, "crossroads": False}
    after = st.project(p["id"])
    assert after["stages"][0]["progress"] == 30 and after["stages"][1]["progress"] == 0 and after["status"] == "active"
    assert after["history"] == [{"ts": 5000.0, "stage": "cut", "result": "good", "minutes": 30,
                                 "text": "You made steady progress on cut.", "interrupted": False}]
    assert st.session() is None
    ev = st.events(limit=1)[0]
    assert ev["kind"] == "work" and all(ev["data"][k] == v for k, v in data.items())
    assert st.skills() == {"clockmaking": 30} and st.abilities() == {"handiness": 30}
    a = st.agent()
    assert a["activity"] == "idle" and a["description"] == "just finished working on Clock"


async def test_activity_other_than_working_is_not_reset(world):
    s, st = world
    p = add(st)
    begin(st, p, activity="resting")
    await proj.resolve_session(st, s, None, OneRoll())
    assert st.agent()["activity"] == "resting" and st.agent()["description"] == ""


async def test_now_defaults_to_the_clock(world, monkeypatch):
    import time
    monkeypatch.setattr(time, "time", lambda: 777.0)
    s, st = world
    p = add(st)
    begin(st, p)
    await proj.resolve_session(st, s, None, OneRoll())
    assert st.project(p["id"])["history"][0]["ts"] == 777.0


@pytest.mark.parametrize("value,result,credit", [(0.05, "setback", 0.0), (0.2, "slow", 0.5), (0.5, "good", 1.0),
                                                 (0.95, "breakthrough", 1.5)])
async def test_each_result_earns_its_share_of_the_minutes(world, value, result, credit):
    s, st = world
    p = add(st, [{"name": "cut", "minutes": 200}])
    begin(st, p, minutes=40)
    data = await proj.resolve_session(st, s, None, OneRoll(value))
    assert data["result"] == result
    assert st.project(p["id"])["stages"][0]["progress"] == pytest.approx(40 * credit)
    assert data["minutes"] == 40                                       # xp and the log use the full session either way


async def test_progress_never_runs_past_the_stage(world):
    s, st = world
    p = add(st, [{"name": "cut", "minutes": 60}, {"name": "fit", "minutes": 30}])
    st.update_project(p["id"], stages=[{**p["stages"][0], "progress": 50.0}, p["stages"][1]])
    begin(st, st.project(p["id"]), minutes=30)
    data = await proj.resolve_session(st, s, None, OneRoll(0.95))
    after = st.project(p["id"])
    assert after["stages"][0]["progress"] == 60 and data["finished_stage"] is True and data["project_done"] is False
    assert data["percent"] == 66


async def test_finishing_the_last_stage_completes_the_project(world):
    s, st = world
    p = add(st, [{"name": "only", "minutes": 30}])
    begin(st, p, minutes=30)
    data = await proj.resolve_session(st, s, None, OneRoll(0.5), now=900.0)
    done = st.project(p["id"])
    assert data["project_done"] is True and data["finished_stage"] is True and data["percent"] == 100
    assert done["status"] == "done" and done["finished_at"] == 900.0 and data["crossroads"] is False


async def test_open_questions_keep_a_finished_plan_open_at_a_crossroads(world):
    s, st = world
    p = add(st, [{"name": "only", "minutes": 30}], questions=["why does it stop?"], hidden=["a loose spring"])
    begin(st, p, minutes=30)
    data = await proj.resolve_session(st, s, None, OneRoll(0.5))
    after = st.project(p["id"])
    assert data["project_done"] is False and data["crossroads"] is True and data["percent"] == 99
    assert after["status"] == "active" and after["finished_at"] is None


async def test_an_interrupted_session_counts_only_the_time_spent_at_half_credit_without_the_die(world):
    s, st = world
    p = add(st, [{"name": "cut", "minutes": 200}])
    gm = StubGM(narration="should not be asked")
    begin(st, p, minutes=60, started_at=1000.0, expect="well")
    data = await proj.resolve_session(st, s, gm, OneRoll(0.99), now=1000.0 + 600, interrupted=True)   # 10 min x work_speed 2
    assert data["result"] == "slow" and data["interrupted"] is True and data["minutes"] == 20
    assert data["text"] == "Work on cut was slow and fiddly, but it moved forward."
    assert st.project(p["id"])["stages"][0]["progress"] == pytest.approx(10)
    assert gm.calls == [] and "expected" not in data and st.skills() == {"clockmaking": 20}
    assert st.expectations() == []
    assert st.project(p["id"])["history"][0]["interrupted"] is True


async def test_an_interrupted_session_never_credits_more_than_was_planned_or_less_than_nothing(world):
    s, st = world
    p = add(st, [{"name": "cut", "minutes": 200}])
    begin(st, p, minutes=30, started_at=1000.0)
    data = await proj.resolve_session(st, s, None, OneRoll(), now=1000.0 + 3600 * 5, interrupted=True)
    assert data["minutes"] == 30
    begin(st, p, minutes=30, started_at=1000.0)
    data = await proj.resolve_session(st, s, None, OneRoll(), now=500.0, interrupted=True)
    assert data["minutes"] == 0


async def test_the_gm_is_asked_about_what_pip_tried_and_the_die_bounds_the_answer(world):
    s, st = world
    st.add_item("brass wire", 4, "material")
    st.add_item("tweezers", 1, "tool")
    p = add(st, [{"name": "cut", "minutes": 100, "materials": {"brass wire": 2}}], tools=["tweezers"])
    st.update_project(p["id"], history=[{"ts": 1, "stage": "cut", "result": "good", "minutes": 5, "text": f"t{i}",
                                         "interrupted": i == 2} for i in range(6)])
    gm = StubGM(ruling={"verdict": "breakthrough", "text": "x" * 400})
    begin(st, st.project(p["id"]), minutes=30, target="  heat it first ")
    data = await proj.resolve_session(st, s, gm, OneRoll(0.2))             # rolled: slow
    (args,) = gm.asked("adjudicate")
    project, stage, approach, rolled_, minutes, mats, earlier, feelings = args
    assert project["name"] == "Clock" and stage["name"] == "cut" and approach == "heat it first"
    assert rolled_ == "slow" and minutes == 30 and earlier == ["t1", "t3", "t4", "t5"][-3:]
    assert mats[0] == "brass wire" and "tweezers" in mats and "apple" not in mats
    assert feelings == proj.feel(st)
    assert data["result"] == "good"                                       # one step above the roll, no more
    assert data["text"] == "x" * 300 + "..."
    assert data["approach"] == "heat it first"
    assert st.project(p["id"])["stages"][0]["progress"] == 30


async def test_without_an_approach_or_a_gm_the_die_stands(world):
    s, st = world
    p = add(st)
    gm = StubGM(ruling={"verdict": "breakthrough", "text": "never"})
    begin(st, p)
    data = await proj.resolve_session(st, s, gm, OneRoll(0.2))
    assert data["result"] == "slow" and gm.asked("adjudicate") == []
    begin(st, st.project(p["id"]), target="try something")
    data = await proj.resolve_session(st, s, None, OneRoll(0.2))
    assert data["result"] == "slow" and data["approach"] == "try something"


async def test_a_ruling_without_a_verdict_or_text_changes_nothing_but_may_still_teach(world):
    s, st = world
    p = add(st, questions=["q?"], hidden=["h"])
    gm = StubGM(ruling={"finding": "wire bends at the knot"}, narration="The narrator speaks.")
    begin(st, p, target="bend it")
    data = await proj.resolve_session(st, s, gm, OneRoll(0.5))
    assert data["result"] == "good" and data["text"] == "The narrator speaks."
    assert data["learned"] == "wire bends at the knot"
    assert st.project(p["id"])["findings"] == ["wire bends at the knot"]
    assert st.project(p["id"])["questions"] == ["q?"]               # a failed try never answers by itself


async def test_an_empty_ruling_is_ignored(world):
    s, st = world
    p = add(st)
    gm = StubGM(ruling={}, narration=None)
    begin(st, p, target="bend it")
    data = await proj.resolve_session(st, s, gm, OneRoll(0.5))
    assert data["learned"] is None and data["text"] == "You made steady progress on cut."


async def test_a_ruling_can_reveal_a_hidden_fact_and_answer_a_question(world):
    s, st = world
    p = add(st, questions=["q1", "q2"], hidden=["fact one", "fact two"])
    gm = StubGM(ruling={"verdict": "good", "text": "It clicked.", "reveal": 1, "answers": 1, "finding": ""})
    begin(st, p, target="bend it")
    data = await proj.resolve_session(st, s, gm, OneRoll(0.5))
    after = st.project(p["id"])
    assert data["learned"] == "fact two" and data["text"] == "It clicked."
    assert after["hidden"] == [{"fact": "fact one", "found": False}, {"fact": "fact two", "found": True}]
    assert after["questions"] == ["q1"] and after["findings"] == ["fact two"]


async def test_a_ruling_never_adds_a_question_or_moves_the_difficulty_beyond_the_lesson(world):
    s, st = world
    p = add(st, difficulty=2)
    gm = StubGM(ruling={"verdict": "good", "new_question": "what now?", "difficulty_delta": 1})
    begin(st, p, target="bend it")
    await proj.resolve_session(st, s, gm, OneRoll(0.5))
    after = st.project(p["id"])
    assert after["questions"] == [] and after["difficulty"] == 2


async def test_only_the_latest_eight_findings_are_kept(world):
    s, st = world
    p = add(st)
    st.update_project(p["id"], findings=[f"old {i}" for i in range(10)])
    gm = StubGM(ruling={"verdict": "good", "finding": "new one"})
    begin(st, p, target="bend it")
    await proj.resolve_session(st, s, gm, OneRoll(0.5))
    f = st.project(p["id"])["findings"]
    assert len(f) == 8 and f[-1] == "new one" and f[0] == "old 3"


async def test_blowup_costs_ground_energy_and_one_material(world):
    s, st = world
    st.add_item("brass wire", 3, "material")
    st.add_item("file", 1, "tool")
    p = add(st, [{"name": "cut", "minutes": 100, "materials": {"brass wire": 1, "file": 1, "ghost": 1}}], tools=["file"])
    st.update_project(p["id"], stages=[{**p["stages"][0], "progress": 50.0}])
    st.update_agent(energy=0.5)
    gm = StubGM(ruling={"verdict": "blowup", "text": "Bang."})
    begin(st, st.project(p["id"]), target="hammer it", minutes=30)
    data = await proj.resolve_session(st, s, gm, OneRoll(0.2))        # rolled slow; blowup is two steps away -> setback
    assert data["result"] == "setback"
    begin(st, st.project(p["id"]), target="hammer it", minutes=30)
    data = await proj.resolve_session(st, s, gm, OneRoll(0.05))       # rolled setback; one step down is blowup
    assert data["result"] == "blowup" and data["lost"] == ["brass wire"]
    items = {i["name"]: i["qty"] for i in st.items()}
    assert items["brass wire"] == 2 and items["file"] == 1             # a tool is never lost
    assert st.project(p["id"])["stages"][0]["progress"] == pytest.approx(25.0)    # 50 - 25% of 100
    assert st.agent()["energy"] == pytest.approx(0.4)


async def test_blowup_cannot_drive_progress_or_energy_below_zero_or_lose_what_is_not_owned(world):
    s, st = world
    p = add(st, [{"name": "cut", "minutes": 100, "materials": {"ghost": 1}}])
    st.update_project(p["id"], stages=[{**p["stages"][0], "progress": 10.0}])
    st.update_agent(energy=0.05)
    gm = StubGM(ruling={"verdict": "blowup"})
    begin(st, st.project(p["id"]), target="hammer it")
    data = await proj.resolve_session(st, s, gm, OneRoll(0.05))
    assert data["result"] == "blowup" and data["lost"] == []
    assert st.project(p["id"])["stages"][0]["progress"] == 0.0 and st.agent()["energy"] == 0.0
    assert data["text"] == "It went badly wrong on cut, and you lost ground."


async def test_narration_comes_from_the_gm_with_the_context_it_needs(world):
    s, st = world
    st.add_item("brass wire", 2, "material")
    p = add(st, [{"name": "cut", "minutes": 30, "materials": {"brass wire": 1}}], goal="a small clock")
    st.update_project(p["id"], history=[{"ts": 1, "stage": "cut", "result": "good", "minutes": 5, "text": "earlier",
                                         "interrupted": False}])
    gm = StubGM(narration="The wire sang.")
    begin(st, st.project(p["id"]), minutes=30)
    data = await proj.resolve_session(st, s, gm, OneRoll(0.5))
    (args,) = gm.asked("narrate")
    name, goal, stage_name, mats, result, minutes, finished, earlier = args
    assert (name, goal, stage_name, result, minutes, finished, earlier) == ("Clock", "a small clock", "cut", "good", 30,
                                                                              True, ["earlier"])
    assert mats[0] == "brass wire"
    assert data["text"] == "The wire sang."


async def test_a_gm_with_nothing_to_say_falls_back_to_the_plain_line(world):
    s, st = world
    p = add(st)
    begin(st, p)
    data = await proj.resolve_session(st, s, StubGM(narration=""), OneRoll(0.5))
    assert data["text"] == "You made steady progress on cut."


async def test_the_gms_ruling_text_replaces_narration(world):
    s, st = world
    p = add(st)
    gm = StubGM(ruling={"verdict": "good", "text": "Ruling text."}, narration="Narration")
    begin(st, p, target="try")
    data = await proj.resolve_session(st, s, gm, OneRoll(0.5))
    assert data["text"] == "Ruling text." and gm.asked("narrate") == []


async def test_earlier_notes_skip_interrupted_sessions_and_keep_the_last_three(world):
    s, st = world
    p = add(st)
    st.update_project(p["id"], history=[
        {"ts": 1, "stage": "cut", "result": "good", "minutes": 5, "text": t, "interrupted": i}
        for t, i in (("a", False), ("b", False), ("c", True), ("d", False), ("e", False))])
    gm = StubGM(narration="n")
    begin(st, st.project(p["id"]))
    await proj.resolve_session(st, s, gm, OneRoll(0.5))
    assert gm.asked("narrate")[0][-1] == ["b", "d", "e"]


async def test_what_pip_expected_is_compared_and_recorded(world):
    s, st = world
    p = add(st, [{"name": "cut", "minutes": 200}])
    begin(st, p, minutes=30, expect="badly")
    data = await proj.resolve_session(st, s, None, OneRoll(0.95))
    assert data["expected"] == "badly" and data["error"] == 3 and data["surprise"] == "better"
    assert data["expectation"] == "you expected it to go badly; it went unusually well"
    (row,) = st.expectations()
    assert (row["kind"], row["project_id"], row["craft"], row["subject"], row["expected"], row["error"]) == \
        ("session", p["id"], "clockmaking", "cut", "badly", 3)
    assert row["event_id"] == st.events(limit=1)[0]["id"] and row["surprising"] == 1


async def test_finishing_a_step_compares_the_time_it_took_with_pips_guess(world):
    s, st = world
    p = add(st, [{"name": "cut", "minutes": 60}])
    st.update_project(p["id"], history=[
        {"ts": 1, "stage": "cut", "result": "good", "minutes": 40, "text": "x", "interrupted": False},
        {"ts": 2, "stage": "cut", "result": "good", "minutes": 30, "text": "x", "interrupted": False, "kind": "experiment"},
        {"ts": 3, "stage": "other", "result": "good", "minutes": 99, "text": "x", "interrupted": False}])
    stages = st.project(p["id"])["stages"]
    stages[0]["guess"] = 20
    stages[0]["progress"] = 40
    st.update_project(p["id"], stages=stages)
    begin(st, st.project(p["id"]), minutes=30)
    data = await proj.resolve_session(st, s, None, OneRoll(0.5))
    assert data["finished_stage"] is True
    assert data["step_note"] == "you guessed 20 minutes; it took 70" and data["step_surprise"] == "longer"
    rows = st.expectations()
    assert [(r["kind"], r["subject"], r["expected"], r["actual"]) for r in rows] == [("step", "cut", "20 min", "70 min")]


async def test_an_unfinished_step_has_no_duration_comparison(world):
    s, st = world
    p = add(st)
    begin(st, p, minutes=15)
    data = await proj.resolve_session(st, s, None, OneRoll(0.5))
    assert data["finished_stage"] is False and "step_note" not in data and st.expectations() == []


async def test_a_step_without_a_recorded_guess_is_judged_against_its_own_length(world):
    s, st = world
    p = add(st, [{"name": "cut", "minutes": 20}])
    stages = st.project(p["id"])["stages"]
    del stages[0]["guess"]
    st.update_project(p["id"], stages=stages)
    begin(st, st.project(p["id"]), minutes=60)
    data = await proj.resolve_session(st, s, None, OneRoll(0.5))
    assert data["step_note"] == "you guessed 20 minutes; it took 60" and data["step_surprise"] == "longer"


async def test_skill_tools_and_tiredness_shape_the_die_used_by_a_session(world):
    s, st = world
    st.add_item("tweezers", 1, "tool")
    st.add_ability_xp({"handiness": 240})                       # level 2 -> +0.10
    p = add(st, tools=["tweezers", "absent"], difficulty=3)     # tool +0.05, difficulty -0.10
    begin(st, p)
    st.update_agent(energy=0.2)                                 # -0.15
    data = await proj.resolve_session(st, s, None, OneRoll(0.20))           # 0.20 + 0.10 + 0.05 - 0.10 - 0.15 = 0.10
    assert data["result"] == "setback"
    begin(st, st.project(p["id"]))
    st.update_agent(energy=0.9)
    data = await proj.resolve_session(st, s, None, OneRoll(0.20))           # 0.25
    assert data["result"] == "slow"


# --- apply_changes ---------------------------------------------------------------------------------------
def pj(**kw):
    base = {"hidden": [], "findings": [], "questions": [], "stages": [], "difficulty": 3}
    base.update(kw)
    return base


def test_a_finding_is_recorded_once_and_clipped():
    p = pj()
    assert proj.apply_changes(p, {"finding": "  it  works  "}, reveal=False) == {"finding": "it works", "answered": None, "added": []}
    assert proj.apply_changes(p, {"finding": "it works"}, reveal=False)["finding"] is None
    assert p["findings"] == ["it works"]
    out = proj.apply_changes(p, {"finding": "f" * 400}, reveal=False)
    assert out["finding"] == "f" * 240 + "..."
    assert proj.apply_changes(p, {"finding": ""}, reveal=False)["finding"] is None
    assert proj.apply_changes(p, {}, reveal=False)["finding"] is None


def test_revealing_picks_the_asked_fact_or_the_first_unfound_one():
    hidden = lambda: [{"fact": "a", "found": True}, {"fact": "b", "found": False}, {"fact": "c", "found": False}]
    p = pj(hidden=hidden())
    out = proj.apply_changes(p, {"reveal": 2}, reveal=True)
    assert out["finding"] == "c" and p["hidden"][2]["found"] and not p["hidden"][1]["found"]
    p = pj(hidden=hidden())
    assert proj.apply_changes(p, {"reveal": 0}, reveal=True)["finding"] == "b"       # 0 is already found: first unfound
    p = pj(hidden=hidden())
    assert proj.apply_changes(p, {"reveal": 9}, reveal=True)["finding"] == "b"
    p = pj(hidden=hidden())
    assert proj.apply_changes(p, {"reveal": "2"}, reveal=True)["finding"] == "b"
    p = pj(hidden=hidden())
    assert proj.apply_changes(p, {}, reveal=True)["finding"] == "b"
    p = pj(hidden=hidden())
    assert proj.apply_changes(p, {"reveal": 1, "finding": "my words"}, reveal=True)["finding"] == "my words"
    assert p["hidden"][1]["found"] is True
    p = pj(hidden=hidden())
    assert proj.apply_changes(p, {"reveal": 2}, reveal=False)["finding"] is None and not p["hidden"][2]["found"]
    p = pj(hidden=[{"fact": "a", "found": True}])
    assert proj.apply_changes(p, {"reveal": 0}, reveal=True)["finding"] is None


def test_revealing_a_fact_answers_the_first_question_unless_told_which():
    p = pj(hidden=[{"fact": "a", "found": False}], questions=["q1", "q2", "q3"])
    out = proj.apply_changes(p, {}, reveal=True)
    assert out["answered"] == "q1" and p["questions"] == ["q2", "q3"]
    p = pj(questions=["q1", "q2", "q3"])
    assert proj.apply_changes(p, {"answers": 2}, reveal=False)["answered"] == "q3"
    p = pj(questions=["q1", "q2", "q3"])
    assert proj.apply_changes(p, {"answers": 0}, reveal=False)["answered"] == "q1"
    p = pj(questions=["q1", "q2", "q3"])
    assert proj.apply_changes(p, {"answers": 3}, reveal=False)["answered"] == "q1"       # out of range: the first
    p = pj(questions=["q1", "q2", "q3"])
    assert proj.apply_changes(p, {"answers": -1}, reveal=False)["answered"] == "q1"
    p = pj(questions=["q1"])
    assert proj.apply_changes(p, {"answers": "1"}, reveal=False)["answered"] is None
    assert proj.apply_changes(p, {}, reveal=False)["answered"] is None
    p = pj(questions=["q1"])
    assert proj.apply_changes(p, {"answers": 0}, reveal=False, may_answer=False)["answered"] is None and p["questions"] == ["q1"]
    p = pj(hidden=[{"fact": "a", "found": False}])
    assert proj.apply_changes(p, {}, reveal=True)["answered"] is None            # no question to answer


def test_an_insight_with_no_hidden_fact_left_still_answers_the_first_question():
    # a question raised mid-project (a surprise) has no hidden fact behind it; the insight is what settles it
    p = pj(questions=["q1", "q2"])
    out = proj.apply_changes(p, {}, reveal=True)
    assert out["answered"] == "q1" and p["questions"] == ["q2"]
    p = pj(questions=["q1", "q2"], hidden=[{"fact": "a", "found": True}])
    assert proj.apply_changes(p, {"answers": 1}, reveal=True)["answered"] == "q2"
    p = pj(questions=["q1"], hidden=[{"fact": "a", "found": True}])
    assert proj.apply_changes(p, {}, reveal=True, may_answer=False)["answered"] is None and p["questions"] == ["q1"]
    p = pj(questions=["q1"], hidden=[{"fact": "a", "found": False}])
    assert proj.apply_changes(p, {}, reveal=False)["answered"] is None


def test_settling_the_last_question_with_nothing_left_to_do_adds_a_closing_step():
    p = pj(questions=["last"], stages=[{"name": "a", "minutes": 30, "progress": 30.0, "started": True, "materials": {}}])
    out = proj.apply_changes(p, {"answers": 0}, reveal=False)
    assert out["added"] == ["put it all together"]
    assert p["stages"][-1] == {"name": "put it all together", "minutes": 45, "materials": {},
                               "abilities": ["handiness", "precision"], "progress": 0.0, "started": False}
    p = pj(questions=["last"], stages=[{"name": "a", "minutes": 30, "progress": 0.0, "started": False, "materials": {}}])
    assert proj.apply_changes(p, {"answers": 0}, reveal=False)["added"] == [] and len(p["stages"]) == 1
    p = pj(questions=["one", "two"], stages=[{"name": "a", "minutes": 30, "progress": 30.0, "started": True, "materials": {}}])
    assert proj.apply_changes(p, {"answers": 0}, reveal=False)["added"] == [] and len(p["stages"]) == 1
    p = pj(questions=[], stages=[{"name": "a", "minutes": 30, "progress": 30.0, "started": True, "materials": {}}])
    assert proj.apply_changes(p, {}, reveal=False)["added"] == []


def test_new_questions_are_added_only_when_allowed_and_there_is_room():
    p = pj(questions=["a"])
    proj.apply_changes(p, {"new_question": "b?"}, reveal=False, new_question=True)
    assert p["questions"] == ["a", "b?"]
    p = pj(questions=["a"])
    proj.apply_changes(p, {"new_question": "b?"}, reveal=False)
    assert p["questions"] == ["a"]
    p = pj(questions=["a", "b", "c"])
    proj.apply_changes(p, {"new_question": "d?"}, reveal=False, new_question=True)
    assert p["questions"] == ["a", "b", "c"]
    p = pj(questions=["a", "b"])
    proj.apply_changes(p, {"new_question": "d?"}, reveal=False, new_question=True)
    assert p["questions"] == ["a", "b", "d?"]
    p = pj()
    proj.apply_changes(p, {"new_question": ""}, reveal=False, new_question=True)
    proj.apply_changes(p, {}, reveal=False, new_question=True)
    assert p["questions"] == []
    proj.apply_changes(p, {"new_question": "q" * 300}, reveal=False, new_question=True)
    assert p["questions"] == ["q" * 160 + "..."]


@pytest.mark.parametrize("start,delta,expected", [(3, 1, 4), (3, -1, 2), (3, 5, 4), (3, -5, 2), (5, 1, 5), (1, -1, 1),
                                                   (3, 0, 3), (3, "up", 3), (3, 1.5, 3), (3, None, 3), (4, 1, 5), (2, -1, 1)])
def test_difficulty_moves_one_step_within_one_to_five(start, delta, expected):
    p = pj(difficulty=start)
    proj.apply_changes(p, {"difficulty_delta": delta}, reveal=False)
    assert p["difficulty"] == expected


# --- editing a plan -------------------------------------------------------------------------------------------
def planned(*names, **by_name):
    return pj(stages=[{"name": n, "minutes": 30, "progress": by_name.get(n, 0.0), "started": n in by_name.get("started", ()),
                       "materials": {}} for n in names])


def test_edit_plan_drops_only_untouched_steps_by_name():
    p = planned("Cut", "Fit", "Glue", "Paint")
    p["stages"][1]["started"] = True
    p["stages"][2]["progress"] = 5.0
    added, dropped = proj.edit_plan(p, [], [" cut ", "FIT", "glue", "paint", "nothing"])
    assert dropped == ["Cut", "Paint"] and added == []
    assert [s["name"] for s in p["stages"]] == ["Fit", "Glue"]


def test_edit_plan_ignores_a_drop_that_is_not_a_list():
    p = planned("Cut")
    assert proj.edit_plan(p, [], "Cut") == ([], []) and proj.edit_plan(p, [], None) == ([], [])
    assert [s["name"] for s in p["stages"]] == ["Cut"]


def test_edit_plan_appends_new_untouched_steps_up_to_eight_in_all():
    p = planned("a", "b", "c", "d", "e")
    steps = [{"name": f"n{i}", "minutes": 30, "materials": {}, "abilities": ["handiness"]} for i in range(5)]
    added, dropped = proj.edit_plan(p, steps, [])
    assert added == ["n0", "n1", "n2"] and dropped == []
    assert len(p["stages"]) == 8 and p["stages"][-1]["name"] == "n2"
    assert p["stages"][-1]["progress"] == 0.0 and p["stages"][-1]["started"] is False
    assert proj.edit_plan(p, steps, []) == ([], [])                      # no room at all


def test_edit_plan_makes_room_by_dropping_first():
    p = planned("a", "b", "c", "d", "e", "f", "g", "h")
    steps = [{"name": "x", "minutes": 30, "materials": {}}, {"name": "y", "minutes": 30, "materials": {}}]
    added, dropped = proj.edit_plan(p, steps, ["a"])
    assert dropped == ["a"] and added == ["x"]
    assert [s["name"] for s in p["stages"]][-1] == "x" and len(p["stages"]) == 8


# --- resolve_experiment -------------------------------------------------------------------------------------------
async def test_no_experiment_session_means_nothing_happens(world):
    s, st = world
    assert await proj.resolve_experiment(st, s, None, OneRoll()) is None
    p = add(st)
    begin(st, p)
    assert await proj.resolve_experiment(st, s, None, OneRoll()) is None and st.session()["kind"] == "work"
    st.end_session()
    begin(st, p, kind="experiment", target="h")
    st.update_project(p["id"], status="done")
    assert await proj.resolve_experiment(st, s, None, OneRoll()) is None and st.session() is None
    st.start_session(404, 0, 30, 0, kind="experiment")
    assert await proj.resolve_experiment(st, s, None, OneRoll()) is None and st.session() is None


@pytest.mark.parametrize("value,outcome,line", [
    (0.1, "nothing", "Nothing came of it."), (0.4, "clue", "It hinted at something, no more."),
    (0.7, "insight", "Something fell into place."), (0.95, "surprise", "It did something you didn't expect.")])
async def test_experiment_outcomes_and_their_plain_text_without_a_gm(world, value, outcome, line):
    s, st = world
    p = add(st, questions=["q?"], hidden=["h"])
    begin(st, p, kind="experiment", target="soak it", minutes=40)
    data = await proj.resolve_experiment(st, s, None, OneRoll(value), now=10.0)
    assert data["outcome"] == outcome and data["text"] == f"You tried it: soak it. {line}"
    assert data["hypothesis"] == "soak it" and data["relevant"] is True and data["minutes"] == 40
    assert data["interrupted"] is False and data["project"] == "Clock" and data["craft"] == "clockmaking"
    assert st.events(limit=1)[0]["kind"] == "experiment" and st.session() is None
    hist = st.project(p["id"])["history"]
    assert hist == [{"ts": 10.0, "stage": "experiment: soak it", "result": outcome, "minutes": 40, "text": data["text"],
                     "interrupted": False, "kind": "experiment"}]
    assert st.skills() == {"clockmaking": 40} and st.abilities() == {"ingenuity": 20, "knowledge": 20}
    assert st.agent()["description"] == "just ran an experiment on Clock"


@pytest.mark.parametrize("value,outcome", [(0.29, "nothing"), (0.30, "clue"), (0.59, "clue"), (0.60, "insight"),
                                           (0.89, "insight"), (0.90, "surprise")])
def test_experiment_bands(value, outcome):
    assert proj.roll_experiment(OneRoll(value), 0, 1, 0.9) == outcome


def test_experiment_modifiers():
    r = lambda v, skill=0, diff=1, energy=0.9: proj.roll_experiment(OneRoll(v), skill, diff, energy)
    assert r(0.24, skill=1) == "nothing" and r(0.26, skill=1) == "clue"
    assert r(0.19, skill=2) == "nothing" and r(0.21, skill=2) == "clue"
    assert r(0.22, skill=1.5) == "nothing" and r(0.24, skill=1.5) == "clue"
    assert r(0.63, diff=2) == "clue" and r(0.65, diff=2) == "insight"
    assert r(0.45, diff=5) == "nothing" and r(0.47, diff=5) == "clue" and r(0.65, diff=5) == "clue"
    assert r(0.55, diff=3) == "clue" and r(0.69, diff=3) == "insight"
    assert r(0.40, energy=0.3) == "clue" and r(0.40, energy=0.29) == "nothing"
    assert r(0.74, energy=0.29) == "clue" and r(0.76, energy=0.29) == "insight"


async def test_the_experiment_asks_the_gm_with_what_is_hidden_and_found(world):
    s, st = world
    p = add(st, questions=["q?"], hidden=["f1", "f2", "f3"])
    hidden = st.project(p["id"])["hidden"]
    hidden[1]["found"] = True
    st.update_project(p["id"], hidden=hidden)
    gm = StubGM(verdict={"text": "z" * 500, "finding": "wet wood bends"})
    begin(st, st.project(p["id"]), kind="experiment", target="soak it", minutes=40)
    data = await proj.resolve_experiment(st, s, gm, OneRoll(0.4))
    (args,) = gm.asked("experiment")
    assert args[1:] == ("soak it", "clue", ["f1", "f3"], ["f2"]) and args[0]["name"] == "Clock"
    assert data["text"] == "z" * 400 + "..." and data["finding"] == "wet wood bends" and data["outcome"] == "clue"
    assert st.project(p["id"])["findings"] == ["wet wood bends"]


async def test_an_irrelevant_experiment_counts_as_nothing_and_teaches_nothing(world):
    s, st = world
    p = add(st, questions=["q?"], hidden=["f1"])
    st.update_project(p["id"], dry=1)
    gm = StubGM(verdict={"relevant": False, "text": "Unrelated.", "finding": "ignored", "reveal": 0, "answers": 0})
    begin(st, st.project(p["id"]), kind="experiment", target="juggle", minutes=30)
    data = await proj.resolve_experiment(st, s, gm, OneRoll(0.95))
    after = st.project(p["id"])
    assert data["relevant"] is False and data["outcome"] == "nothing" and data["finding"] is None
    assert after["findings"] == [] and after["questions"] == ["q?"] and after["dry"] == 1     # not counted as dry either


async def test_relevance_defaults_to_true_when_the_gm_does_not_say(world):
    s, st = world
    p = add(st)
    gm = StubGM(verdict={"relevant": None, "text": "ok"})
    begin(st, p, kind="experiment", target="x")
    assert (await proj.resolve_experiment(st, s, gm, OneRoll(0.4)))["relevant"] is True


async def test_dry_runs_are_counted_and_the_third_is_an_insight(world):
    s, st = world
    p = add(st, questions=["q?"], hidden=["f1"])
    for expected_dry in (1, 2):
        begin(st, st.project(p["id"]), kind="experiment", target="x")
        data = await proj.resolve_experiment(st, s, None, OneRoll(0.1))
        assert data["outcome"] == "nothing" and st.project(p["id"])["dry"] == expected_dry
    begin(st, st.project(p["id"]), kind="experiment", target="x")
    data = await proj.resolve_experiment(st, s, None, OneRoll(0.4))                 # would be a clue; pity makes it an insight
    after = st.project(p["id"])
    assert data["outcome"] == "insight" and after["dry"] == 0
    assert data["finding"] == "f1" and data["answered"] == "q?"


async def test_pity_does_not_override_better_outcomes_and_a_clue_is_dry_too(world):
    s, st = world
    p = add(st, questions=["q?"], hidden=["f1"])
    st.update_project(p["id"], dry=2)
    begin(st, st.project(p["id"]), kind="experiment", target="x")
    assert (await proj.resolve_experiment(st, s, None, OneRoll(0.95), ))["outcome"] == "surprise"
    st.update_project(p["id"], dry=1)
    begin(st, st.project(p["id"]), kind="experiment", target="x")
    data = await proj.resolve_experiment(st, s, None, OneRoll(0.4))
    assert data["outcome"] == "clue" and st.project(p["id"])["dry"] == 2


async def test_a_surprise_may_open_a_new_question(world):
    s, st = world
    p = add(st, questions=["q?"], hidden=["f1"])
    gm = StubGM(verdict={"text": "t", "new_question": "and what is that?"})
    begin(st, p, kind="experiment", target="x")
    await proj.resolve_experiment(st, s, gm, OneRoll(0.95))
    assert "and what is that?" in st.project(p["id"])["questions"]


async def test_an_insight_alone_does_not_open_new_questions_and_a_clue_reveals_nothing(world):
    s, st = world
    p = add(st, questions=["q?", "q2"], hidden=["f1", "f2"])
    gm = StubGM(verdict={"text": "t", "new_question": "extra?", "finding": "a clue", "reveal": 1, "answers": 0})
    begin(st, p, kind="experiment", target="x")
    data = await proj.resolve_experiment(st, s, gm, OneRoll(0.4))                   # clue
    after = st.project(p["id"])
    assert data["outcome"] == "clue" and data["finding"] == "a clue" and data["answered"] is None
    assert after["questions"] == ["q?", "q2"] and all(not h["found"] for h in after["hidden"])
    begin(st, st.project(p["id"]), kind="experiment", target="x")
    data = await proj.resolve_experiment(st, s, gm, OneRoll(0.7))                   # insight
    after = st.project(p["id"])
    assert data["outcome"] == "insight" and data["answered"] == "q?" and after["hidden"][1]["found"] is True
    assert "extra?" not in after["questions"]


async def test_an_experiment_with_a_prediction_records_the_gap(world):
    s, st = world
    p = add(st, questions=["q?"], hidden=["f1"])
    begin(st, p, kind="experiment", target="soak it", expect="works")
    data = await proj.resolve_experiment(st, s, None, OneRoll(0.1))
    assert data["expected"] == "works" and data["surprise"] == "worse" and data["error"] == -2
    assert data["expectation"] == "you expected it to work; it failed"
    (row,) = st.expectations()
    assert (row["kind"], row["subject"], row["craft"], row["event_id"]) == ("experiment", "soak it", "clockmaking",
                                                                         st.events(limit=1)[0]["id"])


async def test_an_interrupted_experiment_shows_nothing(world):
    s, st = world
    p = add(st, questions=["q?"], hidden=["f1"])
    gm = StubGM(verdict={"text": "never"})
    begin(st, p, kind="experiment", target="soak it", minutes=60, started_at=100.0, expect="works")
    data = await proj.resolve_experiment(st, s, gm, OneRoll(0.95), now=100.0 + 300, interrupted=True)
    assert data["outcome"] == "interrupted" and data["minutes"] == 10 and data["interrupted"] is True
    assert data["text"] == "You stopped before the experiment (soak it) could show anything."
    assert data["relevant"] is True and data["finding"] is None and data["answered"] is None and data["added"] == []
    assert gm.calls == [] and "expected" not in data and st.expectations() == []
    after = st.project(p["id"])
    assert after["dry"] == 0 and after["history"][0]["interrupted"] is True and after["history"][0]["result"] == "interrupted"
    assert st.skills() == {"clockmaking": 10}


async def test_an_interrupted_experiment_cannot_exceed_the_planned_time(world):
    s, st = world
    p = add(st)
    begin(st, p, kind="experiment", target="x", minutes=20, started_at=100.0)
    data = await proj.resolve_experiment(st, s, None, OneRoll(), now=100.0 + 36000, interrupted=True)
    assert data["minutes"] == 20


async def test_long_hypotheses_are_clipped_in_the_history_stage(world):
    s, st = world
    p = add(st)
    begin(st, p, kind="experiment", target="h" * 200)
    await proj.resolve_experiment(st, s, None, OneRoll(0.1))
    assert st.project(p["id"])["history"][0]["stage"] == ("experiment: " + "h" * 200)[:80]


async def test_an_experiment_can_finish_a_project_whose_last_question_it_settles(world):
    s, st = world
    p = add(st, [{"name": "only", "minutes": 30}], questions=["q?"], hidden=["f1"])
    stages = st.project(p["id"])["stages"]
    stages[0]["progress"] = 30.0
    st.update_project(p["id"], stages=stages)
    begin(st, st.project(p["id"]), kind="experiment", target="x")
    data = await proj.resolve_experiment(st, s, None, OneRoll(0.7), now=55.0)
    after = st.project(p["id"])
    assert data["answered"] == "q?" and data["added"] == ["put it all together"]
    assert data["project_done"] is False and after["status"] == "active"           # the closing step is still to do
    assert data["crossroads"] is False and data["percent"] == 40


async def test_an_experiment_ends_the_project_when_nothing_is_left(world):
    s, st = world
    p = add(st, [{"name": "only", "minutes": 30}])
    stages = st.project(p["id"])["stages"]
    stages[0]["progress"] = 30.0
    st.update_project(p["id"], stages=stages)
    begin(st, st.project(p["id"]), kind="experiment", target="x")
    data = await proj.resolve_experiment(st, s, None, OneRoll(0.7), now=55.0)
    after = st.project(p["id"])
    assert data["project_done"] is True and after["status"] == "done" and after["finished_at"] == 55.0
    assert data["percent"] == 100 and data["crossroads"] is False


async def test_a_plan_with_no_steps_is_never_finished_by_an_experiment(world):
    s, st = world
    p = add(st, [])
    begin(st, p, kind="experiment", target="x")
    data = await proj.resolve_experiment(st, s, None, OneRoll(0.7))
    assert data["project_done"] is False and st.project(p["id"])["status"] == "active"


async def test_experiment_logs_the_fields_the_story_needs(world):
    s, st = world
    p = add(st, questions=["q?"], hidden=["f1"])
    begin(st, p, kind="experiment", target="x", minutes=25)
    data = await proj.resolve_experiment(st, s, None, OneRoll(0.7))
    assert set(data) >= {"project", "project_id", "craft", "hypothesis", "outcome", "relevant", "minutes", "text", "finding",
                         "answered", "added", "interrupted", "project_done", "percent", "crossroads"}
    assert data["project_id"] == p["id"] and data["percent"] == 0
    ev = st.events(limit=1)[0]["data"]
    assert ev["hypothesis"] == "x" and ev["finding"] == "f1"


# --- revise -------------------------------------------------------------------------------------------------------
def steps_(*names):
    return [{"name": n, "minutes": 30, "guess": 30, "materials": {}} for n in names]


async def test_revising_without_a_reason_edits_the_plan_and_logs_it(world):
    s, st = world
    p = add(st, [{"name": "cut", "minutes": 30}, {"name": "fit", "minutes": 30}])
    gm = StubGM(revision={"text": "Looks sensible.", "steps": [{"abilities": ["patience"], "minutes": 90}]})
    changes, msg = await proj.revise(st, gm, p, steps_("paint"), ["fit"], "")
    assert changes == {"finding": None, "answered": None, "added": ["paint"], "dropped": ["fit"]}
    assert msg == "Looks sensible."
    (args,) = gm.asked("revise")
    assert args[0] is p and args[1][0]["name"] == "paint" and args[2] == ""
    after = st.project(p["id"])
    assert [x["name"] for x in after["stages"]] == ["cut", "paint"]
    assert after["stages"][1]["abilities"] == ["patience"] and after["stages"][1]["minutes"] == 90
    ev = st.events(limit=1)[0]
    assert ev["kind"] == "plan_revised" and ev["data"]["project"] == "Clock" and ev["data"]["project_id"] == p["id"]
    assert ev["data"]["because"] == "" and ev["data"]["added"] == ["paint"] and ev["data"]["dropped"] == ["fit"]


async def test_dropping_steps_alone_does_not_bother_the_gm(world):
    s, st = world
    p = add(st)
    gm = StubGM(revision={"text": "never seen"})
    changes, msg = await proj.revise(st, gm, p, [], ["cut"], "")
    assert gm.calls == [] and msg == "" and changes["dropped"] == ["cut"]


async def test_revising_with_no_gm_still_works(world):
    s, st = world
    p = add(st)
    changes, msg = await proj.revise(st, None, p, steps_("paint"), [], "")
    assert changes["added"] == ["paint"] and msg == ""
    assert st.project(p["id"])["stages"][-1]["abilities"] == ["handiness"]


async def test_a_reason_before_any_new_experience_does_not_count(world):
    s, st = world
    p = add(st, questions=["q?"], hidden=["f1"])
    gm = StubGM(revision={"accepted": True, "text": "Yes!"})
    changes, msg = await proj.revise(st, gm, p, [], [], "I learned a lot")
    assert changes["finding"] is None and changes["answered"] is None and gm.calls == []
    assert msg == "(what you learned will count once you've worked or experimented again)"
    assert st.project(p["id"])["questions"] == ["q?"]


async def test_the_note_is_appended_after_the_gms_words(world):
    s, st = world
    p = add(st)
    gm = StubGM(revision={"text": "Fine."})
    _, msg = await proj.revise(st, gm, p, steps_("x"), [], "reason")
    assert msg == "Fine. (what you learned will count once you've worked or experimented again)"


async def test_an_accepted_reason_after_new_experience_answers_and_reveals(world):
    s, st = world
    p = add(st, questions=["q1", "q2"], hidden=["fact a", "fact b"])
    st.update_project(p["id"], history=[{"ts": 1, "stage": "cut", "result": "good", "minutes": 5, "text": "t", "interrupted": False}])
    p = st.project(p["id"])
    gm = StubGM(revision={"accepted": True, "text": "Yes, that explains it.", "reveal": 1, "answers": 0, "finding": "",
                          "steps": []})
    changes, msg = await proj.revise(st, gm, p, steps_("extra"), [], "because I saw the wire bend")
    (args,) = gm.asked("revise")
    assert args[2] == "because I saw the wire bend"
    assert changes["finding"] == "fact b" and changes["answered"] == "q1" and changes["added"] == ["extra"]
    assert msg == "Yes, that explains it."
    after = st.project(p["id"])
    assert after["revised_at"] == 1 and after["questions"] == ["q2"] and after["hidden"][1]["found"] is True
    assert after["findings"] == ["fact b"]
    ev = st.events(limit=1)[0]["data"]
    assert ev["because"] == "because I saw the wire bend" and ev["finding"] == "fact b" and ev["answered"] == "q1"


async def test_settling_the_last_question_by_revision_lists_the_closing_step_among_the_added(world):
    s, st = world
    p = add(st, [{"name": "only", "minutes": 30}], questions=["last"])
    stages = st.project(p["id"])["stages"]
    stages[0]["progress"] = 30.0
    st.update_project(p["id"], stages=stages, history=[{"ts": 1, "stage": "only", "result": "good", "minutes": 5, "text": "t",
                                                        "interrupted": False}])
    p = st.project(p["id"])
    gm = StubGM(revision={"accepted": True, "answers": 0})
    changes, _ = await proj.revise(st, gm, p, [], [], "it works now")
    assert changes["added"] == ["put it all together"] and changes["answered"] == "last"


async def test_a_declined_reason_is_remembered_so_it_cannot_be_repeated(world):
    s, st = world
    p = add(st, questions=["q?"])
    st.update_project(p["id"], history=[{"ts": 1, "stage": "cut", "result": "good", "minutes": 5, "text": "t", "interrupted": False},
                                        {"ts": 2, "stage": "cut", "result": "good", "minutes": 5, "text": "t", "interrupted": False}])
    p = st.project(p["id"])
    gm = StubGM(revision={"accepted": False, "text": "Not convinced."})
    changes, msg = await proj.revise(st, gm, p, [], [], "trust me")
    assert msg == "Not convinced." and changes["answered"] is None and st.project(p["id"])["revised_at"] == 2
    gm2 = StubGM(revision=None)
    p = st.project(p["id"])
    changes, msg = await proj.revise(st, gm2, p, [], [], "trust me again")
    assert gm2.calls == [] and msg == "(what you learned will count once you've worked or experimented again)"


async def test_a_declined_reason_with_no_comment_gets_a_plain_answer(world):
    s, st = world
    p = add(st, questions=["q?"])
    st.update_project(p["id"], history=[{"ts": 1, "stage": "cut", "result": "good", "minutes": 5, "text": "t", "interrupted": False}])
    p = st.project(p["id"])
    changes, msg = await proj.revise(st, StubGM(revision={"accepted": "yes"}), p, [], [], "because")
    assert msg == "that doesn't change what you need to do" and st.project(p["id"])["revised_at"] == 1


async def test_a_reason_with_nothing_left_to_learn_is_not_put_to_the_gm(world):
    s, st = world
    p = add(st)
    st.update_project(p["id"], history=[{"ts": 1, "stage": "cut", "result": "good", "minutes": 5, "text": "t", "interrupted": False}])
    p = st.project(p["id"])
    gm = StubGM(revision={"accepted": True, "text": "yes"})
    changes, msg = await proj.revise(st, gm, p, [], [], "because")
    assert gm.calls == [] and msg == "that doesn't change what you need to do" and changes["answered"] is None


async def test_an_unfound_hidden_fact_alone_counts_as_something_to_learn(world):
    s, st = world
    p = add(st, hidden=["f1"])
    st.update_project(p["id"], history=[{"ts": 1, "stage": "cut", "result": "good", "minutes": 5, "text": "t", "interrupted": False}])
    p = st.project(p["id"])
    gm = StubGM(revision={"accepted": True, "reveal": 0})
    changes, _ = await proj.revise(st, gm, p, [], [], "because")
    assert len(gm.asked("revise")) == 1 and changes["finding"] == "f1"


async def test_a_long_reason_is_clipped_in_the_log_and_a_long_reply_too(world):
    s, st = world
    p = add(st)
    gm = StubGM(revision={"text": "w" * 500})
    _, msg = await proj.revise(st, gm, p, steps_("x"), [], "b" * 500)
    assert msg.startswith("w" * 300 + "...")
    assert st.events(limit=1)[0]["data"]["because"] == "b" * 200 + "..."


async def test_revising_saves_every_changed_field(world):
    s, st = world
    p = add(st, difficulty=2, questions=["q?"])
    st.update_project(p["id"], history=[{"ts": 1, "stage": "cut", "result": "good", "minutes": 5, "text": "t", "interrupted": False}])
    p = st.project(p["id"])
    gm = StubGM(revision={"accepted": True, "answers": 0, "difficulty_delta": 1, "finding": "known", "text": "ok"})
    await proj.revise(st, gm, p, steps_("x"), [], "because")
    after = st.project(p["id"])
    assert after["difficulty"] == 3 and after["findings"] == ["known"] and after["revised_at"] == 1
    assert after["dry"] == 0 and [x["name"] for x in after["stages"]][-1] == "x"
