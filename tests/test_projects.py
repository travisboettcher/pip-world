import random
import time

import pytest

from app import projects as proj
from app import tools as tools_mod
from app.config import Settings
from app.llm.base import LLMResponse, ToolCall, Usage
from app.llm.fake import FakeBackend
from app.loop import Agent
from app.pacing import get_policy
from app.state import State

PLAN = {"craft": "Clockmaking", "difficulty": 3, "tools": ["needle file", "tweezers"], "stages": [
    {"name": "cut the wheels", "minutes": 60, "materials": {"brass wire": 2}},
    {"name": "fit the escapement", "minutes": 30},
]}


def report(**args):
    return LLMResponse("", [ToolCall("r", "report", args)], Usage(10, 5))


class FixedRng(random.Random):
    def __init__(self, *values):
        super().__init__(0)
        self.values = list(values)

    def random(self):
        return self.values.pop(0) if self.values else 0.5


def make(tmp_path, gm_script=None, rng=None, **kw):
    kw.setdefault("reflect_hour", 99)  # no nightly reflection unless a test asks for one
    kw.setdefault("neighbor", False)    # no neighbor unless a test asks for one
    s = Settings(db_path=str(tmp_path / "t.db"), persona_path="/nonexistent", persona_default_path="/nonexistent",
                 tools=["set_activity", "eat", "rest", "note_to_self", "use_item", "start_project", "work_on",
                        "abandon_project", "experiment", "revise_plan"], min_tick_interval=0, **kw)
    st = State(s)
    gm = FakeBackend(gm_script)
    agent = Agent(s, st, FakeBackend(), get_policy(s), gm_backend=gm, rng=rng or FixedRng())
    return s, st, gm, agent


PIP_STEPS = [{"name": st["name"], "minutes": st["minutes"], "materials": st.get("materials", {})}
             for st in PLAN["stages"]]


THREE_STEPS = [{"name": "gather and shape the pieces", "minutes": 45}, {"name": "put it together", "minutes": 60},
               {"name": "finish and test", "minutes": 45}]


def call(agent, tool, **args):
    if tool == "start_project":  # the plan is Pip's: default steps unless a test supplies its own
        args.setdefault("steps", PIP_STEPS if "clock" in args["name"].lower() else THREE_STEPS)
    return tools_mod.REGISTRY[tool][1](agent.ctx, args)


def test_sanitize_stages_and_build_plan_keep_the_plan_pips():
    steps = proj.sanitize_stages([{"name": "one", "minutes": 5000, "materials": {"Brass": 6, "wood": 6}}, {"name": " "},
                                  "junk", {"name": "two", "abilities": ["patience", "bogus"]}], 5)
    assert steps[0] == {"name": "one", "minutes": 240, "materials": {"brass": 6, "wood": 2}, "abilities": ["handiness"]}
    assert [x["name"] for x in steps] == ["one", "junk", "two"] and steps[2]["abilities"] == ["patience"]  # 8 units max
    plan = proj.build_plan(steps, {"craft": "Clockmaking (gears)", "difficulty": 9, "tools": list("abcd"),
                                   "steps": [{"abilities": ["precision"], "minutes": 90}, "junk", {"minutes": 1}],
                                   "open_questions": ["why?"], "hidden": ["because"]})
    assert plan["difficulty"] == 5 and plan["craft"] == "clockmaking" and len(plan["tools"]) == 3
    assert [x["name"] for x in plan["stages"]] == ["one", "junk", "two"]  # the GM never renames, adds or drops
    assert plan["stages"][0]["abilities"] == ["precision"] and plan["stages"][0]["minutes"] == 90
    assert plan["questions"] == ["why?"] and plan["hidden"] == [{"fact": "because", "found": False}]
    bare = proj.build_plan(steps, None)
    assert bare["craft"] == "tinkering" and bare["questions"] == [] and len(bare["stages"]) == 3


