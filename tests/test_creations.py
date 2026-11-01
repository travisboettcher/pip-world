import random
import time

import pytest

from app import creations as cr
from app import tools as tools_mod
from app.llm.base import LLMResponse
from tests.test_projects import FixedRng, call, make, report

DAY = 86400


def project(difficulty=3, name="hourglass"):
    return {"id": 1, "name": name, "goal": "", "craft": "glasswork", "difficulty": difficulty, "history": []}


def build(st, raw, quality="sound", difficulty=3, scars=(), rng=None, now=None, name="hourglass"):
    p = project(difficulty, name)
    name, desc, spec = cr.sanitize_spec(raw, p, quality, list(scars), rng or FixedRng())
    return st.add_creation(name, desc, 1, quality, spec, cr.initial_runtime(spec, now or time.time()))


def test_sanitize_spec_keeps_the_primitives_and_engine_owns_numbers():
    raw = {"name": "Sandy", "description": "a glass hourglass", "quirks": ["hums"], "capabilities": [
        {"type": "timekeeper", "drift_per_day": 0},                    # GM can't pick accuracy
        {"type": "upkeep", "verb": "Turn over.", "hours": 500},
        {"type": "laser"},                                             # not a primitive
        {"type": "sensor", "condition": "earthquake", "alert": "x"},   # bad param: dropped
        {"type": "periodic", "lines": ["Sand whispers.", ""], "every_minutes": 1},
        {"type": "helper", "effect": "comfort", "line": "x"},          # over the cap of 3
    ]}
    name, desc, spec = cr.sanitize_spec(raw, project(), "rough", [], FixedRng())
    caps = spec["capabilities"]
    assert (name, desc) == ("Sandy", "a glass hourglass") and list(caps) == ["timekeeper", "upkeep", "periodic"]
    assert abs(caps["timekeeper"]["drift_per_day"]) == 15  # rough work drifts
    assert caps["upkeep"] == {"verb": "turn over", "hours": 36}  # clamped to 72, halved for rough work
    assert caps["periodic"] == {"lines": ["Sand whispers."], "every_minutes": 20}


def test_helper_needs_an_effect_a_line_and_for_find_some_finds():
    def helper(**h):
        return cr.sanitize_spec({"description": "x", "capabilities": [{"type": "helper", **h}]},
                                project(), "sound", [], FixedRng())[2]["capabilities"]
    assert helper(effect="find", line="It combs the shore.") == {}  # nothing to find
    assert helper(effect="dig_for_gold", line="x") == {}
    assert helper(effect="find", line="It combs the shore.", finds=["Sea Glass", "shell"])["helper"] == {
        "effect": "find", "line": "It combs the shore.", "every_minutes": 720, "finds": ["sea glass", "shell"]}


def test_companion_needs_difficulty_and_scars_become_quirks():
    raw = {"description": "a puppet", "capabilities": [{"type": "companion", "persona": "A shy puppet."}]}
    assert cr.sanitize_spec(raw, project(2), "fine", [], FixedRng())[2]["capabilities"] == {}
    _, _, spec = cr.sanitize_spec(raw, project(3), "fine", ["You tore a seam."], FixedRng())
    assert "companion" in spec["capabilities"] and spec["quirks"] == ["You tore a seam."]
    name, desc, spec = cr.sanitize_spec(None, project(), "sound", [], FixedRng())  # GM failed: it simply exists
    assert name == "hourglass" and spec["capabilities"] == {}


def test_art_has_no_behaviour_and_no_running_state(tmp_path):
    s, st, *_ = make(tmp_path)
    c = build(st, {"name": "Rain Poem", "description": "eight lines about rain on the garden",
                   "quirks": ["the last line doesn't quite rhyme"], "capabilities": []})
    assert cr.describe(c) == ("- Rain Poem (sound): eight lines about rain on the garden - "
                              "the last line doesn't quite rhyme")
    assert cr.tick(st, FixedRng(), time.time() + 99 * DAY) is False  # nothing ever happens to it
    assert [e for e in st.events(5) if e["kind"] == "creation"] == []


