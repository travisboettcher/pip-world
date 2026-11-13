"""Crafting (docs/DESIGN-world-packs.md, phase 5f): the shipped `crafting` module (module_library/crafting.py): projects on the agent's own
plans, work sessions judged by the die and the narrator, materials, experiments, plan revisions, craft skills, what a finished project turns
out to be, and the night pass's requests."""
import random
import time

import pytest

from app import modules as M
from tests.test_projects import PIP_STEPS, THREE_STEPS, call, crafting, make, report

NOW = time.time()
REVIEW = {"craft": "Clockmaking", "difficulty": 3, "tools": ["needle file"], "steps": [{"abilities": ["precision"], "minutes": 60}, {"abilities": ["patience"]}]}


def code():
    out = {}
    exec(M.library("crafting")[1], out)
    return out


G = code()
PARAMS = {"speed": 1.0, "most": 3, "cap": 6, "abilities": ["precision", "patience", "ingenuity", "knowledge", "handiness"], "default_abilities": ["handiness"]}


def ctx_of(store=None, **kw):
    """A context as the module sees it, for its pure parts."""
    return {"params": dict(PARAMS), "store": store or {}, "abilities": {}, "items": [], "found": [], "now": NOW, "seed": 1,
            "agent": {"name": "Pip", "they": "it", "them": "it", "their": "its", "possessive": "Pip's", "busy": "", "tired": False, "tiring": "energy",
                      "activity": "idle"}, **kw}


def world(tmp_path, script=None, **kw):
    s, st, gm, agent = make(tmp_path, script, work_speed=1e6, **kw)
    crafting(st)
    return s, st, gm, agent


def store(st):
    return st.store("crafting")


def project(st, pid=1):
    return store(st)["projects"][str(pid)]


async def end(agent, now=None):
    """The session's time is up: the module hears it (at `now`, so the die's seed is known)."""
    st = agent.state
    m = M.live_named(st, "crafting")
    sess = st.session()
    st.end_session()
    return await M.call(st, agent.s, M.LocalRunner(), m, "on_time", now or time.time(),
                        session={"label": sess["expect"], "interrupted": False, "minutes": 1})


def moment_for(result, skill, tools, difficulty, tired=False, pid=None):
    """A moment whose seed makes the die say `result` (for the crafting module, id `pid`)."""
    for t in range(int(NOW), int(NOW) + 5000):
        if G["roll"](random.Random(t * 7919 + pid), skill, tools, difficulty, tired) == result:
            return float(t)
    raise AssertionError(result)


def die_says(st, s, result, pid=1):
    """A moment whose seed makes the die say `result` for the session now under way on project `pid`, as the module would roll it (its
    real context: skill, tools, difficulty, tiredness)."""
    m = M.live_named(st, "crafting")
    c = M.context(st, s, m, time.time())
    p = c["store"]["projects"][str(pid)]
    now = c["store"]["now"]["session"]
    for t in range(int(NOW), int(NOW) + 20000):
        rng = random.Random(t * 7919 + m["id"])
        if now["kind"] == "experiment":
            got = G["roll_experiment"](rng, G["skill_for"](c, p, G["EXPERIMENT_ABILITIES"]), p["difficulty"], c["agent"]["tired"])
        else:
            stage = p["stages"][now["stage"]]
            got = G["roll"](rng, G["skill_for"](c, p, G["stage_abilities"](c, stage)), G["tools_owned"](c, p), p["difficulty"], c["agent"]["tired"])
        if got == result:
            return float(t)
    raise AssertionError(result)


def events(st, kind):
    return [e["data"] for e in st.events(40) if e["kind"] == kind]


# --- the plan is the agent's ---------------------------------------------------------------------------------------------------------
def test_steps_become_stages_and_junk_is_dropped():
    c = ctx_of()
    got = G["sanitize_stages"](c, ["shape it", {"name": " cut ", "minutes": 999, "materials": {"Brass Wire": 3, "cog": "x", " ": 2}}, {"minutes": 5}, 7,
                                   {"name": "x", "minutes": "x", "abilities": ["precision", "ESP", "patience", "handiness"]}], 5)
    assert [s["name"] for s in got] == ["shape it", "cut", "x"]
    assert got[0] == {"name": "shape it", "minutes": 60, "guess": 60, "materials": {}, "abilities": ["handiness"]}
    assert got[1]["minutes"] == 240 and got[1]["materials"] == {"brass wire": 3} and got[2]["abilities"] == ["precision", "patience"]
    many = G["sanitize_stages"](c, [{"name": "a", "materials": {"x": 6}}, {"name": "b", "materials": {"y": 6}}], 5)
    assert many[0]["materials"] == {"x": 6} and many[1]["materials"] == {"y": 2}                     # 8 units in all
    assert G["sanitize_stages"](c, [{"name": str(i)} for i in range(9)], 5)[-1]["name"] == "4" and G["sanitize_stages"](c, "x", 5) == []