def test_verdicts_are_bounded_by_the_die():
    assert proj.clamp_verdict("good", "breakthrough") == "breakthrough" and proj.clamp_verdict("good", "setback") == "slow"
    assert proj.clamp_verdict("good", "blowup") == "slow"          # at most one step worse
    assert proj.clamp_verdict("setback", "blowup") == "blowup"     # a bad roll plus a bad approach can blow up
    assert proj.clamp_verdict("slow", "breakthrough") == "good"
    assert proj.clamp_verdict("slow", "nonsense") == "slow"


def test_roll_is_shaped_by_skill_tools_difficulty_fatigue():
    def r(v, **kw):
        args = {"skill_level": 0, "tools_owned": 0, "difficulty": 1, "energy": 1.0} | kw
        return proj.roll(FixedRng(v), **args)
    assert [r(v) for v in (0.1, 0.3, 0.6, 0.95)] == ["setback", "slow", "good", "breakthrough"]
    assert r(0.1, skill_level=2) == "slow"           # practice helps
    assert r(0.86, tools_owned=1) == "breakthrough"  # so does the right tool
    assert r(0.2, difficulty=3) == "setback"         # hard things go wrong more
    assert r(0.2, energy=0.1) == "setback"           # so does working tired
    assert [proj.level(x) for x in (0, 59, 60, 240, 99999)] == [0, 0, 1, 2, 5]


@pytest.mark.asyncio
async def test_start_project_uses_gm_plan_and_reports_stages(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**PLAN)])
    r = await call(agent, "start_project", name="gear clock", goal="keeps time")
    assert r.followup and "started project #1 gear clock (clockmaking, difficulty 3/5)" in r.text
    assert "needs 2 brass wire" in r.text
    assert "gear clock" in gm.calls[0]["messages"][0]["content"] and gm.calls[0]["tools"] == ["report"]
    assert st.usage_today()["calls"] == 1  # GM calls count against the budget
    assert "already working on" in (await call(agent, "start_project", name="Gear Clock")).text


@pytest.mark.asyncio
async def test_gm_failure_falls_back_to_a_generic_plan(tmp_path):
    s, st, gm, agent = make(tmp_path, [LLMResponse("I'd rather not", [], Usage(1, 1))])
    r = await call(agent, "start_project", name="kite")
    assert "Your plan: 1. gather and shape the pieces" in r.text
    assert any(e["kind"] == "gm_error" for e in st.events(5))


@pytest.mark.asyncio
async def test_project_limit(tmp_path):
    s, st, gm, agent = make(tmp_path, max_active_projects=1)
    await call(agent, "start_project", name="kite")
    assert "abandon_project one first" in (await call(agent, "start_project", name="boat")).text
    assert "abandoned kite" in (await call(agent, "abandon_project", project="kite")).text
    assert "started project" in (await call(agent, "start_project", name="boat")).text


@pytest.mark.asyncio
async def test_work_needs_materials_then_takes_them(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**PLAN)])
    await call(agent, "start_project", name="gear clock")
    st.add_item("brass wire", 1, "material")
    r = await call(agent, "work_on", project="clock")
    assert r.followup and "needs 2 brass wire (you have 1)" in r.text and not st.session()
    st.add_item("brass wire", 2, "material")
    r = await call(agent, "work_on", project="#1", minutes=500)
    assert "for 120 min" in r.text  # clamped
    assert st.find_item("brass wire")[0]["qty"] == 1
    assert st.agent()["activity"] == "working"
    assert "already working on gear clock" in (await call(agent, "work_on", project="gear clock")).text


