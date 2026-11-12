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
    st.set_runtime(c["id"], {**c["runtime"], "halted_at": t0 + DAY})
    assert cr.clock_face(st.creation(c["id"]), t0 + 3 * DAY) == cr.clock_face(st.creation(c["id"]), t0 + DAY)   # halted: frozen too


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
    from tests.test_garden import garden
    s, st, gm, agent = make(tmp_path, [])
    garden(st, plots=3, plots_max=4)
    from app import creations as C
    for expected in (1, 1):  # the second would exceed the cap: no plot, and the creation doesn't claim one
        p = st.add_project("Clear a new bed", "more room to plant", "gardening", 3,
                           [{"name": "dig out the roots", "minutes": 60, "materials": {}, "progress": 60, "started": True}], [])
        gm.script[:] = [report(name="New bed", description="a freshly turned bed", quirks=[],
                               capabilities=[{"type": "world", "effect": "garden_plot"}])]
        c = await C.make(st, agent.gm, agent.rng, p, 0)
        assert st.store("garden")["meta"] == {"extra_plots": expected}
    assert "world" not in c["spec"]["capabilities"]
    events = [e for e in st.events(20) if e["kind"] == "world_changed"]
    assert len(events) == 1 and "4 plots" in events[0]["data"]["text"]
    assert events[0]["data"]["firsts"][0]["label"] == "the first time you changed the world around you"


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


async def test_the_registry_drives_the_gm_prompt_and_the_checks():
    from app import world_effects as W
    line = W.gm_lines()
    assert "garden_plot" in line and "workbench" in line and "a pond, a painting or a gift is just itself" in line
    bench = {"name": "Make a workbench", "goal": "", "difficulty": 2, "stages": [{"name": "saw the boards"}]}
    assert W.allowed("workbench", bench) and not W.allowed("garden_plot", bench) and not W.allowed("moon_base", bench)
    assert not W.allowed("workbench", {**bench, "difficulty": 1})
    spec = {"capabilities": {"world": {"effect": "moon_base"}}}
    assert await W.apply(None, spec) is None and "world" not in spec["capabilities"]                              # unknown effects do nothing


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
async def test_without_a_game_master_using_a_thing_is_just_a_moment_spent_and_changes_nothing(tmp_path):
    s, st, *_ = make(tmp_path)
    t0 = time.time()
    c = build(st, {"description": "x", "capabilities": [{"type": "upkeep", "verb": "wound", "hours": 12}]}, name="clock", now=t0)
    before = st.creation(c["id"])["runtime"]["tended_until"]
    assert await cr.use(st, None, c, "wind it") == ("you spend a moment with your clock (wind it).", None)
    assert st.creation(c["id"])["runtime"]["tended_until"] == before


# --- using a thing (0.29.0: words, a mood, energy within limits, and which of its own actions Pip did) -------------------------------
class Told:
    def __init__(self, *outs):
        self.outs, self.calls = list(outs), []

    async def use(self, line, purpose, situation, actions=()):
        self.calls.append((line, purpose, situation, list(actions)))
        return self.outs.pop(0) if self.outs else None