def test_the_narrators_review_tags_the_steps_and_holds_what_cant_be_known():
    c = ctx_of()
    steps = G["sanitize_stages"](c, PIP_STEPS, 5)
    plan = G["build_plan"](c, steps, {**REVIEW, "open_questions": ["will it keep time?"], "hidden": ["the spring is weak"], "tools": ["a", "b", "c", "d"],
                                       "difficulty": 9})
    assert plan["craft"] == "clockmaking" and plan["difficulty"] == 5 and plan["tools"] == ["a", "b", "c"]
    assert [s["name"] for s in plan["stages"]] == ["cut the wheels", "fit the escapement"] and plan["stages"][0]["abilities"] == ["precision"]
    assert plan["questions"] == ["will it keep time?"] and plan["hidden"] == [{"fact": "the spring is weak", "found": False}]
    assert G["build_plan"](c, steps, {**REVIEW, "hidden": ["x"]})["hidden"] == []                    # no question, nothing hidden
    plain = G["build_plan"](c, steps, None)
    assert (plain["craft"], plain["difficulty"], plain["tools"]) == ("tinkering", 2, [])
    assert G["craft_name"]("Clockmaking (gear train, escapement)") == "clockmaking" and G["craft_name"]("wood & metal-work") == "wood metal work"


async def test_starting_a_project_reviews_the_plan(tmp_path):
    s, st, gm, agent = world(tmp_path, [report(**REVIEW, open_questions=["will it keep time?"], hidden=["the spring is weak"], concerns="It's ambitious.")])
    r = await call(agent, "start_project", name="Clock", goal="a clock that ticks")
    assert r.text.startswith("started project #1 Clock (clockmaking, difficulty 3/5). Your plan: 1. cut the wheels (~60 min, needs 2 brass wire); "
                             "2. fit the escapement (~30 min). Helpful tools: needle file. A thought on your plan: It's ambitious. What you don't know yet: "
                             "will it keep time?")
    p = project(st)
    assert (p["name"], p["goal"], p["craft"], p["status"], p["hidden"]) == ("Clock", "a clock that ticks", "clockmaking", "active",
                                                                             [{"fact": "the spring is weak", "found": False}])
    task = gm.calls[0]["messages"][0]["content"]
    assert task.startswith("Pip wants to start a project: 'Clock'.") and "0. cut the wheels (Pip thinks ~60 min, using 2 brass wire)" in task
    assert store(st)["meta"]["all"]["next_id"] == 2 and "now" not in store(st) or not store(st)["now"].get("start")


async def test_what_stops_a_project_starting(tmp_path):
    s, st, gm, agent = world(tmp_path, [report(**REVIEW)] * 4, max_active_projects=2)
    assert (await call(agent, "start_project", name=" ", steps=THREE_STEPS)).text == "error: a project needs a name"
    assert (await call(agent, "start_project", name="Kite", steps=[])).text.startswith("error: sketch at least the first step")
    await call(agent, "start_project", name="Kite")
    assert (await call(agent, "start_project", name="kite")).text == "you're already working on 'kite'; use work_on"
    await call(agent, "start_project", name="Boat")
    assert (await call(agent, "start_project", name="Cart")).text == "you already have 2 projects going (Kite, Boat); finish or abandon_project one first"