@pytest.mark.asyncio
async def test_session_resolves_with_roll_and_narration_then_wakes(tmp_path):
    narr = report(text="You cut two wheels cleanly.")
    s, st, gm, agent = make(tmp_path, [report(**PLAN), narr], rng=FixedRng(0.6), work_speed=1e6)
    st.add_item("brass wire", 2, "material")
    await call(agent, "start_project", name="gear clock")
    await call(agent, "work_on", project="gear clock", minutes=40)
    time.sleep(0.01)
    await agent.resolve_world()
    assert agent._wake.is_set() and not st.session()
    p = st.project(1)
    assert p["stages"][0]["progress"] == 40 and p["history"][0]["result"] == "good"
    assert st.skills() == {"clockmaking": 40}
    w = st.events(5)[0]
    assert w["kind"] == "work" and w["data"]["text"] == "You cut two wheels cleanly." and w["data"]["percent"] == 44
    assert st.agent()["activity"] == "idle"
    narrate_prompt = gm.calls[1]["messages"][0]["content"]
    assert "result (already decided, don't change it): good" in narrate_prompt
    assert "NOT finished yet" in narrate_prompt and "brass wire" in narrate_prompt


@pytest.mark.asyncio
async def test_finishing_all_stages_completes_the_project(tmp_path):
    s, st, gm, agent = make(tmp_path, rng=FixedRng(0.99, 0.99), work_speed=1e6)  # GM silent: fallback plan/text
    await call(agent, "start_project", name="kite")
    for _ in range(3):
        await call(agent, "work_on", project="kite", minutes=60)
        time.sleep(0.01)
        await agent.resolve_world()
    p = st.project(1)
    assert p["status"] == "done" and p["finished_at"]
    done = next(e["data"] for e in st.events(5) if e["kind"] == "work")
    assert done["project_done"] and done["percent"] == 100
    assert st.creations()[0]["name"] == "kite"  # GM silent: a plain keepsake
    assert "already finished" not in (await call(agent, "work_on", project="kite")).text  # not active any more
    assert proj.quality(p, 0) == "fine"  # two breakthroughs


@pytest.mark.asyncio
async def test_set_activity_while_working_only_describes_it(tmp_path):
    s, st, gm, agent = make(tmp_path)
    await call(agent, "start_project", name="kite")
    await call(agent, "work_on", project="kite")
    r = await call(agent, "set_activity", activity="careful sewing", description="Stitching slowly.", mood="calm")
    assert r.text.startswith("(still busy) you're in the middle of working on kite") and st.session()
    a = st.agent()
    assert (a["activity"], a["description"], a["mood"]) == ("working", "Stitching slowly.", "calm")


@pytest.mark.asyncio
async def test_resting_cuts_session_short_at_half_credit(tmp_path):
    s, st, gm, agent = make(tmp_path)
    await call(agent, "start_project", name="kite")
    await call(agent, "work_on", project="kite", minutes=60)
    sess = st.session()
    st.db.execute("UPDATE work_session SET started_at = ?", (sess["started_at"] - 20 * 60,))  # 20 min in
    r = await call(agent, "rest")
    assert "stopped working on kite early" in r.text and not st.session()
    p = st.project(1)
    assert p["stages"][0]["progress"] == pytest.approx(10, abs=0.1) and p["history"][0]["interrupted"]
    assert len(gm.calls) == 1  # only the plan: no narration for an interrupted session


@pytest.mark.asyncio
async def test_eating_does_not_interrupt_work(tmp_path):
    s, st, gm, agent = make(tmp_path)
    await call(agent, "start_project", name="kite")
    await call(agent, "work_on", project="kite")
    await call(agent, "eat")
    assert st.session() and st.agent()["activity"] == "working"


@pytest.mark.asyncio
async def test_working_drains_extra_energy(tmp_path):
    s, st, gm, agent = make(tmp_path)
    await call(agent, "start_project", name="kite")
    await call(agent, "work_on", project="kite")
    t = st.agent()["updated_at"]
    st.apply_decay(t + 3600)
    assert st.agent()["energy"] == pytest.approx(0.9 - 0.05 - 0.05)


