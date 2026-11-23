"""The second world (docs/DESIGN-world-packs.md, phase 6b): Ashfall, a small wasteland pack in worlds/ashfall, as the test that the engine
has no Pip in it. A simulated day runs with fake models: every word sent to them (the agent's prompts and tools, the narrator's tasks) and
every chat command's answer is recorded, and none of it may name anything of Pip's world."""
import json
import re
import time
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import commands
from app import modules as M
from app import world_pack as W
from app.config import Settings
from app.llm.base import LLMResponse, ToolCall, Usage

ASHFALL = Path(__file__).resolve().parent.parent / "worlds" / "ashfall"
PIPS_WORLD = re.compile(r"\b(Pip|Pip's|workshop|gardens?|tomato\w*|carrot\w*|Marigold|junkyard|woods|brass|clockwork|cottage|library)\b", re.I)
MODULES = ["cutaway", "scrap-heap", "shed", "round-tree", "pine-tree", "bench", "standing-stones", "lighthouse", "stall", "well", "outdoors",
           "market", "gathering", "crafting", "trade", "shelter", "raids", "village"]


class Recorder:
    """A fake model that keeps every word it is sent, and answers from a script (each a response, or a function of the tools offered)."""
    name, vision = "recorder", True

    def __init__(self, script=()):
        self.script, self.texts = list(script), []

    async def complete(self, system, messages, tools, max_tokens):
        self.texts.append("\n".join([system] + [m.get("content") if isinstance(m.get("content"), str) else json.dumps(m, default=str)
                                                for m in messages] + [f"{t.name}: {t.description} {json.dumps(t.parameters)}" for t in tools]))
        r = self.script.pop(0) if self.script else None
        return (r(tools) if callable(r) else r) or LLMResponse(text="...", usage=Usage(1, 1))


def act(tool, **args):
    return tool, args


class Day:
    """The agent's side of the day: each turn, the next of `plan` once its tool is offered and she isn't on the road (else she waits)."""
    def __init__(self, state, plan):
        self.state, self.plan = state, list(plan)

    def __call__(self, tools):
        sess = self.state.session()
        if not self.plan or (sess and sess["kind"] == "walk") or self.plan[0][0] not in {t.name for t in tools}:
            return None
        tool, args = self.plan.pop(0)
        return LLMResponse(text="", tool_calls=[ToolCall(id=f"c{time.time_ns()}", name=tool, arguments=args)], usage=Usage(1, 1))


DAY = [act("note_to_self", section="diary", text="The door seal is going again."), act("go_to", place="ruins"), act("gather", minutes=30),
       act("eat", item="tinned beans"), act("where_to", what="wire"), act("go_to", place="village"), act("say", to="Marta", text="Any work?"),
       act("go_to", place="home"), act("start_project", name="Door seal", goal="keep the ash out", steps=[{"name": "cut the rubber", "minutes": 30}]),
       act("recall", query="door"), act("feel", emotion="fear"), act("work_on", project="Door seal", minutes=30),
       act("experiment", project="Door seal", hypothesis="tyre rubber seals better than cloth"), act("set_activity", activity="mending", minutes=30),
       act("rest", minutes=60), act("sleep")]


@pytest.fixture
def ashfall():
    W.set_active(W.load(Settings(world_pack=str(ASHFALL))))
    yield W.active()
    W.set_active(W.load(Settings()))


def test_ashfall_is_a_world_of_its_own(ashfall):
    assert (ashfall.name, ashfall.agent.name, ashfall.agent.pronoun) == ("Ashfall", "Wren", "she")
    assert [n for _, n, _ in ashfall.modules] == MODULES and {w for w, _, _ in ashfall.modules} == {"std", "pack"}
    assert list(M.world_modules(Settings(world_pack=str(ASHFALL)))) == MODULES
    assert not PIPS_WORLD.search("\n".join(f.read_text() for f in ASHFALL.rglob("*") if f.is_file() and f.suffix in (".md", ".json")))


DAYS = [datetime(2026, 3, 9, 7), datetime(2026, 7, 21, 7), datetime(2026, 11, 2, 7)] + [
    datetime(2026, 1, 1, 7) + timedelta(days=12 * i) for i in range(int(os.environ.get("ASHFALL_MORE_DAYS", "0")))]   # more, by hand