# --- working on it ----------------------------------------------------------------------------------------------------------------------
async def test_a_stage_takes_its_materials_when_first_worked_and_says_what_is_missing(tmp_path):
    s, st, gm, agent = world(tmp_path, [report(**REVIEW)])
    await call(agent, "start_project", name="Clock")
    r = await call(agent, "work_on", project="clock")
    assert r.text == "can't start stage 1/2 'cut the wheels' (about 60 min of work; uses 2 brass wire) yet: it needs 2 brass wire (you have 0)"
    st.add_item("brass wire", 3, "material", "")
    st.add_item("wheels", 1, "material", "")                     # named in the stage: built in
    r = await call(agent, "work_on", project="#1", minutes=500, approach="file slowly", expect="well")
    assert r.text == ("you settle in to work on Clock, stage 1/2 'cut the wheels' (about 60 min of work), for 120 min. You'll hear "
                      "how it went in about 1 min. You used up your wheels on it.")
    assert st.find_item("brass wire")[0]["qty"] == 1 and st.find_item("wheels")[0] is None and project(st)["stages"][0]["started"]
    sess = st.session()
    assert (sess["kind"], sess["about"], sess["expect"], sess["stage"]) == ("module", "Clock", "working on Clock: cut the wheels", 1)
    assert store(st)["now"]["session"] == {"kind": "work", "project_id": 1, "stage": 0, "minutes": 120, "approach": "file slowly", "expect": "well"}
    assert st.agent()["activity"] == "working"
    assert (await call(agent, "work_on", project="Clock")).text == "you're already working on Clock"
    assert (await call(agent, "work_on", project="Kite")).text.startswith("error: no active project like 'Kite' (yours: #1 Clock)")


async def test_a_session_judged_and_told(tmp_path):
    s, st, gm, agent = world(tmp_path, [report(**REVIEW), report(verdict="breakthrough", text="The teeth come clean.", finding="Brass files easily.")])
    st.add_item("brass wire", 2, "material", "")
    await call(agent, "start_project", name="Clock")
    await call(agent, "work_on", project="Clock", minutes=60, approach="file each tooth gently", expect="badly")
    m = M.live_named(st, "crafting")
    now = moment_for("good", 0, 0, 3, pid=m["id"])
    await end(agent, now)
    p = project(st)
    assert p["stages"][0]["progress"] == 60 and p["history"][-1]["result"] == "breakthrough" and p["findings"] == ["Brass files easily."]
    (ev,) = events(st, "work")
    assert (ev["result"], ev["text"], ev["learned"], ev["finished_stage"], ev["by"], ev["craft"], ev["percent"]) == \
        ("breakthrough", "The teeth come clean.", "Brass files easily.", True, "crafting", "clockmaking", 66)
    assert ev["expected"] == "badly" and ev["surprise"] == "better" and st.expectations(5)[0]["event_id"]
    task = gm.calls[1]["messages"][0]["content"]
    assert "The die says this kind of effort goes well on average." in task and "'file each tooth gently'" in task
    assert store(st)["skills"]["clockmaking"] == 60 and st.abilities().get("precision", 0) >= 60 and st.agent()["activity"] == "idle"


def test_the_narrator_moves_the_die_one_step_at_most():
    cv = G["clamp_verdict"]
    assert cv("good", "blowup") == "slow" and cv("good", "breakthrough") == "breakthrough" and cv("setback", "blowup") == "blowup"
    assert cv("slow", "nonsense") == "slow" and cv("slow", "slow") == "slow"


async def test_a_blowup_loses_ground_a_material_and_some_energy(tmp_path):
    s, st, gm, agent = world(tmp_path, [report(**REVIEW), report(verdict="blowup", text="It snaps.")])
    st.add_item("brass wire", 5, "material", "")
    await call(agent, "start_project", name="Clock")
    await call(agent, "work_on", project="Clock", minutes=60, approach="hammer it")
    p = project(st)
    p["stages"][0]["progress"] = 30.0
    st.merge_store("crafting", {"projects": {"1": p}})
    energy = st.agent()["energy"]
    m = M.live_named(st, "crafting")
    await end(agent, moment_for("setback", 0, 0, 3, pid=m["id"]))
    assert project(st)["stages"][0]["progress"] == 15.0 and st.find_item("brass wire")[0]["qty"] == 2           # 3 taken: 2 to start, 1 lost
    assert st.agent()["energy"] == pytest.approx(energy - 0.1, abs=0.02) and events(st, "work")[0]["lost"] == ["brass wire"]


async def test_without_an_approach_the_narrator_only_tells_it(tmp_path):
    s, st, gm, agent = world(tmp_path, [report(**REVIEW), report(text="You make a start.")])
    await call(agent, "start_project", name="Kite")
    await call(agent, "work_on", project="Kite", minutes=30)
    m = M.live_named(st, "crafting")
    await end(agent, moment_for("slow", 0, 0, 3, pid=m["id"]))
    (ev,) = events(st, "work")
    assert ev["result"] == "slow" and ev["text"] == "You make a start." and project(st)["stages"][0]["progress"] == 15
    assert "The result (already decided, don't change it): slow" in gm.calls[1]["messages"][0]["content"]