@pytest.mark.asyncio
async def test_heartbeat_waits_for_the_session(tmp_path):
    s, st, gm, agent = make(tmp_path, heartbeat_seconds=0.01)
    await call(agent, "start_project", name="kite")
    await call(agent, "work_on", project="kite")
    import asyncio
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(agent._sleep(), timeout=0.2)  # would return "timer" at once if not working
    st.end_session()
    assert await asyncio.wait_for(agent._sleep(), timeout=1) == "timer"


@pytest.mark.asyncio
async def test_perception_and_moments_show_projects(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**PLAN), report(text="A tooth snapped off.")],
                            rng=FixedRng(0.0), work_speed=1e6)
    st.add_item("brass wire", 2, "material")
    await agent._run_tool(ToolCall("1", "start_project", {"name": "gear clock", "steps": PIP_STEPS}), 0)  # logs the tool event
    await call(agent, "work_on", project="gear clock")
    time.sleep(0.01)
    await agent.resolve_world()
    p = agent._perception("event", [])
    assert "#1 gear clock (clockmaking, difficulty 3/5): 0% done, now on stage 1/2 'cut the wheels' " \
           "(its 2 brass wire are already in hand)" in p
    assert "Your experience: getting the hang of clockmaking" in p and "Your skills" not in p
    assert "How you've grown:" in p and "(handiness)" in p
    assert "work on gear clock (cut the wheels): setback - A tooth snapped off." in p
    assert "You started a new project: gear clock" in p
    assert "Working on gear clock: A tooth snapped off." in p
    assert proj.scars(st.project(1)) == ["A tooth snapped off."]


def test_clip_cuts_at_sentence_end():
    from app.gm import clip
    assert clip("  short   text ", 50) == "short text"
    assert clip("First sentence here. Second one runs far too long to fit.", 40) == "First sentence here."
    assert clip("no sentence end anywhere in this long line", 20) == "no sentence end..."


def test_upcoming_needs_and_narration_sees_earlier_sessions():
    p = {"stages": [{"materials": {"wire": 2}, "started": True}, {"materials": {"wire": 1, "cloth": 2}, "started": False},
                    {"materials": {"wire": 3}, "started": False}]}
    assert proj.upcoming_needs(p, 1) == {"wire": 4, "cloth": 2} and proj.upcoming_needs(p, 3) == {}


@pytest.mark.asyncio
async def test_perception_lists_later_stage_needs_against_belongings(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**PLAN)])
    st.add_item("brass wire", 1, "material")
    await call(agent, "start_project", name="gear clock", steps=[PIP_STEPS[1], PIP_STEPS[0]])
    assert "later stages need 2 brass wire (you have 1)" in agent._perception("event", [])


@pytest.mark.asyncio
async def test_tick_resolves_a_session_that_just_ended_before_looking(tmp_path):
    s, st, gm, agent = make(tmp_path, rng=FixedRng(0.6), work_speed=1e6)
    await call(agent, "start_project", name="kite")
    await call(agent, "work_on", project="kite")
    time.sleep(0.01)  # time is up, but the monitor hasn't run yet
    await agent.tick("timer")
    assert not st.session() and st.project(1)["history"][0]["result"] == "good"
    prompt = agent.backend.calls[0]["messages"][0]["content"]
    assert "work on kite (gather and shape the pieces): good" in prompt and "you're working on it now" not in prompt


def test_craft_names_are_the_core_skill_and_old_ones_are_folded_in(tmp_path):
    from app.text import craft_name
    assert craft_name("Clockmaking (gear train, escapement)") == "clockmaking"
    assert craft_name("rough carpentry and tying") == "rough carpentry"  # at most 3 words, no dangling "and"
    assert craft_name("Poetry writing") == "poetry writing" and craft_name("") == "tinkering"
    s, st, *_ = make(tmp_path)
    st.add_project("clock", "", "clockmaking (gear train, escap", 5, [], [])
    st.add_xp("clockmaking (gear train, escap", 60)
    st.add_xp("clockmaking", 30)
    st2 = State(s)  # restart
    assert st2.project(1)["craft"] == "clockmaking" and st2.skills() == {"clockmaking": 90}