def test_timekeeper_drifts_stops_without_upkeep_and_restarts_behind(tmp_path):
    s, st, *_ = make(tmp_path)
    t0 = 1_700_000_000.0
    c = build(st, {"description": "x", "capabilities": [{"type": "timekeeper"},
                                                        {"type": "upkeep", "verb": "turn", "hours": 48}]}, now=t0)
    drift = c["spec"]["capabilities"]["timekeeper"]["drift_per_day"]
    assert abs(drift) == 5 and cr.clock_reading(c, t0 + DAY)[1] == pytest.approx(drift)
    assert cr.running(c, t0 + DAY) and not cr.running(c, t0 + 3 * DAY)
    stopped_face = cr.clock_face(c, t0 + 2 * DAY)
    assert cr.clock_face(c, t0 + 3 * DAY) == stopped_face  # frozen at the time it stopped
    assert "STOPPED - it needs tending (turn)" in cr.describe(c, t0 + 3 * DAY)
    assert cr.tend(st, c, t0 + 3 * DAY) == "you tend your hourglass (turn); it will keep going for about 48 hours"
    c = st.creation(c["id"])
    assert cr.running(c, t0 + 3 * DAY)
    assert cr.clock_reading(c, t0 + 3 * DAY)[1] == pytest.approx(-DAY / 60 + 2 * drift)  # a day behind


def test_tick_runs_periodic_sensor_helper_and_stop(tmp_path):
    s, st, *_ = make(tmp_path)
    now = time.time()
    build(st, {"description": "a tin crab", "capabilities": [
        {"type": "periodic", "lines": ["It clacks its claws."], "every_minutes": 30},
        {"type": "sensor", "condition": "visitor", "alert": "It scuttles to the door."},
        {"type": "helper", "effect": "find", "line": "It scuttles home from the shore.", "finds": ["sea glass"],
         "every_minutes": 360}]}, now=now, name="crab")
    assert cr.tick(st, FixedRng(), now + 60) is False  # nothing due yet
    st.add_inbox("hi")
    assert cr.tick(st, FixedRng(), now + 31 * 60) is True  # sensor wakes Pip
    assert cr.tick(st, FixedRng(), now + 32 * 60) is False  # edge-triggered: once
    texts = [e["data"]["text"] for e in st.events(10) if e["kind"] == "creation"]
    assert texts == ["It scuttles to the door.", "It clacks its claws."]
    cr.tick(st, random.Random(1), now + 361 * 60)
    found = st.events(1)[0]["data"]
    assert found["text"] == "It scuttles home from the shore. (found: sea glass)"
    assert st.find_item("sea glass")[0]["kind"] == "material"
    build(st, {"description": "a fern", "capabilities": [{"type": "upkeep", "verb": "water", "hours": 4}]},
          now=now, name="fern")
    assert cr.tick(st, FixedRng(), now + 5 * 3600) is True
    assert st.events(1)[0]["data"]["text"] == "Your fern has stopped - it needs tending (water)."
    assert cr.tick(st, FixedRng(), now + 6 * 3600) is False  # stop reported once


def test_hurry_crops_and_comfort(tmp_path):
    s, st, *_ = make(tmp_path)
    st.plant(1, "tomato seeds", "tomatoes", 60, 3, 0.5)
    now = time.time()
    before = st.garden(now)[0]["ready_at"]
    build(st, {"description": "a scarecrow", "capabilities": [
        {"type": "helper", "effect": "hurry_crops", "line": "It keeps the birds off.", "every_minutes": 60}]},
        now=now - 3600, name="scarecrow")
    build(st, {"description": "a quilt", "capabilities": [
        {"type": "helper", "effect": "comfort", "line": "The quilt is warm on your shoulders.", "every_minutes": 240}]},
        now=now - 5 * 3600, name="quilt")
    energy = st.agent()["energy"]
    cr.tick(st, FixedRng(), now)
    assert st.garden(now)[0]["ready_at"] == pytest.approx(before - 0.1 * (before - now))
    assert st.agent()["energy"] == pytest.approx(energy + 0.05)
    assert {e["data"]["text"] for e in st.events(2)} == {"It keeps the birds off.", "The quilt is warm on your shoulders."}