async def test_resting_cuts_a_session_short_without_the_die(tmp_path):
    s, st, gm, agent = world(tmp_path, [report(**REVIEW)])
    await call(agent, "start_project", name="Kite")
    await call(agent, "work_on", project="Kite", minutes=60)
    r = await call(agent, "rest")
    assert "you stopped working on Kite: gather and shape the pieces early" in r.text
    (ev,) = events(st, "work")
    assert ev["interrupted"] and ev["result"] == "slow" and ev["text"].startswith("Work on gather and shape the pieces was slow") and len(gm.calls) == 1


async def test_finishing_the_last_stage_makes_the_thing(tmp_path):
    design = {"name": "Tick", "description": "a small brass clock", "capabilities": [{"type": "timekeeper"}], "quirks": ["it hums"]}
    s, st, gm, agent = world(tmp_path, [report(**REVIEW), report(text="Done."), report(**design)])
    await call(agent, "start_project", name="Clock", steps=[{"name": "fit the escapement", "minutes": 15}])
    await call(agent, "work_on", project="Clock", minutes=60)
    m = M.live_named(st, "crafting")
    await end(agent, moment_for("good", 0, 0, 3, pid=m["id"]))
    assert project(st)["status"] == "done" and events(st, "work")[0]["project_done"]
    (c,) = st.creations()
    assert (c["name"], c["description"], c["project_id"]) == ("Tick", "a small brass clock", 1) and set(c["spec"]["capabilities"]) == {"timekeeper"}
    assert events(st, "creation_made")[0]["project"] == "Clock" and "Pip just finished its project 'Clock'" in gm.calls[2]["messages"][0]["content"]
    assert "work_on" in agent.tool_names()


# --- discovery --------------------------------------------------------------------------------------------------------------------------
async def test_an_experiment_reveals_a_hidden_fact_and_answers_a_question(tmp_path):
    s, st, gm, agent = world(tmp_path, [report(**REVIEW, open_questions=["will it keep time?"], hidden=["the spring is weak"]),
                                       report(relevant=True, text="It runs slow.", finding="The spring is weak.", reveal=0, answers=0)])
    await call(agent, "start_project", name="Clock", steps=[{"name": "fit the escapement", "minutes": 15}])
    assert (await call(agent, "experiment", project="Clock", hypothesis="hmm")).text.startswith("error: say what you think")
    r = await call(agent, "experiment", project="Clock", hypothesis="a weak spring slows it down", expect="works")
    assert r.text.startswith("you set up an experiment on Clock (a weak spring slows it down) for 45 min.")
    m = M.live_named(st, "crafting")
    for t in range(int(NOW), int(NOW) + 5000):
        if G["roll_experiment"](random.Random(t * 7919 + m["id"]), 0, 3, False) == "insight":
            break
    await end(agent, float(t))
    p = project(st)
    assert p["hidden"][0]["found"] and p["questions"] == [] and p["findings"] == ["The spring is weak."] and p["dry"] == 0
    (ev,) = events(st, "experiment")
    assert (ev["outcome"], ev["answered"], ev["finding"], ev["relevant"]) == ("insight", "will it keep time?", "The spring is weak.", True)


def test_changes_from_what_was_found():
    p = {"stages": [{"name": "a", "minutes": 10, "progress": 10, "started": True}], "questions": ["q1"], "hidden": [{"fact": "f", "found": False}],
         "findings": [], "difficulty": 3, "status": "active"}
    out = G["apply_changes"](p, {"reveal": 5, "answers": 0, "difficulty_delta": 4}, reveal=True)
    assert out == {"finding": "f", "answered": "q1", "added": ["put it all together"]} and p["difficulty"] == 4
    assert p["stages"][-1]["name"] == "put it all together" and p["hidden"][0]["found"]
    q = {"stages": [], "questions": [], "hidden": [], "findings": [], "difficulty": 1, "status": "active"}
    G["apply_changes"](q, {"new_question": "why?", "difficulty_delta": -1}, reveal=False, new_question=True)
    assert q["questions"] == ["why?"] and q["difficulty"] == 1