# --- abilities, arbitration and discovery ----------------------------------------------
PARTIAL = {"craft": "clockmaking", "difficulty": 3, "steps": [{"abilities": ["precision", "bogus"]}],
           "open_questions": ["why does it run fast?", "what powers it?"],
           "hidden": ["the pallets are too steep", "a heavier weight would drive it"]}
FRAME = [{"name": "build the frame", "minutes": 30}]


@pytest.mark.asyncio
async def test_start_needs_pips_own_steps_and_gm_reviews_them(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**PARTIAL, concerns="Brass won't bend that way.")])
    r = await tools_mod.REGISTRY["start_project"][1](agent.ctx, {"name": "gear clock"})
    assert "sketch at least the first step" in r.text and not gm.calls  # no GM-written plan
    r = await call(agent, "start_project", name="gear clock", steps=FRAME)
    p = st.project(1)
    assert [x["name"] for x in p["stages"]] == ["build the frame"] and p["stages"][0]["abilities"] == ["precision"]
    assert "Your plan: 1. build the frame" in r.text and "A thought on your plan: Brass won't bend" in r.text
    assert "What you don't know yet: why does it run fast?; what powers it?" in r.text
    assert "Pip's own plan" in gm.calls[0]["messages"][0]["content"] and "do not rewrite" in gm.calls[0]["messages"][0]["content"]
    assert p["questions"] == PARTIAL["open_questions"] and [h["found"] for h in p["hidden"]] == [False, False]


@pytest.mark.asyncio
async def test_work_trains_abilities_that_help_other_crafts(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**PARTIAL), report(text="You measure carefully.")], work_speed=10**6)
    await call(agent, "start_project", name="gear clock", steps=FRAME)
    await call(agent, "work_on", project="gear clock", minutes=60)
    time.sleep(0.01)
    await agent.resolve_world()
    assert st.abilities()["precision"] == pytest.approx(60, abs=1)
    assert proj.skill_for(st, {"craft": "painting"}, ["precision"]) == 1.0  # a different craft still benefits
    assert proj.skill_for(st, {"craft": "clockmaking"}, ["precision"]) > 1.0  # plus familiarity


@pytest.mark.asyncio
async def test_finished_known_stages_leave_a_crossroads_not_a_finished_project(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(**PARTIAL), report(text="It goes together.")], work_speed=10**6)
    await call(agent, "start_project", name="gear clock", steps=FRAME)
    await call(agent, "work_on", project="gear clock", minutes=60)
    time.sleep(0.05)
    await agent.resolve_world()
    p = st.project(1)
    assert p["status"] == "active" and proj.crossroads(p) and proj.percent(p) == 99
    assert "the way forward isn't clear" in agent._perception("event", [])
    assert "Try an experiment" in (await call(agent, "work_on", project="gear clock")).text


async def worked(tmp_path, die, gm_script, approach, **kw):
    s, st, gm, agent = make(tmp_path, [report(**{**PARTIAL, "open_questions": [], "hidden": []})] + gm_script,
                            rng=FixedRng(die), work_speed=10**6, **kw)
    st.add_item("brass wire", 4, "material")
    await call(agent, "start_project", name="gear clock", steps=PIP_STEPS)
    await call(agent, "work_on", project="gear clock", minutes=60, approach=approach)
    time.sleep(0.05)
    await agent.resolve_world()
    return s, st, gm, agent