@pytest.mark.asyncio
async def test_finished_project_is_designed_into_a_creation(tmp_path):
    design = report(name="Sandy", description="a small glass hourglass", quirks=["the sand sticks a little"],
                    capabilities=[{"type": "timekeeper"}, {"type": "upkeep", "verb": "turn", "hours": 24}])
    s, st, gm, agent = make(tmp_path, [LLMResponse("..."), *[report(text="Work.")] * 3, design],
                            rng=FixedRng(0.6), work_speed=1e6)
    await call(agent, "start_project", name="hourglass", steps=[  # the GM review fails -> Pip's steps stand
        {"name": "blow the glass", "minutes": 45}, {"name": "fill it", "minutes": 60}, {"name": "seal it", "minutes": 45}])
    for _ in range(3):
        await call(agent, "work_on", project="hourglass", minutes=60)
        time.sleep(0.01)
        await agent.resolve_world()
    (c,) = st.creations()
    assert c["name"] == "Sandy" and c["quality"] == "sound" and list(c["spec"]["capabilities"]) == ["timekeeper", "upkeep"]
    assert "Finished quality: sound" in gm.calls[-1]["messages"][0]["content"]
    p = agent._perception("event", [])
    assert "Things you've made:" in p and "- Sandy (sound): a small glass hourglass - going; needs tending (turn)" in p
    assert "it shows" in p and "quirks: the sand sticks a little" in p
    assert "Your hourglass became Sandy: a small glass hourglass" in p  # a diary moment


@pytest.mark.asyncio
async def test_tend_and_use_tools(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="You set it right.", set_clock=True, mood="pleased", energy=0.5)])
    c = build(st, {"description": "x", "capabilities": [{"type": "timekeeper"},
                                                        {"type": "upkeep", "verb": "turn", "hours": 4}]},
              now=time.time() - 2 * DAY)
    r = await call(agent, "use_item", item="hourglass", purpose="set it")
    assert r.text == "your hourglass has stopped - it needs tending (turn) first" and gm.calls == []
    assert "you tend your hourglass (turn)" in (await call(agent, "tend", creation="glass")).text
    r = await call(agent, "use_item", item="hourglass", purpose="set it to the right time")
    assert r.text == ("You set it right. (it now shows the right time; it keeps going for about 4 more hours; "
                      "use the tend tool to keep it going)")
    assert cr.clock_reading(st.creation(c["id"]), time.time())[1] == pytest.approx(0, abs=0.1)
    a = st.agent()
    assert a["mood"] == "pleased" and a["energy"] == pytest.approx(0.9 + 0.1)  # energy effect capped at 0.1
    build(st, {"description": "a poem", "capabilities": []}, name="poem")
    assert "doesn't need tending" in (await call(agent, "tend", creation="poem")).text


@pytest.mark.asyncio
async def test_using_a_running_tended_thing_says_that_tending_not_using_keeps_it_going(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="You wind the key.")])
    build(st, {"description": "x", "capabilities": [{"type": "upkeep", "verb": "wound", "hours": 12}]},
          now=time.time(), name="clock")
    r = await call(agent, "use_item", item="clock", purpose="wind it")
    assert r.text.startswith("You wind the key.") and "use the tend tool" in r.text and "about 12 more hours" in r.text


@pytest.mark.asyncio
async def test_use_can_stop_only_tended_things(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="It sputters out.", stop=True), report(text="Hm.", stop=True)])
    build(st, {"description": "x", "capabilities": [{"type": "upkeep", "verb": "oil", "hours": 10}]}, name="lantern")
    r = await call(agent, "use_item", item="lantern", purpose="shake it")
    assert "it has stopped until you tend it (oil)" in r.text and not cr.running(st.creations()[0], time.time())
    assert "keeps going" not in r.text           # a halted thing isn't "going for 10 more hours"
    assert "needs tending (oil)" in (await call(agent, "use_item", item="lantern", purpose="x")).text
    build(st, {"description": "a painting", "capabilities": []}, name="painting")
    r = await call(agent, "use_item", item="painting", purpose="admire it")
    assert r.text == "Hm." and cr.running(st.creations()[1], time.time())  # art can't be "stopped"


# --- world effects: a finished land-clearing project adds a garden plot -----------------------------------
def _project(name="Clear a new bed", goal="make room for another vegetable plot", difficulty=3, stages=("dig out the roots",)):
    return {"id": 1, "name": name, "goal": goal, "craft": "gardening", "difficulty": difficulty,
            "stages": [{"name": n} for n in stages], "history": []}