async def test_revising_the_plan(tmp_path):
    s, st, gm, agent = world(tmp_path, [report(**REVIEW, open_questions=["will it keep time?"], hidden=["the spring is weak"]),
                                       report(text="Fine.", steps=[{"abilities": ["patience"], "minutes": 20}])])
    await call(agent, "start_project", name="Clock")
    assert (await call(agent, "revise_plan", project="Clock")).text == "error: give steps to add, steps to drop, or what you learned"
    r = await call(agent, "revise_plan", project="Clock", steps=[{"name": "oil it", "minutes": 30}], drop=["fit the escapement"])
    assert r.text == "Fine. added: oil it; dropped: fit the escapement"
    assert [s["name"] for s in project(st)["stages"]] == ["cut the wheels", "oil it"] and project(st)["stages"][1]["minutes"] == 20
    r = await call(agent, "revise_plan", project="Clock", because="a book said springs weaken")
    assert r.text == "(what you learned will count once you've worked or experimented again) the plan stays as it is"
    assert events(st, "plan_revised")[-1]["dropped"] == ["fit the escapement"]


async def test_abandoning_and_picking_back_up(tmp_path):
    s, st, gm, agent = world(tmp_path, [report(**REVIEW)])
    await call(agent, "start_project", name="Kite")
    assert (await call(agent, "resume_project", project="Kite")).text.startswith("error: no paused project like 'Kite'")
    assert (await call(agent, "abandon_project", project="Kite", reason="too windy")).text == "abandoned Kite"
    assert (project(st)["status"], project(st)["outcome"]) == ("abandoned", "too windy")
    assert (await call(agent, "abandon_project", project="Kite")).text == "error: Kite is already abandoned"


# --- what others ask, see and read --------------------------------------------------------------------------------------------------------
async def test_the_night_pass_and_a_world_effect_ask_the_module(tmp_path):
    s, st, gm, agent = world(tmp_path, [report(**REVIEW)])
    await call(agent, "start_project", name="Kite")
    assert await M.ask_module(st, s, None, "crafting", "pause", {"project": "#1"}, True) == "Put Kite on hold."
    assert project(st)["status"] == "paused"
    assert (await call(agent, "resume_project", project="kite")).text == "you pick Kite back up"
    assert await M.ask_module(st, s, None, "crafting", "add_slot", {}, True) == "You can keep 4 projects going at once now."
    assert store(st)["meta"]["all"]["extra_slots"] == 1 and M.published(st, "project_limit") == 4
    assert M.queue_request(st, "crafting", "pause", {"project": "#1"}) and not M.queue_request(st, "crafting", "fly", {})
    await M.step(st, s, None)
    assert project(st)["status"] == "paused"


async def test_what_the_agent_sees_and_the_dashboard_reads(tmp_path):
    s, st, gm, agent = world(tmp_path, [report(**REVIEW, open_questions=["will it keep time?"], hidden=["x"])])
    await call(agent, "start_project", name="Clock")
    st.log("module", text="found", moment="gathered")
    m = M.live_named(st, "crafting")
    lines = m["standing"]["lines"]
    assert m["standing"]["title"] == "Your projects"
    assert lines[0] == "#1 Clock (clockmaking, difficulty 3/5): 0% done, now on stage 1/2 'cut the wheels' (needs 2 brass wire; missing 2 brass wire (you have 0))"
    assert lines[1] == "you don't know yet: will it keep time?"
    said = M.published(st, "projects")
    assert said[0]["name"] == "Clock" and said[0]["percent"] == 0 and said[0]["current_stage"] == 0 and M.published(st, "skills") == {}


def test_a_finished_project_is_kept_small_and_the_oldest_let_go():
    p = {"id": 1, "status": "done", "history": [{"ts": i, "stage": "s", "result": "good", "minutes": 1, "text": "t", "extra": 1} for i in range(9)],
         "hidden": [{"fact": "f", "found": True}], "findings": ["a", "b", "c"], "stages": [{"name": "s", "materials": {"x": 1}}]}
    c = G["compact"](p)
    assert len(c["history"]) == 4 and "extra" not in c["history"][0] and c["hidden"] == [] and c["findings"] == ["b", "c"] and c["stages"][0]["materials"] == {}
    old = {str(i): {"id": i, "status": "done", "finished_at": i, "history": [], "stages": [], "hidden": [], "findings": []} for i in range(1, 33)}
    store = G["prune"](ctx_of({"projects": old}), {})
    assert sorted(int(k) for k, v in store["projects"].items() if v is None) == [1, 2]