@pytest.mark.asyncio
async def test_gm_arbitrates_the_approach_within_one_step_of_the_die(tmp_path):
    # the die says "good" (0.6); a clever approach lifts it to a breakthrough, but never beyond one step
    s, st, gm, agent = await worked(tmp_path, 0.6, [report(verdict="breakthrough", text="The trick works.",
                                                            finding="Tempering the wire first helps.")],
                                    "temper the wire before shaping it")
    h = st.project(1)["history"][0]
    assert h["result"] == "breakthrough" and st.project(1)["findings"] == ["Tempering the wire first helps."]
    task = [c for c in gm.calls if "temper the wire" in c["messages"][0]["content"]]
    assert task and "die says" in task[0]["messages"][0]["content"]
    w = [e for e in st.events(20) if e["kind"] == "work"][0]["data"]
    assert w["approach"] == "temper the wire before shaping it" and w["learned"] == "Tempering the wire first helps."


@pytest.mark.asyncio
async def test_a_reckless_approach_can_only_blow_up_on_a_bad_roll(tmp_path):
    ruling = report(verdict="blowup", text="The wire snaps and whips your hand.")
    s, st, gm, agent = await worked(tmp_path, 0.1, [ruling], "bend it cold, as hard as I can")  # die: setback
    p = st.project(1)
    assert p["history"][0]["result"] == "blowup" and p["stages"][0]["progress"] == 0
    assert st.agent()["energy"] < 0.9 - 0.05 and st.find_item("brass wire")[0]["qty"] == 1  # 2 used at the start, 1 lost
    (tmp_path / "b").mkdir()
    s, st, gm, agent = await worked(tmp_path / "b", 0.6, [ruling], "bend it cold, as hard as I can")  # die: good
    assert st.project(1)["history"][0]["result"] == "slow"  # one step worse at most


@pytest.mark.asyncio
async def test_no_approach_means_the_die_decides_and_the_gm_only_narrates(tmp_path):
    s, st, gm, agent = await worked(tmp_path, 0.6, [report(text="You cut two wheels.")], "")
    assert st.project(1)["history"][0]["result"] == "good"
    assert not any("describe" in c["messages"][0]["content"] and "approach" in c["messages"][0]["content"] for c in gm.calls[1:])


def rolled(outcome):  # a rng that produces a given experiment outcome (score is ~0 at skill 0, difficulty 1)
    return FixedRng({"nothing": 0.1, "clue": 0.45, "insight": 0.75, "surprise": 0.95}[outcome])


async def started(tmp_path, outcome, gm_script, **kw):
    s, st, gm, agent = make(tmp_path, [report(**{**PARTIAL, "difficulty": 1})] + gm_script, rng=rolled(outcome),
                            work_speed=10**6, **kw)
    await call(agent, "start_project", name="gear clock", steps=FRAME)
    return s, st, gm, agent


async def run_experiment(agent, st, hypothesis="a heavier weight might drive the train"):
    r = await call(agent, "experiment", project="gear clock", hypothesis=hypothesis, minutes=30)
    time.sleep(0.05)
    await agent.resolve_world()
    return r


@pytest.mark.asyncio
async def test_insight_reveals_a_fact_and_answers_a_question_but_pip_adds_the_steps(tmp_path):
    s, st, gm, agent = await started(tmp_path, "insight", [report(
        relevant=True, text="The heavier weight spins it up at once.", finding="A heavier weight drives it.",
        reveal=1, answers=1, new_stages=[{"name": "GM wrote this", "minutes": 20}])])
    r = await run_experiment(agent, st)
    assert "set up an experiment" in r.text
    p = st.project(1)
    assert p["findings"] == ["A heavier weight drives it."] and p["hidden"][1]["found"] and not p["hidden"][0]["found"]
    assert p["questions"] == ["why does it run fast?"] and p["dry"] == 0
    assert "GM wrote this" not in [x["name"] for x in p["stages"]]  # the plan is Pip's
    assert p["history"][-1]["kind"] == "experiment" and st.abilities()["ingenuity"] > 0