def test_the_world_capability_needs_a_land_project_and_enough_difficulty():
    import random
    from app import creations as C
    world = {"capabilities": [{"type": "world", "effect": "garden_plot"}]}
    rng = random.Random(1)
    ok = C.sanitize_spec(world, _project(), "sound", [], rng)[2]["capabilities"]
    assert ok == {"world": {"effect": "garden_plot"}}
    for p in (_project(name="Paint a portrait", goal="a picture of Morgan", stages=("sketch",)),   # nothing to do with ground
              _project(difficulty=1)):                                                            # too trivial to change the world
        assert C.sanitize_spec(world, p, "sound", [], rng)[2]["capabilities"] == {}
    assert C.sanitize_spec({"capabilities": [{"type": "world", "effect": "moon_base"}]}, _project(), "sound", [], rng)[2]["capabilities"] == {}


@pytest.mark.asyncio
async def test_finishing_a_bed_adds_a_plot_up_to_the_cap(tmp_path):
    s, st, gm, agent = make(tmp_path, [], garden_plots=3, garden_plots_max=4)
    assert len(st.garden()) == 3
    from app import creations as C
    for expected in (4, 4):  # the second would exceed the cap: no plot, and the creation doesn't claim one
        p = st.add_project("Clear a new bed", "more room to plant", "gardening", 3,
                           [{"name": "dig out the roots", "minutes": 60, "materials": {}, "progress": 60, "started": True}], [])
        gm.script[:] = [report(name="New bed", description="a freshly turned bed", quirks=[],
                               capabilities=[{"type": "world", "effect": "garden_plot"}])]
        c = await C.make(st, agent.gm, agent.rng, p, 0)
        assert len(st.garden()) == expected
    assert "world" not in c["spec"]["capabilities"]
    events = [e for e in st.events(20) if e["kind"] == "world_changed"]
    assert len(events) == 1 and "4 plots" in events[0]["data"]["text"]
    assert events[0]["data"]["firsts"][0]["label"] == "the first time you changed the world around you"
    assert [g["plot"] for g in st.garden()] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_a_new_plot_can_be_planted_and_shows_in_the_garden(tmp_path):
    s, st, gm, agent = make(tmp_path, garden_plots=1, garden_plots_max=3)
    agent.tools.update({n: tools_mod.REGISTRY[n] for n in ("plant",)})
    assert "plots are numbered 1-1" in (await call(agent, "plant", seed="carrot seeds", plot=2)).text
    st.add_plot()
    assert "planted" in (await call(agent, "plant", seed="carrot seeds", plot=2)).text.lower()
    assert [g["state"] for g in st.garden()] == ["empty", "growing"]
    assert st.meta("extra_plots") == "1"


# --- the world-effect registry is generic: a new kind of change is one entry ------------------------------
@pytest.mark.asyncio
async def test_a_workbench_raises_the_number_of_projects_pip_can_keep_going(tmp_path):
    from app import creations as C
    s, st, gm, agent = make(tmp_path, [], max_active_projects=1, max_active_projects_cap=2)
    agent.tools.update({n: tools_mod.REGISTRY[n] for n in ("start_project",)})
    st.add_project("kite", "g", "kitemaking", 2, [], [])
    steps = [{"name": "first step"}]
    assert "projects going" in (await call(agent, "start_project", name="boat", steps=steps)).text         # at the limit of 1
    p = st.add_project("Build a proper workbench", "a bench and shelves so I can keep more going", "carpentry", 3,
                       [{"name": "frame the bench", "minutes": 60, "materials": {}, "progress": 60, "started": True}], [])
    gm.script[:] = [report(name="Workbench", description="a sturdy bench with shelves", quirks=[],
                           capabilities=[{"type": "world", "effect": "workbench"}])]
    st.update_project(p["id"], status="done")                                                              # a finished project
    c = await C.make(st, agent.gm, agent.rng, p, 0)
    assert c["spec"]["capabilities"] == {"world": {"effect": "workbench"}} and st.project_limit() == 2
    assert "started project" in (await call(agent, "start_project", name="boat", steps=steps)).text         # room for a second
    ev = [e for e in st.events(20) if e["kind"] == "world_changed"][0]["data"]
    assert ev["effect"] == "workbench" and "2 projects going at once" in ev["text"]
    p2 = st.add_project("Another bench", "more shelves for the bench", "carpentry", 3,
                        [{"name": "more shelves", "minutes": 60, "materials": {}, "progress": 60, "started": True}], [])
    gm.script[:] = [report(name="Shelves", description="more shelves", quirks=[], capabilities=[{"type": "world", "effect": "workbench"}])]
    c2 = await C.make(st, agent.gm, agent.rng, p2, 0)
    assert st.project_limit() == 2 and "world" not in c2["spec"]["capabilities"]                          # capped: no claim, no change