def test_mentioned_materials_are_those_the_stage_names_but_does_not_list():
    items = [{"name": "pendulum", "qty": 1, "kind": "material"}, {"name": "brass wire", "qty": 2, "kind": "material"},
             {"name": "pendulum bob", "qty": 1, "kind": "tool"}]                    # a tool is never used up
    ctx = ctx_of(items=items)

    def named(name="build the escapement and pendulum", **kw):
        return [i["name"] for i in G["mentioned_materials"](ctx, {"name": name, "minutes": 60, "materials": {}, **kw})]
    assert named(materials={"brass wire": 1}) == ["pendulum"]                      # wire is already listed; the tool is kept
    assert named("polish the case") == []
    assert named("hang the Pendulums") == ["pendulum"]
    assert named("a pendulumless design") == []                                    # whole words only


def test_the_design_task_lets_the_narrator_name_an_ability():
    from app import creations as cr
    making = {"capabilities": cr.menu(False), "companion": cr.menu(True)[-1], "companion_from": 4}
    p = {"name": "radio", "craft": "wireless", "goal": "hear the world", "difficulty": 4, "history": [{"stage": "wind", "text": "wound it."}]}
    task = G["design_task"](ctx_of(making=making), p, "sound", [])
    props = task["args"]["schema"]["properties"]
    assert task["args"]["schema"]["required"] == ["description"]
    assert props["capabilities"]["items"]["required"] == ["type"] and props["more"]["items"]["required"] == ["type"]
    more = props["more"]["items"]["properties"]
    assert more["ability"] == {"type": "string"} and more["persona"] == {"type": "string"} and more["chatter_minutes"] == {"type": "number"}
    assert more["finds"]["items"] == {"type": "string"} and props["capabilities"]["items"]["properties"]["hours"] == {"type": "number"}
    text = task["args"]["prompt"]
    assert "provides: ONLY if what Pip finished" in text and "garden_plot" in text and "companion: it has a mind" in text
    assert "- wind: wound it." in text and "Finished quality: sound." in text
    p["difficulty"] = 3
    assert "companion: it has a mind" not in G["design_task"](ctx_of(making=making), p, "sound", [])["args"]["prompt"]


def test_describe_stage_summarises_a_step():
    p = {"stages": [{"name": "cut", "minutes": 45, "materials": {"brass wire": 2, "glue": 1}, "started": False},
                    {"name": "fit", "minutes": 30, "materials": {}, "started": False},
                    {"name": "paint", "minutes": 20, "materials": {"paint": 1}, "started": True}]}
    assert G["describe_stage"](p, 0) == "stage 1/3 'cut' (about 45 min of work; uses 2 brass wire, 1 glue)"
    assert G["describe_stage"](p, 1) == "stage 2/3 'fit' (about 30 min of work)"
    assert G["describe_stage"](p, 2) == "stage 3/3 'paint' (about 20 min of work)"            # already paid for