@pytest.mark.asyncio
async def test_using_a_thing_word_for_word(tmp_path):
    s, st, *_ = make(tmp_path)
    t0 = time.time()
    st.update_agent(activity="idle", mood="calm", hunger=0.25, energy=0.5)
    c = build(st, {"description": "x", "capabilities": [{"type": "upkeep", "verb": "wound", "hours": 12}]}, name="clock", now=t0)
    acts = [{"name": "tend", "help": "wind it"}, {"name": "set", "help": "set it"}, {"nope": 1}, "x"]
    gm = Told({"text": "  You wind it,   slowly. ", "mood": "x" * 50, "energy": 0.4, "action": "tend"},
              {"text": "You look.", "energy": 0.1}, {"text": "You poke it.", "action": "dance", "energy": -0.05})
    text, action = await cr.use(st, gm, c, "wind it", t0, acts)
    assert (text, action) == ("You wind it, slowly.", "tend")                                        # the module tends it: no note
    line, purpose, situation, offered = gm.calls[0]
    assert line == cr.describe(c, t0) and purpose == "wind it" and situation == "Pip is idle, mood calm, hunger 0.2, energy 0.5."
    assert offered == acts[:2]
    a = st.agent()
    assert a["mood"] == "x" * 40 + "..." and a["energy"] == pytest.approx(0.6)                            # energy at most 0.1
    assert st.creation(c["id"])["runtime"]["last_energy_use"] == t0
    text, action = await cr.use(st, gm, st.creation(c["id"]), "look", t0 + cr.USE_ENERGY_COOLDOWN - 1, acts)
    assert action is None and text == "You look. (it keeps going for about 6 more hours; use the tend tool to keep it going)"
    assert st.agent()["energy"] == pytest.approx(0.6)                                               # within the cooldown: no change
    text, action = await cr.use(st, gm, st.creation(c["id"]), "poke", t0 + cr.USE_ENERGY_COOLDOWN, acts)
    assert action is None and st.agent()["energy"] == pytest.approx(0.55)                         # the cooldown has passed
    used = [e["data"] for e in st.events(5) if e["kind"] == "creation" and e["data"]["what"] == "used"]
    assert used[-1] == {"name": "clock", "what": "used", "text": "You wind it, slowly.", "purpose": "wind it"}
    st.set_runtime(c["id"], {**st.creation(c["id"])["runtime"], "halted_at": t0})
    assert await cr.use(st, gm, st.creation(c["id"]), "x", t0 + 10) == ("your clock has stopped - it needs tending (wound) first", None)
    plain = build(st, {"description": "x", "capabilities": [{"type": "timekeeper"}]}, name="sundial", now=t0)
    st.set_runtime(plain["id"], {**plain["runtime"], "halted_at": t0})
    assert await cr.use(st, gm, st.creation(plain["id"]), "x", t0 + 10) == ("your sundial has stopped", None)
    assert await cr.use(st, Told(), build(st, {"description": "a poem", "capabilities": []}, name="poem"), "read") == \
        ("you spend a moment with your poem (read).", None)                                         # the GM had nothing: a moment


def test_a_things_workings_must_offer_what_its_manifest_says_tends_it(tmp_path):
    from app import modules as M
    from tests.test_modules import live, modular, rule
    s, st, agent = modular(tmp_path)
    build(st, {"description": "x", "capabilities": [{"type": "upkeep", "verb": "wound", "hours": 12}]}, name="Clock")
    named = live(st, rule(kind="thing", name="clock-a", subject="Clock", hooks=["on_install"], proposes=["offer"], tends="wind"), "x")
    assert M.untended(st, named, ["tend"]) == "the Clock runs down: its workings must offer `wind`, or nobody could keep it going"
    assert M.untended(st, named, ["wind"]) == ""
    plain = live(st, rule(kind="thing", name="clock-b", subject="Clock", hooks=["on_install"], proposes=["offer"]), "x")
    assert M.untended(st, plain, ["tend"]) == "" and M.untended(st, plain, []).endswith("must offer `tend`, or nobody could keep it going")
    rule_m = live(st, rule(name="bells"), "x")
    assert M.untended(st, rule_m, []) == ""


@pytest.mark.asyncio
async def test_using_a_thing_keeps_to_its_limits(tmp_path):
    s, st, *_ = make(tmp_path)
    st.update_agent(energy=0.5, mood="calm")
    c = build(st, {"description": "a poem", "capabilities": []}, name="poem")
    gm = Told({"text": "w" * 400, "energy": -0.3, "mood": "glum"})
    text, _ = await cr.use(st, gm, c, "p" * 200)
    assert text == "w" * 300 + "..." and st.agent()["energy"] == pytest.approx(0.4) and st.agent()["mood"] == "glum"
    used = next(e["data"] for e in st.events(3) if e["kind"] == "creation")
    assert used["purpose"] == "p" * 120 + "..." and used["text"] == text
    gm2 = Told({"text": "Hm.", "energy": "lots"})
    await cr.use(st, gm2, c, "x", time.time() + cr.USE_ENERGY_COOLDOWN + 1)
    assert st.agent()["energy"] == pytest.approx(0.4)                                               # not a number: no change