def test_the_registry_drives_the_gm_prompt_and_the_checks():
    from app import world_effects as W
    line = W.gm_lines()
    assert "garden_plot" in line and "workbench" in line and "a pond, a painting or a gift is just itself" in line
    bench = {"name": "Make a workbench", "goal": "", "difficulty": 2, "stages": [{"name": "saw the boards"}]}
    assert W.allowed("workbench", bench) and not W.allowed("garden_plot", bench) and not W.allowed("moon_base", bench)
    assert not W.allowed("workbench", {**bench, "difficulty": 1})
    spec = {"capabilities": {"world": {"effect": "moon_base"}}}
    assert W.apply(None, spec) is None and "world" not in spec["capabilities"]                              # unknown effects do nothing


def test_a_small_drift_is_not_worth_a_clock_reset(tmp_path):
    s, st, *_ = make(tmp_path)
    t0 = 1_700_000_000.0
    c = build(st, {"description": "x", "capabilities": [{"type": "timekeeper"}]}, now=t0)
    for offset, said in ((0.5, "about right"), (4.9, "about right"), (-4.9, "about right"),
                         (5, "about 5 min fast"), (-6, "about 6 min slow")):
        st.set_runtime(c["id"], {**c["runtime"], "clock_offset": offset})
        d = cr.describe(st.creation(c["id"]), t0)
        assert f"(it runs {said}; use_item can set it)" in d, (offset, d)


@pytest.mark.asyncio
async def test_using_a_thing_the_way_it_is_tended_tends_it_for_real(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="You wind it up.", tend=True), report(text="You admire it."),
                                       report(text="You wind it, then it sputters.", tend=True, stop=True)])
    t0 = time.time()
    c = build(st, {"description": "x", "capabilities": [{"type": "upkeep", "verb": "wound", "hours": 12}]}, name="clock", now=t0 - 8 * 3600)
    assert st.creation(c["id"])["runtime"]["tended_until"] == pytest.approx(t0 + 4 * 3600, abs=5)       # 4 hours left
    r = await call(agent, "use_item", item="clock", purpose="wind it")
    assert r.text == "You wind it up. (wound: it will keep going for about 12 hours)"
    assert st.creation(c["id"])["runtime"]["tended_until"] == pytest.approx(time.time() + 12 * 3600, abs=5)
    assert "`tend`" in gm.calls[0]["messages"][0]["content"] and '"wound"' in gm.calls[0]["messages"][0]["content"]
    r = await call(agent, "use_item", item="clock", purpose="look at it")                              # not tended: the old note
    assert r.text == "You admire it. (it keeps going for about 12 more hours; use the tend tool to keep it going)"
    r = await call(agent, "use_item", item="clock", purpose="wind it again")                            # stopped in the same breath
    assert "it has stopped until you tend it (wound)" in r.text and "wound: it will keep going" not in r.text
    assert not cr.running(st.creation(c["id"]), time.time())


@pytest.mark.asyncio
async def test_only_a_tended_thing_can_be_tended_by_using_it(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="You polish it.", tend=True)])
    build(st, {"description": "a painting", "capabilities": []}, name="painting")
    r = await call(agent, "use_item", item="painting", purpose="polish")
    assert r.text == "You polish it." and "`tend`" not in gm.calls[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_without_a_game_master_using_a_thing_is_just_a_moment_spent_and_changes_nothing(tmp_path):
    s, st, *_ = make(tmp_path)
    t0 = time.time()
    c = build(st, {"description": "x", "capabilities": [{"type": "upkeep", "verb": "wound", "hours": 12}]}, name="clock", now=t0)
    before = st.creation(c["id"])["runtime"]["tended_until"]
    assert await cr.use(st, None, c, "wind it") == "you spend a moment with your clock (wind it)."
    assert st.creation(c["id"])["runtime"]["tended_until"] == before