@pytest.mark.parametrize("start", DAYS, ids=[d.date().isoformat() for d in DAYS])
async def test_a_day_in_ashfall_has_nothing_of_pips_world_in_it(tmp_path, ashfall, monkeypatch, start):
    from app.loop import Agent
    from app.pacing import get_policy
    from app.state import State
    clock = [start.timestamp()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    monkeypatch.delenv("TOOLS", raising=False)
    s = Settings(world_pack=str(ASHFALL), db_path=str(tmp_path / "a.db"), persona_path="/nonexistent", pacing="manual", min_tick_interval=0,
                 sleep=True, emotions="on", night_pass="apply", reflect_hour=21, modules="on", module_library="on", module_runner="local",
                 happenings="on")
    s.tools = Settings.from_env().tools + ["program"]
    st = State(s)
    narrator = Recorder()
    agent_llm = Recorder([Day(st, DAY * 3)] * 200)
    agent = Agent(s, st, agent_llm, get_policy(s), gm_backend=narrator)
    for step in range(48):                                   # a day, half an hour at a time
        clock[0] += 1800
        if step == 2:
            agent.receive("Morning. Did the ash get in last night?", "Travis")
        agent.check_world()
        await agent.resolve_world()
        await agent._tick("timer")
    assert {m["name"]: m["status"] for m in st.modules()} == {n: "live" for n in MODULES}
    did = {e["data"]["tool"] for e in st.events(1000) if e["kind"] == "tool"}
    assert {"go_to", "gather", "eat", "start_project", "work_on", "rest", "note_to_self"} <= did
    people = {c["name"]: (c["kind"], c["place"]) for c in st.characters()}
    assert people["Marta"] == ("villager", "village") and len(people) >= 1                 # villagers live at the village (one a day)
    said_to = [e["data"] for e in st.events(1000) if e["kind"] == "say" and e["data"].get("to_name") == "Marta"]
    results = [e["data"]["result"] for e in st.events(1000) if e["kind"] == "tool" and e["data"]["tool"] == "say"]
    assert said_to and any(r.startswith("said it to Marta") for r in results)               # in person, at the village
    assert len(agent_llm.texts) > 30 and narrator.texts
    said = agent_llm.texts + narrator.texts + [commands.answer(st, s, "/" + c) for c in commands._HANDLERS]
    leaks = sorted({PIPS_WORLD.search(t).group(0) + ": ..." + t[max(0, PIPS_WORLD.search(t).start() - 60): PIPS_WORLD.search(t).end() + 60]
                    for t in said if PIPS_WORLD.search(t)})
    assert leaks == []
    assert "Wren" in agent_llm.texts[0] and "health" in agent_llm.texts[0] and "radiation" in agent_llm.texts[0]


# --- what a pack chooses, and the engine adapting to it -----------------------------------------------------------------------------
def pack(tmp_path, modules, own=()):
    from tests.test_world_pack import pack_dir
    d = pack_dir(tmp_path, modules=modules)
    for name in own:
        (d / "modules").mkdir(exist_ok=True)
        (d / "modules" / f"{name}.json").write_text(json.dumps({"name": name, "kind": "rule", "api": 1, "hooks": ["on_install"]}))
        (d / "modules" / f"{name}.py").write_text("def on_install(ctx):\n    return {}\n")
    return d


def test_a_pack_names_the_engines_modules_and_its_own(tmp_path):
    d = pack(tmp_path, ["std:sky", {"module": "ashfall:still", "params": {"rate": 2}}, {"module": "std:gathering", "params": {"speed": 3}}], ["still"])
    p = W.load(Settings(world_pack=str(d)))
    assert p.modules == (("std", "sky", {}), ("pack", "still", {"rate": 2}), ("std", "gathering", {"speed": 3}))
    assert p.module("still")[0]["name"] == "still" and "def on_install" in p.module("still")[1]
    pips = W.load(Settings()).modules                                               # Pip's world names its own: the engine's and its three
    assert [n for w, n, _ in pips if w == "pack"] == ["gallery-wall", "stall-pictures", "home"] and len(pips) == len(M.RULES) + 3
    bare = pack(tmp_path / "bare", None, [])
    assert W.load(Settings(world_pack=str(bare))).modules is None                    # a pack that names none: everything the engine ships
    try:
        W.set_active(p)
        got = M.world_modules(Settings(world_pack=str(d), work_speed=5.0, hemisphere="south"))
        assert list(got) == ["sky", "still", "gathering"]
        assert got["still"][0]["params"] == {"rate": 2} and got["gathering"][0]["params"]["speed"] == 3   # the pack's params over the settings'
        assert got["sky"][0]["params"]["hemisphere"] == "south"
    finally:
        W.set_active(W.load(Settings()))
    crafting = M.world_modules(Settings(work_speed=5.0))["crafting"][0]["params"]       # the settings' over the module's own, which stay
    assert crafting["speed"] == 5.0 and crafting["abilities"] == M.library("crafting")[0]["params"]["abilities"]
    try:
        W.set_active(p)
        assert got["gathering"][0]["belongings"]["gives"] == []                       # a pack with no items.json has no kinds of thing
    finally:
        W.set_active(W.load(Settings()))


EACH = ('each of `modules` is "std:<name>" (the engine\'s), "ashfall:<name>" (the pack\'s own, in modules/), or '
        '{"module": ..., "params": {...}}')


@pytest.mark.parametrize("modules,why", [
    ("std:sky", "`modules` is a list"), (["sky"], EACH), (["std:Sky"], EACH), (["other:sky"], EACH), ([{"module": "std:sky", "params": []}], EACH),
    ([3], EACH), (["std:nope"], "no module std:nope: the engine ships none by that name"),
    (["ashfall:still"], "no module ashfall:still: modules/still.json and .py are needed"), (["std:sky", "std:sky"], "each module once in `modules`")])
def test_a_pack_that_names_its_modules_wrongly_is_refused(tmp_path, modules, why):
    d = pack(tmp_path, modules)
    with pytest.raises(W.PackError) as e:
        W.load(Settings(world_pack=str(d)))
    assert str(e.value) == f"world pack {d}: {why}"


def test_a_pack_module_must_be_called_what_its_file_is(tmp_path):
    d = pack(tmp_path, ["ashfall:still"], ["still"])
    (d / "modules" / "still.json").write_text(json.dumps({"name": "other", "kind": "rule", "api": 1}))
    try:
        W.set_active(W.load(Settings(world_pack=str(d))))
        with pytest.raises(W.PackError, match="modules/still.json names itself 'other'"):
            M.world_modules(Settings(world_pack=str(d)))
    finally:
        W.set_active(W.load(Settings()))


def test_a_world_without_seeds_gathers_none_and_designs_nothing_for_crops(ashfall):
    from app import creations as cr
    got = M.world_modules(Settings(world_pack=str(ASHFALL)))
    assert got["gathering"][0]["belongings"] == {"takes": [], "gives": ["tool", "material", "food"], "most": 20}
    menu = "\n".join(cr.menu(False))
    assert "crop_ripe" not in menu and "hurry_crops" not in menu and "visitor (someone comes to talk to Wren)" in menu   # Pip's world's, not this one's


def test_a_stat_can_change_faster_away_from_home(tmp_path, ashfall):
    from app import stats as stats_mod
    from app.state import State
    d = stats_mod.declared(Settings(world_pack=str(ASHFALL)))["radiation"]
    assert stats_mod.rate(d, "idle", False) == -0.01 and stats_mod.rate(d, "idle", False, away=True) == 0.03
    assert stats_mod.rate({"per_hour": 0.1}, "idle", False, away=True) == 0.1
    s = Settings(world_pack=str(ASHFALL), db_path=str(tmp_path / "a.db"), persona_path="/x")
    st = State(s)
    st.update_agent(radiation=0.5, updated_at=time.time() - 3600)
    st.apply_decay()
    assert st.agent()["radiation"] == pytest.approx(0.49, abs=1e-3)                  # at home in the shelter it falls
    st.update_agent(location="ruins", updated_at=time.time() - 3600)
    st.apply_decay()
    assert st.agent()["radiation"] == pytest.approx(0.52, abs=1e-3)                  # out in the ruins it builds
    st.update_agent(location="shelter", updated_at=time.time() - 3600)
    st.start_session(0, 0, 10, time.time() + 600, kind="walk", target="ruins")
    st.apply_decay()
    assert st.agent()["radiation"] == pytest.approx(0.55, abs=1e-3)                  # and on the road


def test_the_guide_tells_of_stakes_only_where_a_stat_can_run_out(ashfall):
    from app import guide
    s = Settings(world_pack=str(ASHFALL), sleep=True)
    assert "Out here you can get hurt." in guide.render({"say"}, s, False)
    assert "Out here you can get hurt." not in guide.render({"say"}, Settings(world_pack=str(ASHFALL), stats={"health": {"at_zero": None},
                                                                                                     "radiation": {"at_zero": None}}), False)


def test_coming_home_is_never_a_first_in_any_world(tmp_path, ashfall):
    from app.state import State
    st = State(Settings(world_pack=str(ASHFALL), db_path=str(tmp_path / "a.db"), persona_path="/x"))
    st.log("arrived", place="shelter")
    assert "firsts" not in st.events(1)[0]["data"]
    st.log("arrived", place="ruins")
    assert [f["key"] for f in st.events(1)[0]["data"]["firsts"]] == ["place:ruins"]


def test_a_pack_modules_own_params_and_belongings_are_kept_to_the_world(tmp_path):
    d = pack(tmp_path, [{"module": "ashfall:still", "params": {"b": 2}}, "ashfall:bare", {"module": "std:sky"}], ["still", "bare"])
    (d / "modules" / "still.json").write_text(json.dumps({"name": "still", "kind": "rule", "api": 1, "params": {"a": 1, "b": 1},
                                                          "belongings": {"takes": ["food", "seed"], "gives": ["tool"], "most": 2}}))
    (d / "items.json").write_text(json.dumps({"kinds": ["food", "tool"]}))
    try:
        W.set_active(W.load(Settings(world_pack=str(d))))
        got = M.world_modules(Settings(world_pack=str(d)))
        assert got["still"][0]["params"] == {"a": 1, "b": 2} and got["still"][0]["belongings"] == {"takes": ["food"], "gives": ["tool"], "most": 2}
        assert "params" not in got["bare"][0] and "belongings" not in got["bare"][0]       # nothing added to a module that has none
        assert W.load(Settings(world_pack=str(d))).modules[2] == ("std", "sky", {})
    finally:
        W.set_active(W.load(Settings()))


async def test_a_world_that_doesnt_run_a_shipped_module_switches_it_off(tmp_path):
    from app.state import State
    from tests.test_modules import live, rule
    s = Settings(db_path=str(tmp_path / "a.db"), persona_path="/x", module_library="on", modules="on", module_runner="local")
    st = State(s)
    garden = live(st, {**M.library("garden")[0], "params": M.library("garden")[0]["params"]}, M.library("garden")[1], author=M.SHIPPED)
    gone = live(st, rule(name="retired"), "x", author=M.SHIPPED)
    own = live(st, rule(name="mine"), "x", author="world")
    thing = live(st, rule(kind="thing", name="clockwork", subject="Gear Clock"), "x", author=M.SHIPPED)
    try:
        W.set_active(W.load(Settings(world_pack=str(ASHFALL))))
        await M.offer_library(st, Settings(world_pack=str(ASHFALL), db_path=s.db_path, module_library="on", modules="on"), M.LocalRunner())
    finally:
        W.set_active(W.load(Settings()))
    status = {m["id"]: (m["status"], m.get("note")) for m in st.modules()}
    assert status[garden["id"]] == ("disabled", "this world doesn't include it")
    assert status[gone["id"]] == ("disabled", "the engine no longer ships it")
    assert status[own["id"]][0] == "live" and status[thing["id"]][0] == "live"         # the world's own, and a creation's workings, stay


def test_without_a_home_named_the_agent_is_home_at_home(tmp_path):
    from app.state import State
    from tests.test_world_pack import pack_dir
    d = pack_dir(tmp_path)
    (d / "stats.json").write_text(json.dumps({"dust": {"start": 0.5, "per_hour": 0.0, "away_per_hour": 0.1, "asleep_per_hour": -0.1}}))
    s = Settings(world_pack=str(d), db_path=str(tmp_path / "a.db"), persona_path="/x")
    try:
        W.set_active(W.load(s))
        st = State(s)
        st.update_agent(location="home", updated_at=time.time() - 3600)
        st.apply_decay()
        assert st.agent()["dust"] == pytest.approx(0.5, abs=1e-3)
        st.update_agent(activity="sleeping", updated_at=time.time() - 3600)
        st.apply_decay()
        assert st.agent()["dust"] == pytest.approx(0.4, abs=1e-3)
    finally:
        W.set_active(W.load(Settings()))


def test_the_menu_of_this_worlds_sensors_and_helpers_word_for_word(ashfall):
    from app import creations as cr
    m = cr.menu(False)
    assert m[3] == ("sensor: it notices something and reacts; `condition` is one of visitor (someone comes to talk to Wren), dawn, dusk, "
                    "hurt (Wren is badly hurt), dosed (Wren has taken in too much radiation), hungry (Wren is hungry); `alert` is a short line "
                    "describing how it reacts")
    assert m[4] == ("helper: it regularly helps in one of these ways (`effect`): find (it turns up small useful things; give `finds`: 2-4 kinds "
                    "of thing it would find), purify (it cleans water or air, so Wren takes in less radiation), mend (Wren feels a little patched "
                    "up); give `line` (one sentence describing what it does) and `every_minutes`")


@pytest.mark.asyncio
async def test_a_water_filter_wren_makes_keeps_the_radiation_down(tmp_path, ashfall):
    from app import creations as cr
    from tests.test_workings import NOW, workings
    caps = {"helper": {"effect": "purify", "line": "The filter drips clean water into the can.", "every_minutes": 240}}
    import random
    raw = {"name": "Water Filter", "description": "a filter", "capabilities": [{"type": "helper", **caps["helper"]}]}
    spec = cr.sanitize_spec(raw, {"name": "x"}, "sound", [], random.Random(1))[2]
    assert spec["capabilities"]["helper"] == {"effect": "purify", "line": "The filter drips clean water into the can.", "every_minutes": 240}
    s, st, agent, c, m = await workings(tmp_path, caps, world_pack=str(ASHFALL))
    st.update_agent(radiation=0.5)
    assert await M.step(st, s, None, NOW + 241 * 60) is False
    assert round(st.agent()["radiation"], 3) == 0.47 and M.perception(st) == ["Things in the world:", "- The filter drips clean water into the can."]
    assert cr.at_work(st, caps, NOW)["helper"] == {**caps["helper"], "does": "affect:radiation:-0.03", "can": True}


def test_what_a_happening_finds_or_needs_mending_is_this_worlds(tmp_path, ashfall):
    import random
    from app import happenings as H
    from app.state import State
    s = Settings(world_pack=str(ASHFALL), db_path=str(tmp_path / "a.db"), persona_path="/x")
    st = State(s)
    flats = {e[0] for e in json.loads((ASHFALL / "items.json").read_text())["finds"]["flats"]}
    for seed in range(20):
        (found,) = H.decide(st, s, {"category": "salvage", "tone": "good", "severity": "medium", "effects": [{"kind": "item"}]},
                            time.time(), random.Random(seed))["effects"]
        assert found["name"] in flats                                                  # what turns up is what the wild places have
    from app import finds
    materials = {e[0] for table in json.loads((ASHFALL / "items.json").read_text())["finds"].values() for e in table if e[1] == "material"}
    mend = finds.mending()                                                             # what a thing that broke may need: this world's materials
    assert mend["things"] and set(mend["things"]) <= materials and "brass wire" not in mend["things"] and mend["qty"][0] >= 1
    named = H.decide(st, s, {"category": "salvage", "tone": "good", "effects": [{"kind": "item", "name": "copper wire"}]}, time.time(), random.Random(1))
    assert named["effects"][0]["name"] == "copper wire"
    with pytest.raises(ValueError, match="nothing called brass wire is found in this world"):
        H.decide(st, s, {"category": "salvage", "tone": "good", "effects": [{"kind": "item", "name": "brass wire"}]}, time.time(), random.Random(1))


def test_a_world_with_nothing_to_find_finds_nothing(tmp_path):
    import random
    from app import happenings as H
    from app.state import State
    from tests.test_world_pack import pack_dir
    d = pack_dir(tmp_path)
    s = Settings(world_pack=str(d), db_path=str(tmp_path / "a.db"), persona_path="/x")
    try:
        W.set_active(W.load(s))
        st = State(s)
        with pytest.raises(ValueError, match="^nothing is found in this world$"):
            H.decide(st, s, {"category": "found", "tone": "good", "effects": [{"kind": "item"}]}, time.time(), random.Random(1))
    finally:
        W.set_active(W.load(Settings()))


def test_the_ruins_can_be_browsed_and_the_flats_cannot(tmp_path, ashfall):
    from app import places
    from app import tools as T
    from app.state import State
    s = Settings(world_pack=str(ASHFALL), db_path=str(tmp_path / "a.db"), persona_path="/x")
    st = State(s)
    reg = places.registry(st, s, None)
    assert reg["ruins"].kind == "yard" and reg["flats"].kind == "wild"
    assert T.listed_here("browse", reg["ruins"]) and not T.listed_here("browse", reg["flats"]) and not T.listed_here("browse", None)
    assert not T.listed_here("gather", reg["village"])                                 # it lists nothing to do
    assert "browse" in {t.name for t in T.specs_for({"browse": T.REGISTRY["browse"]}, "ruins", reg["ruins"])}


def test_a_wild_place_with_nothing_listed_has_nothing_to_find(tmp_path):
    from app import happenings as H
    from tests.test_world_pack import pack_dir
    d = pack_dir(tmp_path)
    (d / "places.json").write_text(json.dumps({"home": {"key": "camp"}, "start": [{"key": "dunes", "kind": "wild", "description": "dunes"},
                                                                                  {"key": "pit", "kind": "yard", "description": "a pit"}]}))
    (d / "items.json").write_text(json.dumps({"kinds": ["material"], "finds": {"pit": [["bolts", "material", 1, [1, 2], "bolts", {}]]}}))
    try:
        W.set_active(W.load(Settings(world_pack=str(d))))
        assert H._tables("wild") == [] and [e[0] for e in H._tables("yard")] == ["bolts"]
        assert [e[0] for e in H._tables("sight")] == ["bolts"]                         # none of that kind: anything the world has
    finally:
        W.set_active(W.load(Settings()))


def test_the_app_starts_ashfall_with_ashfalls_belongings(tmp_path):
    """Live, 2026-11-15: the app made its State before the agent set the active world, so Wren started with Pip's seeds."""
    from fastapi.testclient import TestClient
    from app.llm.fake import FakeBackend
    from app.main import create_app
    W.set_active(W.load(Settings()))                                            # whatever ran before: Pip's world
    s = Settings(world_pack=str(ASHFALL), db_path=str(tmp_path / "a.db"), persona_path="/x", pacing="manual")
    try:
        with TestClient(create_app(s, FakeBackend())) as c:
            st = c.app.state.agent.state
            assert sorted(i["name"] for i in st.items()) == ["crowbar", "rad pills", "tinned beans"]
            assert st.agent()["location"] == "shelter"
    finally:
        W.set_active(W.load(Settings()))


def test_ashfall_has_six_agents_and_each_has_a_home_and_a_view(tmp_path):
    from fastapi.testclient import TestClient
    from app.llm.fake import FakeBackend
    from app.main import create_app
    pack = W.load(Settings(world_pack=str(ASHFALL)))
    assert [a.key for a in pack.agents] == ["wren", "ivo", "hester", "tobin", "sela", "marta"] and pack.agent.name == "Wren"
    homes = {a.key: a.home_place.get("key") for a in pack.agents[2:]}
    assert homes == {"hester": "cooperage", "tobin": "loft", "sela": "stillroom", "marta": "gatehouse"}
    assert all(pack.persona(a).startswith(f"You are {a.name}, ") for a in pack.agents[2:])
    assert {a.key: a.role for a in pack.agents} == {"wren": "survivor", "ivo": "scavenger", "hester": "villager", "tobin": "villager", "sela": "villager", "marta": "villager"}
    rests = {a.key: dict(a.temperament) for a in pack.agents}
    assert rests["hester"]["anger"] > rests["sela"].get("anger", 8) and rests["tobin"]["trust"] > rests["hester"]["trust"]   # grumpy, sunny
    assert rests["sela"]["fear"] > rests["tobin"]["fear"] and not rests["wren"] and not rests["ivo"]                         # and anxious
    assert pack.agent_named("marta").was == "Marta" and [a.key for a in pack.agents if a.was] == ["marta"]                    # the gate's villager, become an agent
    ivo = pack.agent_named("ivo")
    assert ivo.home_place["key"] == "lockup" and pack.persona(ivo).startswith("You are Ivo, a scavenger")
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(ASHFALL), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual")
    try:
        with TestClient(create_app(s, FakeBackend())) as c:
            assert c.get("/state?agent=ivo").json()["agent"]["location"] == "lockup"
            assert c.get("/state").json()["agent"]["location"] == "shelter"
            ivos = c.app.state.world.agents[1].state
            assert sorted(i["name"] for i in ivos.items()) == ["crowbar", "rad pills", "tinned beans"]
            for path in ("/world/scene", "/world/map", "/standing", "/events?limit=5"):
                assert c.get(f"{path}{'&' if '?' in path else '?'}agent=ivo").status_code == 200, path
            assert c.get("/world/scene?agent=ivo").json()["agent"]["name"] == "Ivo"
            assert c.get("/state?agent=hester").json()["agent"]["location"] == "cooperage"
            hester = c.app.state.world.agents[2].state
            assert hester.meta("met:tobin") and hester.meta("met:sela") and hester.meta("met:wren") is None   # neighbours; strangers met by chance
            assert [e["baseline"] for e in c.get("/emotions?agent=hester").json()["emotions"] if e["name"] == "anger"] == [25]
    finally:
        W.set_active(W.load(Settings()))


@pytest.mark.asyncio
async def test_both_homes_are_laid_out_and_on_the_map(tmp_path):
    from app import loop, world_view
    from app.llm.fake import FakeBackend
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(ASHFALL), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual",
                 module_library="on", modules="on")
    try:
        world = loop.build(s, FakeBackend())
        await world.step()
        world.check()
        wren, ivo, *_ = world.agents
        spots = wren.state.map_positions()
        assert spots["shelter"] == (0.0, 0.0) and spots["lockup"] != (0.0, 0.0)               # the middle is the first home's
        for a, home in ((wren, "shelter"), (ivo, "lockup")):
            with a.acting():
                scene = world_view.scene_view(a.state, s, None, home)
            assert scene["place"]["key"] == home and len(scene["layout"]["shapes"]) > 20, home     # Ashfall's shelter layout, for any home
    finally:
        W.set_active(W.load(Settings()))


