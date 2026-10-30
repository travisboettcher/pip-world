import random
import time

import pytest

from app import creations as cr
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
    await call(agent, "start_project", name="hourglass")  # GM plan fails -> 3 generic stages
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
    assert r.text == "You set it right. (it now shows the right time)"
    assert cr.clock_reading(st.creation(c["id"]), time.time())[1] == pytest.approx(0, abs=0.1)
    a = st.agent()
    assert a["mood"] == "pleased" and a["energy"] == pytest.approx(0.9 + 0.1)  # energy effect capped at 0.1
    build(st, {"description": "a poem", "capabilities": []}, name="poem")
    assert "doesn't need tending" in (await call(agent, "tend", creation="poem")).text


@pytest.mark.asyncio
async def test_use_can_stop_only_tended_things(tmp_path):
    s, st, gm, agent = make(tmp_path, [report(text="It sputters out.", stop=True), report(text="Hm.", stop=True)])
    build(st, {"description": "x", "capabilities": [{"type": "upkeep", "verb": "oil", "hours": 10}]}, name="lantern")
    r = await call(agent, "use_item", item="lantern", purpose="shake it")
    assert "it has stopped until you tend it (oil)" in r.text and not cr.running(st.creations()[0], time.time())
    assert "needs tending (oil)" in (await call(agent, "use_item", item="lantern", purpose="x")).text
    build(st, {"description": "a painting", "capabilities": []}, name="painting")
    r = await call(agent, "use_item", item="painting", purpose="admire it")
    assert r.text == "Hm." and cr.running(st.creations()[1], time.time())  # art can't be "stopped"