# --- an install from before 0.42.0 ------------------------------------------------------------------------------------------------------
async def test_an_old_installs_projects_crafts_and_space_move_into_the_module(tmp_path):
    import json
    from app import projects as proj
    from app.state import State
    s, st, gm, agent = make(tmp_path)
    stage = {"name": "cut the wheels", "minutes": 60, "guess": 45, "progress": 30.0, "started": True, "materials": {"brass wire": 2}, "abilities": ["precision"]}
    history = [{"ts": 10.0 + i, "stage": "cut the wheels", "result": "good", "minutes": 15, "text": f"session {i}", "kind": "work",
                "interrupted": False, "extra": "dropped when finished"} for i in range(6)]
    for name, status, craft in (("gear clock", "active", "Clockmaking (gear train)"), ("old kite", "done", "wood & metal-work")):
        st.db.execute("INSERT INTO projects (name, goal, craft, difficulty, stages, tools, history, status, outcome, ts, finished_at, questions, hidden, "
                      "findings, dry, revised_at) VALUES (?, 'a goal', ?, 3, ?, '[\"tweezers\"]', ?, ?, '', 5.0, ?, '[\"will it run?\"]', ?, ?, 1, 7.0)",
                      (name, craft, json.dumps([stage]), json.dumps(history), status, 99.0 if status == "done" else None,
                       json.dumps([{"fact": "the spring is weak", "found": False}]), json.dumps(["f1", "f2", "f3"])))
    st.db.execute("INSERT INTO skills VALUES ('clockmaking', 100), ('Clockmaking (escapement)', 20), ('wood & metal-work', 5)")
    st.set_meta(extra_project_slots="2")
    st.db.commit()
    st = State(s)                                                                    # the next start: the move, once
    got = store(st)
    live, done = got["projects"]["1"], got["projects"]["2"]
    assert (live["name"], live["craft"], live["stages"], live["tools"], live["questions"], live["dry"], live["revised_at"], live["finished_at"]) == \
        ("gear clock", "clockmaking", [stage], ["tweezers"], ["will it run?"], 1, 7.0, None)
    assert live == {"id": 1, "name": "gear clock", "goal": "a goal", "craft": "clockmaking", "difficulty": 3, "stages": [stage], "tools": ["tweezers"],
                    "history": history, "status": "active", "outcome": "", "ts": 5.0, "finished_at": None, "questions": ["will it run?"],
                    "hidden": [{"fact": "the spring is weak", "found": False}], "findings": ["f1", "f2", "f3"], "dry": 1, "revised_at": 7.0}
    assert (done["craft"], done["status"], done["finished_at"], done["hidden"], done["findings"]) == ("wood metal work", "done", 99.0, [], ["f2", "f3"])
    assert done["history"] == [{k: v for k, v in h.items() if k != "extra"} for h in history[-4:]] and done["stages"] == [{**stage, "materials": {}}]
    assert got["skills"] == {"clockmaking": 120, "wood metal work": 5} and got["meta"] == {"all": {"next_id": 3, "extra_slots": 2}}
    assert st.db.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0 and st.db.execute("SELECT COUNT(*) FROM skills").fetchone()[0] == 0
    assert st.meta("extra_project_slots") is None
    assert st.capability_context() == ({1: "clockmaking", 2: "wood metal work"}, {(1, "cut the wheels"): ["precision"], (2, "cut the wheels"): ["precision"]})
    st.merge_store("crafting", {"skills": {"clockmaking": 1}})
    st = State(s)                                                                    # once: a later start leaves the store alone
    assert store(st)["skills"]["clockmaking"] == 1
    crafting(st)
    await M.call(st, s, M.LocalRunner(), M.live_named(st, "crafting"), "on_install", NOW)
    said = proj.published(st)
    assert [(p["name"], p["status"], p["percent"]) for p in said["projects"]] == [("gear clock", "active", 50), ("old kite", "done", 50)]
    assert said["skills"]["clockmaking"] == {"xp": 1, "level": 0} and M.published(st, "project_limit") == 5


async def test_a_fresh_install_has_nothing_to_move(tmp_path):
    s, st, gm, agent = make(tmp_path)
    assert store(st) == {}
    st.merge_store("crafting", {"skills": {"x": 1}})
    from app.state import State
    State(s)
    assert store(st) == {"skills": {"x": 1}}


def old_rows(st, *rows, skills=(), slots=0):
    """An install from before 0.42.0: (name, status) projects in the old table, crafts' experience, extra workshop space."""
    import json
    for name, status in rows:
        st.db.execute("INSERT INTO projects (name, craft, difficulty, stages, history, status, ts, findings) VALUES (?, 'kites', 1, ?, ?, ?, 1.0, ?)",
                      (name, json.dumps([{"name": "cut", "minutes": 30, "materials": {"silk": 1}}]),
                       json.dumps([{"ts": 1.0, "stage": "cut", "text": "x", "extra": 1}]), status, json.dumps(["a", "b", "c"])))
    st.db.executemany("INSERT INTO skills VALUES (?, ?)", skills)
    if slots:
        st.set_meta(extra_project_slots=str(slots))
    st.db.commit()


def test_an_abandoned_project_is_kept_small_too_and_space_alone_moves(tmp_path):
    from app.state import State
    s, st, gm, agent = make(tmp_path)
    old_rows(st, ("kite", "abandoned"))
    p = store(State(s))["projects"]["1"]
    assert (p["history"], p["findings"], p["stages"][0]["materials"]) == ([{"ts": 1.0, "stage": "cut", "result": None, "minutes": None, "text": "x",
                                                                          "kind": None, "interrupted": None}], ["b", "c"], {})
    (tmp_path / "b").mkdir()
    s, st, gm, agent = make(tmp_path / "b")
    old_rows(st, slots=1)
    assert store(State(s)) == {"meta": {"all": {"next_id": 1, "extra_slots": 1}}}             # empty collections aren't kept
    (tmp_path / "c").mkdir()
    s, st, gm, agent = make(tmp_path / "c")
    old_rows(st, skills=[("kites", 30.0)])
    assert store(State(s))["skills"] == {"kites": 30.0}