@pytest.mark.asyncio
async def test_irrelevant_hypotheses_learn_nothing_and_dont_count_as_dry(tmp_path):
    s, st, gm, agent = await started(tmp_path, "insight", [report(relevant=False, text="Nothing to do with the clock.",
                                                                  finding="should be ignored", reveal=0)])
    await run_experiment(agent, st, "what if I paint it blue and sing")
    p = st.project(1)
    assert p["findings"] == [] and not any(h["found"] for h in p["hidden"]) and p["dry"] == 0
    assert [e["data"]["outcome"] for e in st.events(50) if e["kind"] == "experiment"] == ["nothing"]


@pytest.mark.asyncio
async def test_pity_timer_turns_the_third_dry_experiment_into_an_insight(tmp_path):
    dry = report(relevant=True, text="Nothing.")
    s, st, gm, agent = await started(tmp_path, "nothing", [dry, dry, report(relevant=True, text="There!", reveal=0)])
    for _ in range(3):
        await run_experiment(agent, st)
    p = st.project(1)
    assert p["hidden"][0]["found"] and p["dry"] == 0 and p["findings"] == [p["hidden"][0]["fact"]]


@pytest.mark.asyncio
async def test_experiment_works_without_the_gm_and_settling_the_last_question_leaves_a_final_stage(tmp_path):
    s, st, gm, agent = await started(tmp_path, "insight", [])
    st.update_project(1, questions=["only question"], stages=[{**st.project(1)["stages"][0], "progress": 30}])
    await run_experiment(agent, st)  # GM script is empty: fallback text, first fact revealed
    p = st.project(1)
    assert p["questions"] == [] and p["hidden"][0]["found"] and p["findings"]
    assert p["stages"][-1]["name"] == "put it all together" and p["status"] == "active"


@pytest.mark.asyncio
async def test_pip_edits_its_own_plan_freely_and_research_needs_new_experience(tmp_path):
    s, st, gm, agent = await started(tmp_path, "clue", [
        report(steps=[{"abilities": ["patience"]}], text="Fine."),   # annotates the first edit
        report(relevant=True, text="A faint hint."),                  # the experiment
        report(steps=[{"abilities": ["precision"], "minutes": 40}], text="Sensible.", accepted=True, answers=0,
               finding="Pallet angle matters.")])
    # steps are Pip's to add or drop at any time; no experience needed
    r = await call(agent, "revise_plan", project="gear clock", steps=[{"name": "file the pallets", "minutes": 30}],
                   drop=["build the frame"])
    p = st.project(1)
    assert "added: file the pallets" in r.text and "dropped: build the frame" in r.text
    assert [x["name"] for x in p["stages"]] == ["file the pallets"]
    # a knowledge claim before any new experience doesn't count yet (steps still apply)
    st.update_project(1, history=[])
    r = await call(agent, "revise_plan", project="gear clock", because="a library book says pallet angle matters")
    assert "will count once you've worked or experimented again" in r.text and p["questions"] == PARTIAL["open_questions"]
    await run_experiment(agent, st)
    r = await call(agent, "revise_plan", project="gear clock", because="a library book says pallet angle matters",
                   steps=[{"name": "set the angle", "minutes": 20}])
    p = st.project(1)
    assert "settled: why does it run fast?" in r.text and p["findings"] == ["Pallet angle matters."]
    assert [x["name"] for x in p["stages"]][-1] == "set the angle" and p["stages"][-1]["abilities"] == ["precision"]
    assert p["revised_at"] == len(p["history"])
    r = await call(agent, "revise_plan", project="gear clock", because="a visitor said something vague about gears")
    assert "will count once" in r.text  # one claim per bit of new experience
    assert "error" in (await call(agent, "revise_plan", project="gear clock")).text


@pytest.mark.asyncio
async def test_interrupted_experiment_teaches_nothing(tmp_path):
    s, st, gm, agent = await started(tmp_path, "insight", [])
    await call(agent, "experiment", project="gear clock", hypothesis="try a different spring", minutes=60)
    r = await call(agent, "rest")
    assert "cut the experiment" in r.text and st.project(1)["findings"] == []