@pytest.mark.asyncio
async def test_the_village_gate_is_a_market_where_salvage_sells(tmp_path, monkeypatch):
    """Live, 2026-11-16: Ivo stood at the gate for an hour and a half trying to sell copper wire to villagers who could only talk."""
    import datetime as dt
    from app import loop, places
    from app.llm.fake import FakeBackend
    from app.llm.base import ToolCall
    noon = dt.datetime.combine(dt.date.today(), dt.time(12)).timestamp()                 # the gate keeps hours
    monkeypatch.setattr(time, "time", lambda: noon)
    os.makedirs(tmp_path / "data")
    s = Settings(world_pack=str(ASHFALL), db_path=str(tmp_path / "data" / "agent.db"), persona_path="/x", pacing="manual",
                 module_library="on", modules="on")
    try:
        world = loop.build(s, FakeBackend())
        await world.step()
        ivo = world.agents[1]
        ivo.state.update_agent(location="village")
        ivo.state.add_item("copper wire", 5, "material", "wire stripped from a wall")
        await ivo.step()
        with ivo.acting():
            assert places.kind_of(ivo.state, "village") == "market" and {"browse", "buy", "sell"} <= ivo.tool_names()
            wares = (await ivo._run_tool(ToolCall(id="1", name="browse", arguments={}), 0))["content"]
            sold = (await ivo._run_tool(ToolCall(id="2", name="sell", arguments={"item": "copper wire", "quantity": 5}), 0))["content"]
        assert wares.startswith("In stock at the village today: "), wares
        assert sold.startswith("you sold 5 copper wire for "), sold
        assert ivo.state.find_item("copper wire")[0] is None and ivo.state.coins() > 0
    finally:
        W.set_active(W.load(Settings()))


def test_the_village_never_brings_a_villager_who_is_an_agent_now():
    """Marta became an agent (0.66.0): in a world where she runs as one, the village brings the next villager, not a second Marta."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("village", ASHFALL / "modules" / "village.py")
    village = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(village)
    ctx = {"time": {"hour": 10, "minute": 0, "season": ""}, "now": 1000.0, "params": {"broadcast_hour": 19}, "state": {"next": 1e10},
           "people": [], "agents": [{"key": "wren", "name": "Wren"}]}
    assert village.on_time(ctx)["character"]["name"] == "Marta"
    ctx["agents"].append({"key": "marta", "name": "Marta"})
    out = village.on_time(ctx)
    assert out["character"]["name"] == "Ezra" and out["state"]["brought"] == ["Ezra"]
    assert "agents" in json.loads((ASHFALL / "modules" / "village.json").read_text())["reads"]