def test_a_store_already_there_is_kept_and_the_old_tables_still_emptied(tmp_path):
    from app.state import State
    s, st, gm, agent = make(tmp_path)
    st.merge_store("crafting", {"skills": {"kites": 1}})
    old_rows(st, ("kite", "active"), skills=[("kites", 30.0)], slots=2)
    st = State(s)
    assert store(st) == {"skills": {"kites": 1}} and st.meta("extra_project_slots") is None
    assert st.db.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0 and st.db.execute("SELECT COUNT(*) FROM skills").fetchone()[0] == 0


def test_the_engine_names_a_craft_as_the_module_keys_it():
    from app.text import craft_name
    cases = {"Clockmaking (gear train, escapement)": "clockmaking", "wood & metal-work": "wood metal work", "  Glass.  ": "glass",
             "kite making and": "kite making", "rope or": "rope", "art of": "art", "work with": "work", "into the": "into",
             "made for": "made", "one two three four": "one two three", "a.b": "a b", "": "tinkering", "&": "tinkering",
             "Bread-baking: sourdough": "bread baking", "x" * 40: "x" * 30, "café work": "caf work", ". dots .": "dots", "and": "tinkering"}
    for raw, want in cases.items():
        assert craft_name(raw) == want == G["craft_name"](raw), raw


def test_what_crafting_reads_where_things_were_found_and_what_a_made_thing_can_do(tmp_path):
    from app import creations as cr
    s, st, gm, agent = world(tmp_path)
    st.add_find("junkyard", "brass wire", 10.0)
    st.add_find("woods", "pine cones", 20.0)
    st.add_find("woods", "pine cones", 30.0)
    st.add_find("library", "old maps", 40.0)
    ctx = M.context(st, s, M.live_named(st, "crafting"), NOW)
    assert ctx["found"] == [{"item": "pine cones", "place": "woods", "label": "the woods"},                # most often, then most lately
                            {"item": "old maps", "place": "library", "label": "the library"},
                            {"item": "brass wire", "place": "junkyard", "label": "the junkyard"}]
    assert ctx["making"] == {"capabilities": cr.menu(False), "companion": cr.menu(True)[-1], "companion_from": cr.COMPANION_MIN_DIFFICULTY,
                             "qualities": ["rough", "sound", "fine", "masterwork"]}
    assert ctx["making"]["companion"].startswith("companion:") and not any(c.startswith("companion:") for c in ctx["making"]["capabilities"])
    assert ctx["agent"]["tiring"] == "energy" and ctx["agent"]["tired"] is False


def test_a_request_waits_with_who_asked_and_only_the_last_ten_are_kept(tmp_path):
    s, st, gm, agent = world(tmp_path)
    for i in range(12):
        assert M.queue_request(st, "crafting", "pause", {"project": f"#{i}"}, by="night pass")
    asked = M.live_named(st, "crafting")["requests"]
    assert [r["args"]["project"] for r in asked] == [f"#{i}" for i in range(2, 12)]
    assert set(asked[0]) == {"what", "args", "from", "ts"} and asked[0]["from"] == "night pass" and asked[0]["ts"] == pytest.approx(time.time(), abs=5)
    assert M.queue_request(st, "crafting", "resume", {}) and M.live_named(st, "crafting")["requests"][-1]["from"] == "engine"
    assert not M.queue_request(st, "nobody", "pause", {})


def test_a_status_line_may_be_long_enough_for_a_project(tmp_path):
    line = "x" * M.STATUS_LINE_MAX
    assert M._status({"title": "T", "lines": [line]})["lines"] == [line]
    with pytest.raises(M.Refused):
        M._status({"title": "T", "lines": [line + "x"]})


def test_the_engine_reads_only_well_shaped_projects_and_skills(tmp_path):
    from app import projects as proj
    s, st, gm, agent = make(tmp_path)
    assert proj.published(st) == {"projects": [], "skills": {}}
    m = crafting(st)
    st.update_module(m["id"], facts={"projects": {"a": 1}, "skills": ["x"]})
    assert proj.published(st) == {"projects": [], "skills": {}}
    st.update_module(m["id"], facts={"projects": [{"id": 1}], "skills": {"kites": {"xp": 1, "level": 0}}})
    assert proj.published(st) == {"projects": [{"id": 1}], "skills": {"kites": {"xp": 1, "level": 0}}}
